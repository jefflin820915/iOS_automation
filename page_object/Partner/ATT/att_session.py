"""Session Page Object managing AT&T Connected Life lifecycle (relaunch every 10 runs) and sub-pages."""
import time
from typing import Any, Dict, Optional
from appium import webdriver
from appium.options.common import AppiumOptions
from appium.webdriver.webdriver import WebDriver
from selenium.common.exceptions import WebDriverException
from common import constants
from common.base_page import BasePage
from page_object.Partner.ATT.att_account_page import ATTAccountPage
from page_object.Partner.ATT.att_camera_live_page import ATTCameraLivePage
from page_object.Partner.ATT.att_common import DEFAULT_ATT_RELAUNCH_INTERVAL, resolve_att_bundle_id
from page_object.Partner.ATT.att_devices_page import ATTDevicesPage
from page_object.Partner.ATT.att_room_page import ATTRoomPage
from utils import logging_utils


class ATTSession:
    """Central entry point managing AT&T Connected Life (`att`) lifecycle and sub-page objects."""
    DEFAULT_RELAUNCH_INTERVAL: int = DEFAULT_ATT_RELAUNCH_INTERVAL
    WDA_ERROR_SIGNATURES = (
        "ECONNREFUSED",
        "Could not proxy command to the remote server",
        "socket hang up",
        "A session is either terminated or not started",
        "invalid session id",
        "NoSuchDriverError",
    )

    def __init__(self, driver: WebDriver) -> None:
        self.driver = driver
        self.timeout = getattr(constants, "DEFAULT_TIMEOUT_SECONDS", 15.0)
        self._logger = logging_utils.get_logger(__name__, "att_session")
        self.device_name: Optional[str] = None
        self.pairing_code: Optional[str] = None
        self.room_name: str = "Attic"
        self.iteration: Optional[int] = None
        self._run_counter: int = 0
        self.last_device_status: str = "UNKNOWN"
        self.last_google_account: str = ""
        self.device_tech_info: Dict[str, str] = {}
        bundle_id = resolve_att_bundle_id(driver)
        constants.ACTIVE_APP_BUNDLE_ID = bundle_id
        if driver is not None:
            try:
                setattr(driver, "_active_app_bundle_id", bundle_id)
            except Exception:
                pass
        for cls in (ATTDevicesPage, ATTRoomPage, ATTCameraLivePage, ATTAccountPage):
            page_instance = cls(driver)
            page_instance.session = self
            setattr(self, cls.__name__.lower(), page_instance)

    def __getattr__(self, name: str) -> Any:
        """Delegate missing method/attribute lookups across all registered AT&T page objects."""
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        for val in self.__dict__.values():
            if isinstance(val, BasePage) and hasattr(val, name):
                return getattr(val, name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    @classmethod
    def _resolve_session(cls, ctx: Any) -> "ATTSession":
        if isinstance(ctx, cls):
            return ctx
        session = getattr(ctx, "session", None)
        if isinstance(session, cls):
            return session
        return ctx

    @classmethod
    def _is_wda_connection_error(cls, exc: Exception) -> bool:
        msg = str(exc)
        return any(sig in msg for sig in cls.WDA_ERROR_SIGNATURES)

    def _reconnect_wda_driver(self) -> bool:
        """Rebuild Appium WebDriver session in-place if WDA disconnects during long unattended loops."""
        self._logger.warning("[WDA Reconnect] Rebuilding Appium WebDriver session for AT&T...")
        try:
            self.driver.quit()
        except Exception:
            pass
        try:
            options = AppiumOptions()
            options.load_capabilities(constants.IOS_CAPABILITIES)
            new_driver = webdriver.Remote(constants.APPIUM_SERVER_URL, options=options)
            new_driver.implicitly_wait(getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0))
            bundle_id = resolve_att_bundle_id(new_driver)
            setattr(new_driver, "_active_app_bundle_id", bundle_id)
            self.driver.__dict__.update(new_driver.__dict__)
            self._logger.info(
                f"[WDA Reconnect] Re-established WDA session (session_id={self.driver.session_id})."
            )
            return True
        except Exception as err:
            self._logger.error(f"[WDA Reconnect] Failed to rebuild WDA session: {err}")
            return False

    def ensure_device_unlocked(self) -> bool:
        sess = ATTSession._resolve_session(self)
        try:
            if hasattr(sess.driver, "is_locked") and sess.driver.is_locked():
                return BasePage._unlock_device_if_locked(sess)
            return True
        except WebDriverException as err:
            if sess._is_wda_connection_error(err) and sess._reconnect_wda_driver():
                return BasePage._unlock_device_if_locked(sess)
            sess._logger.warning(f"Failed checking lock state: {err}")
            return False

    def _is_att_running(self) -> bool:
        bundle_id = resolve_att_bundle_id(self.driver)
        fg_state = getattr(constants, "APP_STATE_FOREGROUND", 4)
        try:
            return self.driver.query_app_state(bundle_id) == fg_state
        except WebDriverException as err:
            self._logger.error(f"Failed to query AT&T app state ({bundle_id}): {err}")
            return False

    def start_att(self, timeout: float = 15.0) -> bool:
        """Bring AT&T Connected Life app to the foreground and wait for state == foreground."""
        sess = ATTSession._resolve_session(self)
        bundle_id = resolve_att_bundle_id(sess.driver)
        constants.ACTIVE_APP_BUNDLE_ID = bundle_id
        try:
            setattr(sess.driver, "_active_app_bundle_id", bundle_id)
            setattr(sess.driver, "_att_started", True)
        except Exception:
            pass
        sess.ensure_device_unlocked()
        if sess._is_att_running():
            sess._logger.info(
                f"AT&T Connected Life ('{bundle_id}') is already active in foreground.")
            return True
        sess._logger.info(f"Starting AT&T Connected Life ('{bundle_id}') on iOS...")
        try:
            sess.driver.activate_app(bundle_id)
        except WebDriverException as err:
            if sess._is_wda_connection_error(err) and sess._reconnect_wda_driver():
                sess.driver.activate_app(resolve_att_bundle_id(sess.driver))
            else:
                sess._logger.error(f"Failed to activate AT&T app: {err}")
                return False
        start_ts = time.time()
        while (time.time() - start_ts) < timeout:
            if sess._is_att_running():
                sess._logger.info("AT&T Connected Life launched successfully in foreground.")
                time.sleep(1.0)
                return True
            try:
                sess.driver.activate_app(bundle_id)
            except WebDriverException:
                pass
            time.sleep(0.8)
        sess._logger.error(
            f"Timed out after {timeout}s waiting for AT&T Connected Life to foreground.")
        return False

    def stop_att(self) -> bool:
        """Terminate AT&T Connected Life so the next launch starts from a clean process."""
        sess = ATTSession._resolve_session(self)
        bundle_id = resolve_att_bundle_id(sess.driver)
        not_running_state = getattr(constants, "APP_STATE_NOT_RUNNING", 1)
        try:
            app_state = sess.driver.query_app_state(bundle_id)
            if app_state != not_running_state:
                sess.driver.terminate_app(bundle_id)
                sess._logger.info(f"AT&T Connected Life ('{bundle_id}') stopped successfully.")
                time.sleep(1.0)
            else:
                sess._logger.info(f"AT&T Connected Life ('{bundle_id}') is not running.")
            return True
        except WebDriverException as err:
            if sess._is_wda_connection_error(err) and sess._reconnect_wda_driver():
                try:
                    bundle_id = resolve_att_bundle_id(sess.driver)
                    if sess.driver.query_app_state(bundle_id) != not_running_state:
                        sess.driver.terminate_app(bundle_id)
                    return True
                except WebDriverException:
                    return False
            sess._logger.error(f"Failed to stop AT&T app: {err}")
            return False

    def prepare_app_for_iteration(
            self,
            iteration: Optional[int] = None,
            relaunch_interval: Optional[int] = None,
    ) -> bool:
        """Prepare AT&T app for the current iteration, relaunching every `relaunch_interval` runs (default 10).
        - Iterations 1, 11, 21, ... (`(iter - 1) % 10 == 0`): full terminate + relaunch.
        - Iterations 2..10, 12..20, ...: keep app running without terminating, ensure foreground
          and return cleanly to the `Devices` tab (with emergency relaunch only if recovery fails).
        """
        sess = ATTSession._resolve_session(self)
        ctx_iter = getattr(self, "iteration", None) if not isinstance(self, ATTSession) else None
        raw_iter = iteration if iteration is not None else (
            ctx_iter if ctx_iter is not None else sess.iteration)
        if raw_iter is not None and int(raw_iter) > 0:
            iter_num = int(raw_iter)
            sess._run_counter = iter_num
        else:
            sess._run_counter += 1
            iter_num = sess._run_counter
        interval = int(
            relaunch_interval
            if relaunch_interval is not None
            else getattr(constants, "ATT_RELAUNCH_INTERVAL", sess.DEFAULT_RELAUNCH_INTERVAL)
        )
        interval = max(1, interval)
        should_relaunch = (iter_num == 1) or ((iter_num - 1) % interval == 0)
        if should_relaunch:
            sess._logger.info(
                f"[ATT Lifecycle] Iteration #{iter_num} (relaunch every {interval} runs): "
                "relaunching AT&T Connected Life app..."
            )
            sess.stop_att()
            if not sess.start_att():
                return False
            ATTDevicesPage.go_to_devices_tab(sess)
            return True
        remaining = interval - ((iter_num - 1) % interval)
        sess._logger.info(
            f"[ATT Lifecycle] Iteration #{iter_num} (relaunch every {interval} runs, "
            f"{remaining} run(s) until next relaunch): reusing running AT&T app..."
        )
        if not sess.start_att():
            return False
        try:
            ATTDevicesPage.go_to_devices_tab(sess)
            return True
        except Exception as recover_err:
            sess._logger.warning(
                f"[ATT Lifecycle] Could not recover running AT&T app to Devices tab ({recover_err}); "
                "forcing emergency relaunch..."
            )
            sess.stop_att()
            if not sess.start_att():
                return False
            ATTDevicesPage.go_to_devices_tab(sess)
            return True
