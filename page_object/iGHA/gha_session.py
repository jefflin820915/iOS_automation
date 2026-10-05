"""Session Page Object managing iGHA lifecycle and aggregating all sub-page objects."""
import threading
import time
import tomllib
from typing import Optional, Any
from appium import webdriver
from appium.options.common import AppiumOptions
from appium.webdriver.webdriver import WebDriver
from selenium.common.exceptions import WebDriverException, StaleElementReferenceException
from common import constants
from common.base_page import BasePage
from page_object.iGHA.gha_home_page import GHAHomePage
from page_object.iGHA.gha_account_picker import GHAAccountPicker
from page_object.iGHA.gha_device_page import GHADevicePage
from page_object.iGHA.gha_setup_device_page import GHASetUpDevicePage
from page_object.iGHA.gha_add_page import GHAAddPage
from page_object.iGHA.gha_add_device_page import GHAAddDevicePage
from page_object.iGHA.gha_enter_pairing_code_page import GHAEnterPairingCodePage
from page_object.iGHA.gha_privacy_guidelines_page import GHAPrivacyGuidelinesPage
from page_object.iGHA.gha_help_improve_camera_device_page import GHAHelpImproveCameraDevicePage
from page_object.iGHA.gha_watch_setup_video_page import GHAWatchSetupVideoPage
from page_object.iGHA.gha_connect_device_to_google_account_page import GHAConnectDeviceToGoogleAccountPage
from page_object.iGHA.gha_commission_flow import GHACommissioningPageObject
from page_object.iGHA.gha_where_is_this_device_page import GHAWhereIsThisDevicePage
from page_object.iGHA.gha_camera_activated_page import GHACameraActivatedPage
from page_object.iGHA.gha_you_should_now_see_live_video_page import GHAYouShouldNowSeeLiveVideoPage
from page_object.iGHA.gha_adjust_your_mic_settings import GHAAdjustYourMicSettingsPage
from page_object.iGHA.gha_stay_in_the_know_page import GHAStayInTheKnowPage
from page_object.iGHA.gha_your_camera_device_is_ready_page import GHAYourCameraDeviceIsReadyPage
from page_object.iGHA.gha_setting_page import GHASettingsPage
from page_object.iGHA.gha_tab_page import GHATabPage
from page_object.iGHA.gha_device_setting_page import GHADeviceSettingPage
from page_object.iGHA.gha_camera_live_page import GHACameraLivePage
from page_object.iGHA.gha_single_device_found_page import GHASingleDeviceFoundPage
from utils import logging_utils
from utils.camera_reset_utils import DeviceResetUtils
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from page_object.iGHA.gha_choose_whether_you_want_to_turn_on_video_history import (
    GHAChooseWhetherYouWantToTurnOnVideoPage,
)
from page_object.iGHA.gha_exceptions import OOBEInternalErrorException


class GHASession:
    """Central entry point managing iGHA application lifecycle and sub-page objects."""
    EMERGENCY_REMOVE_ATTEMPTS = 2
    WDA_ERROR_SIGNATURES = (
        "ECONNREFUSED",
        "Could not proxy command to the remote server",
        "socket hang up",
        "A session is either terminated or not started",
        "invalid session id",
        "NoSuchDriverError",
    )

    def __init__(self, driver: WebDriver) -> None:
        """Initialize GHASession with Appium driver and instantiate all iGHA page objects.
        Args:
            driver (WebDriver): The active Appium WebDriver instance.
        """
        self.driver = driver
        self.timeout = getattr(constants, "DEFAULT_TIMEOUT_SECONDS", 15.0)
        self._logger = logging_utils.get_logger(__name__, "gha_session")
        self._gha_stopped_in_cleanup = False
        self._device_removed_in_emergency = False
        page_classes = [
            GHAHomePage,
            GHAAccountPicker,
            GHADevicePage,
            GHASetUpDevicePage,
            GHAAddPage,
            GHAAddDevicePage,
            GHAEnterPairingCodePage,
            GHAPrivacyGuidelinesPage,
            GHAHelpImproveCameraDevicePage,
            GHAWatchSetupVideoPage,
            GHAConnectDeviceToGoogleAccountPage,
            GHACommissioningPageObject,
            GHAWhereIsThisDevicePage,
            GHACameraActivatedPage,
            GHAYouShouldNowSeeLiveVideoPage,
            GHAChooseWhetherYouWantToTurnOnVideoPage,
            GHAAdjustYourMicSettingsPage,
            GHAStayInTheKnowPage,
            GHAYourCameraDeviceIsReadyPage,
            GHASettingsPage,
            GHATabPage,
            GHADeviceSettingPage,
            GHACameraLivePage
        ]
        for cls in page_classes:
            attr_name = cls.__name__.lower()
            page_instance = cls(driver)
            page_instance.session = self
            setattr(self, attr_name, page_instance)

    def __getattr__(self, name: str) -> Any:
        """Automatically delegate method lookup across all registered pages."""
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        for page in self.__dict__.values():
            if hasattr(page, name):
                return getattr(page, name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    @classmethod
    def _is_wda_connection_error(cls, exc: Exception) -> bool:
        """Return True if the exception indicates WDA (127.0.0.1:8100) or the Appium session disconnected."""
        msg = str(exc)
        return any(sig in msg for sig in cls.WDA_ERROR_SIGNATURES)

    def _reconnect_wda_driver(self) -> bool:
        """Rebuild the Appium WebDriver session in-place when WDA (127.0.0.1:8100) disconnects."""
        self._logger.warning(
            "[WDA Reconnect] Detected dead WDA connection (127.0.0.1:8100). Rebuilding Appium WebDriver session..."
        )
        device_tech_info = getattr(self.driver, "device_tech_info", None)
        try:
            self.driver.quit()
        except Exception:
            pass
        try:
            options = AppiumOptions()
            options.load_capabilities(constants.IOS_CAPABILITIES)
            new_driver = webdriver.Remote(constants.APPIUM_SERVER_URL, options=options)
            new_driver.implicitly_wait(getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0))
            if device_tech_info is not None:
                new_driver.device_tech_info = device_tech_info
            self.driver.__dict__.update(new_driver.__dict__)
            self._logger.info(
                f"[WDA Reconnect] Successfully re-established Appium/WDA session (session_id={self.driver.session_id})."
            )
            return True
        except Exception as reconnect_err:
            self._logger.error(f"[WDA Reconnect] Failed to rebuild Appium WebDriver session: {reconnect_err}")
            return False

    def _get_device_grid_view(self):
        """Locates the main device grid collection view on the GHA home page."""
        return self.driver.find_element(
            AppiumBy.ACCESSIBILITY_ID, "deviceTileGridCollectionView"
        )

    def _pull_down_to_refresh(self, element) -> None:
        """Performs a downward drag gesture on the element to trigger iOS pull-to-refresh."""
        rect = element.rect
        center_x = rect["x"] + rect["width"] // 2
        start_y = rect["y"] + int(rect["height"] * 0.15)
        end_y = rect["y"] + int(rect["height"] * 0.65)
        actions = ActionChains(self.driver)
        actions.w3c_actions = ActionBuilder(
            self.driver, mouse=PointerInput(interaction.POINTER_TOUCH, "touch")
        )
        actions.w3c_actions.pointer_action.move_to_location(center_x, start_y)
        actions.w3c_actions.pointer_action.pointer_down()
        actions.w3c_actions.pointer_action.pause(0.3)
        actions.w3c_actions.pointer_action.move_to_location(center_x, end_y)
        actions.w3c_actions.pointer_action.pause(0.5)
        actions.w3c_actions.pointer_action.pointer_up()
        actions.perform()

    def _dismiss_setup_new_devices_sheet(self, timeout: float = 10.0) -> bool:
        """Check for and dismiss the 'Set up new devices?' bottom sheet if it appears after launch.
        Args:
            timeout (float): Max time in seconds to poll for the bottom sheet (defaults to 5.0s).
        Returns:
            bool: True if the sheet was detected and dismissed, False otherwise.
        """
        self._logger.info(f"Checking for 'Set up new devices?' bottom sheet (polling up to {timeout}s)...")
        start_time = time.time()
        not_now_locators = [
            (AppiumBy.XPATH, '//XCUIElementTypeButton[@name="actionBarSecondaryButton" or @name="Not now" or @label="Not now"]'),
            (AppiumBy.XPATH, '//XCUIElementTypeStaticText[@name="Not now" or @label="Not now"]'),
            (AppiumBy.ACCESSIBILITY_ID, "actionBarSecondaryButton"),
            (AppiumBy.ACCESSIBILITY_ID, "Not now")
        ]
        while time.time() - start_time < timeout:
            try:
                self.driver.implicitly_wait(0)
                for by, loc in not_now_locators:
                    btns = self.driver.find_elements(by, loc)
                    for btn in btns:
                        try:
                            if btn.is_displayed():
                                self._logger.info("Detected 'Set up new devices?' prompt. Clicking 'Not now'...")
                                btn.click()
                                time.sleep(1.0)
                                return True
                        except (StaleElementReferenceException, WebDriverException):
                            continue
            except Exception:
                pass
            finally:
                self.driver.implicitly_wait(getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0))
            time.sleep(0.5)
        self._logger.info("No 'Set up new devices?' bottom sheet detected. Continuing.")
        return False

    def _emergency_recover_and_remove_device(self, attempts: int = EMERGENCY_REMOVE_ATTEMPTS) -> bool:
        """Restart GHA and remove the (already commissioned) device so the next run starts clean.
        Note: Hardware reset (smart plug on/off + ADB factory reset) is only run during 'post-test cleanup'.
        Returns:
            True if handle_remove_device() completed without raising.
        """
        removed = False
        for attempt in range(1, attempts + 1):
            self._logger.warning(
                f"[Emergency Teardown] Attempt {attempt}/{attempts}: restarting GHA to reset navigation state..."
            )
            try:
                self.stop_gha()
                time.sleep(2.0)
                self.start_gha()
                time.sleep(5.0)
                self._logger.info("[Emergency Teardown] Navigating to Settings to remove device...")
                GHATabPage.enter_home_settings_page(self)
                GHASettingsPage.open_device_settings(self, device_name=self.device_name)
                self.handle_remove_device()
                removed = True
                self._device_removed_in_emergency = True
                self._logger.info("[Emergency Teardown] Device successfully removed during emergency cleanup.")
                break
            except Exception as cleanup_err:
                self._logger.error(f"[Emergency Teardown] Attempt {attempt}/{attempts} failed: {cleanup_err}")
        try:
            self.refresh_gha_devices()
        except Exception as refresh_err:
            self._logger.warning(f"[Emergency Teardown] Refresh GHA devices failed: {refresh_err}")
        return removed

    def _start_wda_keepalive(self, interval_seconds: float = 15.0) -> threading.Event:
        """Send a lightweight query_app_state command every interval_seconds to prevent Appium's 60s newCommandTimeout."""
        stop_event = threading.Event()
        def _heartbeat() -> None:
            while not stop_event.wait(interval_seconds):
                try:
                    self.driver.query_app_state(constants.GHA_BUNDLE_ID)
                except Exception as hb_err:
                    self._logger.debug(f"[WDA KeepAlive] Heartbeat ignored error: {hb_err}")
        thread = threading.Thread(target=_heartbeat, name="wda-keepalive", daemon=True)
        thread.start()
        return stop_event

    def reset_target_device(self, reason: str = "post-test cleanup") -> bool:
        """Reset devices at post-test cleanup by executing BOTH Smart plug power-cycle AND ADB factory reset.
        Does not branch by device_name: every test cleanup runs:
        1. GHACommissioningPageObject.power_cycle_smart_plug(self) (plug on/off)
        2. stop_gha() while WDA is active + 15s WDA keep-alive heartbeat during ADB reset
        3. DeviceResetUtils.adb_factory_reset(...) (`ftsmisc -s reboot_mode factory_reset; reboot -f`)
        Args:
            reason: Short context for the log (e.g. 'post-test cleanup').
        Returns:
            True if both reset steps succeeded.
        """
        device = str(getattr(self, "device_name", "") or "ALL")
        self._logger.info(
            f"[Device Reset] '{device}' -> Smart plug power-cycle + ADB factory reset ({reason or 'n/a'})"
        )
        plug_ok = False
        try:
            self._logger.info("[Device Reset] Step 1/2: Running Smart plug power-cycle (plug on/off)...")
            GHACommissioningPageObject.power_cycle_smart_plug(self)
            plug_ok = True
            self._logger.info("[Device Reset] Step 1/2: Smart plug power-cycle SUCCESS.")
        except Exception as plug_err:
            self._logger.error(f"[Device Reset] Step 1/2: Smart plug power-cycle FAILED: {plug_err}")
        try:
            if self.stop_gha():
                self._gha_stopped_in_cleanup = True
        except Exception:
            pass
        self._logger.info("[Device Reset] Step 2/2: Running ADB factory reset (with WDA keep-alive)...")
        stop_keepalive = self._start_wda_keepalive(interval_seconds=15.0)
        try:
            adb_target = device if DeviceResetUtils.get_config(device) is not None else "Ref2 Battery Camera"
            adb_ok = DeviceResetUtils.adb_factory_reset(adb_target, reason=reason)
        finally:
            stop_keepalive.set()
        self._logger.info(f"[Device Reset] Step 2/2: ADB factory reset {'SUCCESS' if adb_ok else 'FAILED'}.")
        ok = plug_ok and adb_ok
        self._logger.info(
            f"[Device Reset] Result for '{device}' ({reason or 'n/a'}): "
            f"smart_plug={'SUCCESS' if plug_ok else 'FAILED'}, adb_reset={'SUCCESS' if adb_ok else 'FAILED'}."
        )
        return ok

    def refresh_gha_devices(self, timeout: float = 5.0) -> None:
        """Refresh all devices in the Google Home App (iOS).
        Performs a pull-to-refresh on deviceTileGridCollectionView and waits
        for the iOS activity spinner to disappear.
        Args:
            timeout: The maximum time in seconds to wait for refresh to complete.
                     Defaults to 5 seconds.
        """
        try:
            time.sleep(3)
            grid_view = self._get_device_grid_view()
            self._pull_down_to_refresh(grid_view)
            time.sleep(0.5)
            spinner_locator = (
                AppiumBy.IOS_CLASS_CHAIN,
                "**/XCUIElementTypeActivityIndicator",
            )
            WebDriverWait(self.driver, timeout).until(
                EC.invisibility_of_element_located(spinner_locator)
            )
            self._logger.info("GHA has been refreshed.")
        except TimeoutException:
            self._logger.critical(f"Refresh too long..., timeout: {timeout}")
        except Exception as e:
            self._logger.error(f"Failed to refresh GHA devices: {e}")

    def _is_gha_running(self) -> bool:
        """Check if GHA is currently running in the active foreground."""
        try:
            return self.driver.query_app_state(constants.GHA_BUNDLE_ID) == constants.APP_STATE_FOREGROUND
        except WebDriverException as e:
            self._logger.error(f"Failed to query GHA app state: {e}")
            return False

    def stop_gha(self) -> bool:
        """Terminate the GHA application, with automatic WDA fallback and self-healing."""
        try:
            app_state = self.driver.query_app_state(constants.GHA_BUNDLE_ID)
            if app_state != constants.APP_STATE_NOT_RUNNING:
                self.driver.terminate_app(constants.GHA_BUNDLE_ID)
                self._logger.info("GHA stopped successfully.")
            else:
                self._logger.info("GHA is not running.")
            self._gha_stopped_in_cleanup = False
            return True
        except WebDriverException as e:
            if getattr(self, "_gha_stopped_in_cleanup", False):
                self._gha_stopped_in_cleanup = False
                self._logger.warning(
                    f"[WDA] WDA connection dropped during post-test ADB reset ({e}), "
                    "but GHA was already stopped prior to Step 2/2. Treating stop_gha() as SUCCESS "
                    "so ScreenRecorder can finish saving the current video."
                )
                return True
            if self._is_wda_connection_error(e):
                self._logger.warning(f"Failed to stop GHA due to WDA disconnect ({e}). Attempting WDA reconnect...")
                if self._reconnect_wda_driver():
                    try:
                        app_state = self.driver.query_app_state(constants.GHA_BUNDLE_ID)
                        if app_state != constants.APP_STATE_NOT_RUNNING:
                            self.driver.terminate_app(constants.GHA_BUNDLE_ID)
                            self._logger.info("GHA stopped successfully after WDA reconnect.")
                        else:
                            self._logger.info("GHA is not running (verified after WDA reconnect).")
                        return True
                    except WebDriverException as retry_err:
                        self._logger.error(f"Failed to stop GHA after WDA reconnect: {retry_err}")
                        return False
            self._logger.error(f"Failed to stop GHA: {e}")
            return False

    def start_gha(self, timeout: float = 10.0) -> bool:
        """Start GHA and ensure it is running in the active foreground."""
        self._gha_stopped_in_cleanup = False
        if self._is_gha_running():
            self._logger.info("GHA is already running in foreground.")
            return True
        self._logger.info("Starting Google Home App on iOS...")
        try:
            self.driver.activate_app(constants.GHA_BUNDLE_ID)
            self._dismiss_setup_new_devices_sheet()
        except WebDriverException as e:
            if self._is_wda_connection_error(e) and self._reconnect_wda_driver():
                try:
                    self.driver.activate_app(constants.GHA_BUNDLE_ID)
                    self._dismiss_setup_new_devices_sheet()
                except WebDriverException as retry_err:
                    self._logger.error(f"Failed to activate GHA after WDA reconnect: {retry_err}")
                    return False
            else:
                self._logger.error(f"Failed to activate GHA: {e}")
                return False
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self._is_gha_running():
                self._logger.info("GHA launched successfully in foreground.")
                return True
            try:
                self.driver.activate_app(constants.GHA_BUNDLE_ID)
            except WebDriverException:
                pass
        self._logger.error(f"Timed out after {timeout}s waiting for GHA.")
        return False

    def _restart_gha_to_home(self) -> None:
        """Terminate and relaunch GHA so navigation starts from the home screen."""
        self.stop_gha()
        time.sleep(2.0)
        if not self.start_gha():
            self._logger.warning("[Device Selection] GHA did not come to foreground after restart.")
        time.sleep(3.0)

    def _try_select_target_device_once(self, target_name: str, swallow_errors: bool) -> bool:
        """One pass: open 'Set up device' and select the target (single-device screen or list).
        Args:
            target_name: Device name to select.
            swallow_errors: If True, navigation errors are logged and treated as 'not found'
                (so the caller can retry). If False, they propagate with their original traceback.
        """
        try:
            nav_result = GHAAddPage.navigate_to_setup_device_page(self)
            if nav_result is False:
                self._logger.error("[Device Selection] Failed to open 'Set up device' page.")
                return False
        except Exception as nav_err:
            if not swallow_errors:
                raise
            self._logger.error(f"[Device Selection] Navigation to 'Set up device' failed: {nav_err}")
            return False
        self._logger.info("Checking for Single Device Found screen before checking list...")
        try:
            if GHASingleDeviceFoundPage.handle_if_present(self, target_device_name=target_name, timeout=3.0):
                self._logger.info(f"Target device '{target_name}' successfully confirmed and selected via Single Device screen!")
                time.sleep(2.0)
                return True
        except Exception as e:
            self._logger.warning(f"Error checking Single Device screen: {e}")
        self._logger.info(f"Single device not present or switched to list. Searching '{target_name}' in device list...")
        return GHASetUpDevicePage.is_device_exist_in_setup_device_page(self, device_name=target_name)

    def _recover_device_discovery(self) -> None:
        """Relaunch GHA to home and refresh the device grid so discovery starts fresh.
        Note: Hardware reset (smart plug on/off + ADB factory reset) is only run during 'post-test cleanup'.
        """
        self._logger.warning("[Device Selection] Recovering discovery: restarting GHA and refreshing devices...")
        self._restart_gha_to_home()
        self.refresh_gha_devices()
        self._restart_gha_to_home()

    def handle_device_selection_steps(self) -> bool:
        """Navigate to Add Device page and select target device.
        Handles both:
        1. Single device branch: Directly shows 'Next' button -> Clicks Next.
        2. Multi-device branch: Shows nearby device list -> Selects device from list.
        If the target is not discovered, restarts GHA, refreshes, and searches again
        (up to constants.DEVICE_SELECTION_MAX_ATTEMPTS total attempts).
        Raises:
            AssertionError: If the target is still not discovered after all attempts.
        """
        target_name = str(getattr(self, "device_name", "") or "")
        max_attempts = max(1, int(getattr(constants, "DEVICE_SELECTION_MAX_ATTEMPTS", 2)))
        for attempt in range(1, max_attempts + 1):
            is_last = attempt == max_attempts
            self._logger.info(f"[Device Selection] Attempt {attempt}/{max_attempts} for '{target_name}'...")
            if self._try_select_target_device_once(target_name, swallow_errors=not is_last):
                if attempt > 1:
                    self._logger.info(
                        f"[Device Selection] '{target_name}' found after GHA restart recovery (attempt {attempt})."
                    )
                return True
            if not is_last:
                self._logger.warning(
                    f"[Device Selection] '{target_name}' not discovered on attempt {attempt}/{max_attempts}. "
                    "Restarting GHA and retrying..."
                )
                self._recover_device_discovery()
        message = (
            f"[Device Selection] '{target_name}' not discovered after {max_attempts} attempt(s)."
        )
        self._logger.error(message)
        raise AssertionError(message)

    def pair_device_with_pairing_code(self) -> None:
        """Open the Enter pairing code page and submit the manual pairing code.
        Raises:
            RuntimeError: If any step of pairing code entry fails.
        """
        code = str(getattr(self, "pairing_code", "") or "")
        self._logger.info(
            f"[PairingCode] Device='{getattr(self, 'device_name', '')}' | pairing_code length={len(code)}"
        )
        if not GHAAddDevicePage.click_use_pairing_code_btn(self):
            raise RuntimeError("Failed to open 'Enter pairing code' page.")
        if not GHAEnterPairingCodePage.enter_pairing_code(self, pairing_code=code):
            raise RuntimeError("Failed to enter pairing code or proceed with 'Continue'.")

    def handle_setup_requirement_pages(self) -> None:
        """Handle privacy guidelines and product improvement consent screens."""
        GHAPrivacyGuidelinesPage.handle_privacy_guidelines_page_process(self)
        GHAHelpImproveCameraDevicePage.click_yes_i_m_in_btn(self)

    def handle_pairing_until_device_connected(self) -> bool:
        """Commission the Matter device through Apple sheets and GHA setup steps until connected.
        Once commissioning succeeds the device is already in the home, so any failure in the
        post-commissioning OOBE pages restarts GHA and removes the device before failing the test.
        """
        device_name = getattr(self, "device_name", None)
        room_name = getattr(self, "room_name", "Attic")
        GHACommissioningPageObject(self.driver).complete_commissioning_and_pairing_flow(
            device_name=device_name, room_name=room_name
        )
        step = "Video history"
        try:
            GHAChooseWhetherYouWantToTurnOnVideoPage.enable_video_history_and_proceed(self)
            time.sleep(5)
            step = "Adjust your mic settings"
            GHAAdjustYourMicSettingsPage.enable_all_mic_settings_and_proceed(self)
            time.sleep(5)
            step = "Stay in the know"
            GHAStayInTheKnowPage.handle_stay_in_the_know_page_process(self)
            step = "Your camera device is ready"
            GHAYourCameraDeviceIsReadyPage.click_done_btn(self)
            return True
        except OOBEInternalErrorException as e:
            self._logger.error(f"[OOBE Failure] Internal error at '{step}' (OK already clicked): {e}")
            removed = self._emergency_recover_and_remove_device()
            raise AssertionError(
                f"Commissioning OOBE failed at '{step}' due to internal error: {e} "
                f"Emergency device removal: {'SUCCESS' if removed else 'FAILED'}."
            ) from e
        except Exception as e:
            self._logger.error(f"[OOBE Failure] Unexpected error at '{step}': {e}. Removing commissioned device...")
            self._emergency_recover_and_remove_device()
            raise

    def handle_verify_camera_live_stream_and_remove(self):
        session_obj = self if isinstance(self, GHASession) else getattr(self, "session", self)
        session_obj._device_removed_in_emergency = False
        try:
            GHADevicePage.is_device_exist_device_page(self, device_name=self.device_name)
            GHADevicePage.enter_device_page(self, device_name=self.device_name)
            GHACameraLivePage.verify_camera_live_stream(self)
        finally:
            if getattr(session_obj, "_device_removed_in_emergency", False):
                self._logger.info(
                    "[Post-Test Cleanup] Device was already removed & refreshed by emergency teardown; "
                    "proceeding directly to hardware reset."
                )
                session_obj._device_removed_in_emergency = False
            else:
                self.handle_remove_device()
                self.refresh_gha_devices()
            GHASession.reset_target_device(self, reason="post-test cleanup")

    def handle_remove_device(self) -> None:
        """Navigate to Settings and completely remove/unpair the camera device."""
        self._logger.info("Start test case: remove device")
        GHADeviceSettingPage.get_device_information(self)
        GHADeviceSettingPage.click_remove_device_btn(self)