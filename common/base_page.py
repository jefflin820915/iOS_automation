"""Base Page Object providing core verification, page source dumping, and wait helpers for iOS Appium."""
from datetime import datetime
import os
import time
from typing import Optional, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from common import constants
from utils import logging_utils


class PageNotPresentException(Exception):
    """Exception raised when an expected page or component is not present on screen."""

    def __init__(self, locator: Tuple[AppiumBy, str], page_name: str,
                 message: Optional[str] = None) -> None:
        self.locator = locator
        self.page_name = page_name
        default_msg = f"Expected component {locator} on page '{page_name}' is not present or visible on screen."
        super().__init__(message or default_msg)


class BasePage:
    """Base class for all iOS Appium Page Objects."""
    PAGE_HEADLINE: Optional[str] = None
    PAGE_LOCATOR: Optional[Tuple[AppiumBy, str]] = None
    INIT_CHECK_THROTTLE_SECONDS: float = 5.0

    def __init__(self, driver: WebDriver, timeout: float = 10.0) -> None:
        """Initialize BasePage with iOS Appium WebDriver instance.
        Args:
            driver (WebDriver): The active iOS Appium WebDriver instance.
            timeout (float): Default explicit wait timeout in seconds.
        """
        self.driver = driver
        self.timeout = timeout
        self._logger = logging_utils.get_logger(__name__, "page_object")
        self._log_page_entry()
        self.ensure_device_unlocked_and_ready(force=False)

    def _log_page_entry(self) -> None:
        """Log page entry banner when page object is instantiated or verified."""
        page_name = self.__class__.__name__
        self._logger.info(f"<<< {page_name} >>>")

    @staticmethod
    def reset_failure_screenshot_state(
            driver: Optional[WebDriver], target_path: Optional[str] = None,
            remove_existing: bool = True
    ) -> None:
        """Reset per-test failure screenshot tracking on the WebDriver instance.
        Args:
            driver: Active Appium WebDriver instance.
            target_path: Optional destination file path for the current test's failure screenshot.
                If None, preserves any existing `_failure_screenshot_target` on `driver`.
            remove_existing: If True, removes any tentative screenshot file captured during an
                earlier recovered retry attempt.
        """
        if driver is None:
            return
        try:
            prev_captured = getattr(driver, "_failure_screenshot_captured", None)
            if remove_existing and prev_captured and os.path.isfile(prev_captured):
                try:
                    os.remove(prev_captured)
                except OSError:
                    pass
            if target_path is not None:
                setattr(driver, "_failure_screenshot_target", target_path)
            setattr(driver, "_failure_screenshot_captured", None)
            setattr(driver, "_failure_screenshot_locked", False)
        except Exception:
            pass

    @classmethod
    def capture_failure_screenshot(
            cls,
            driver: Optional[WebDriver],
            reason: str = "",
            force: bool = False,
            lock: bool = True,
    ) -> Optional[str]:
        """Capture a screenshot immediately at the moment of failure, before recovery/cleanup alters the UI.
        Once a screenshot is captured with `lock=True` (the default for terminal failure handlers),
        subsequent calls during recovery/teardown or in `test_runner.py` will not overwrite it.
        Args:
            driver: Active Appium WebDriver instance.
            reason: Short description of the failure moment for logging.
            force: If True (and not locked), overwrite an earlier tentative screenshot (e.g. from a probe).
            lock: If True, lock the captured screenshot so later cleanup/unwinding cannot overwrite it.
        Returns:
            The saved screenshot file path if captured (or already captured), or None on failure.
        """
        if driver is None or not hasattr(driver, "save_screenshot"):
            return None
        logger = logging_utils.get_logger(__name__, "page_object")
        try:
            already_captured = getattr(driver, "_failure_screenshot_captured", None)
            is_locked = bool(getattr(driver, "_failure_screenshot_locked", False))
            if already_captured and os.path.isfile(already_captured):
                if is_locked or not force:
                    if lock and not is_locked:
                        try:
                            setattr(driver, "_failure_screenshot_locked", True)
                        except Exception:
                            pass
                    return already_captured
            target_path = getattr(driver, "_failure_screenshot_target", None)
            if not target_path:
                add_dir = getattr(logging_utils, "_current_additional_log_dir", None) or getattr(
                    constants, "SESSION_LOG_DIR", "."
                )
                os.makedirs(add_dir, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                target_path = os.path.join(add_dir, f"FAILED_{ts}.png")
                try:
                    setattr(driver, "_failure_screenshot_target", target_path)
                except Exception:
                    pass
            else:
                parent_dir = os.path.dirname(target_path)
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)
            driver.save_screenshot(target_path)
            try:
                setattr(driver, "_failure_screenshot_captured", target_path)
                if lock:
                    setattr(driver, "_failure_screenshot_locked", True)
            except Exception:
                pass
            context_str = f" ({reason})" if reason else ""
            logger.info(
                f"[Screenshot] Captured immediate failure screenshot{context_str}: {target_path}")
            return target_path
        except Exception as shot_err:
            logger.warning(
                f"[Screenshot] Failed to capture immediate failure screenshot ({reason}): {shot_err}")
            return None

    def ensure_device_unlocked_and_ready(self, force: bool = True) -> bool:
        """Ensure the iOS device screen is unlocked first, then resume GHA if suspended.
        Args:
            force (bool): If True (default for per-run checks), always query lock & app state.
                If False (used during bulk PageObject __init__), skip if checked within
                INIT_CHECK_THROTTLE_SECONDS on the same driver instance.
        Returns:
            bool: True if the device screen is unlocked after the check, False otherwise.
        """
        now = time.time()
        if not force and self.driver is not None:
            last_check = getattr(self.driver, "_last_unlock_ready_check_ts", 0.0)
            if (now - last_check) < self.INIT_CHECK_THROTTLE_SECONDS:
                return True
            try:
                setattr(self.driver, "_last_unlock_ready_check_ts", now)
            except Exception:
                pass
        elif self.driver is not None:
            try:
                setattr(self.driver, "_last_unlock_ready_check_ts", now)
            except Exception:
                pass
        unlocked = self._unlock_device_if_locked()
        self._resume_if_suspended()
        return unlocked

    def get_window_hierarchy(self) -> str:
        """Dump the full XML UI accessibility hierarchy of the active iOS screen.
        Returns:
            str: XML string of current page source (equivalent to Android dumpWindowHierarchy).
        """
        try:
            return self.driver.page_source
        except WebDriverException as e:
            self._logger.error(f"Failed to dump iOS window hierarchy: {e}")
            return ""

    def check_component_exist(
            self,
            by: AppiumBy,
            value: str,
            timeout: Optional[float] = None
    ) -> WebElement:
        """Check if the specified component is loaded and visible within timeout.
        Args:
            by (AppiumBy): Appium locator strategy (e.g. AppiumBy.ACCESSIBILITY_ID).
            value (str): Locator selector string.
            timeout (float, optional): Maximum wait time in seconds. Defaults to self.timeout.
        Returns:
            WebElement: The located WebElement.
        Raises:
            PageNotPresentException: If element is not found within timeout.
        """
        wait_time = timeout if timeout is not None else self.timeout
        try:
            elem = WebDriverWait(self.driver, wait_time).until(
                EC.presence_of_element_located((by, value))
            )
            return elem
        except TimeoutException:
            self._logger.warning(
                f"Expected component {by}={value} in '{self.__class__.__name__}' is not present.")
            BasePage.capture_failure_screenshot(
                self.driver,
                reason=f"{self.__class__.__name__} missing {by}={value}",
                force=True,
                lock=False,
            )
            raise PageNotPresentException(locator=(by, value), page_name=self.__class__.__name__)

    def is_current_page(self) -> str:
        """Verify if current active screen matches this Page Object."""
        page_text = self.driver.find_element(
            by=AppiumBy.ACCESSIBILITY_ID,
            value=constants.GHA_CONNECTING_TITLE_ACCESSIBILITY_ID,
        ).text
        time.sleep(1)
        self._logger.info(f"Checking current '{page_text}'")
        return page_text

    def _unlock_device_if_locked(self) -> bool:
        """Check if iOS device screen is locked, swipe up to show keypad, and enter passcode."""
        code = getattr(constants, "IOS_DEVICE_PASSCODE", "")
        default_wait = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
        try:
            if not self.driver.is_locked():
                return True
            self._logger.warning(
                f"iOS device screen is LOCKED. Auto-unlocking (passcode configured: {bool(code)})...")
            try:
                self.driver.execute_script("mobile: pressButton", {"name": "home"})
                time.sleep(0.5)
            except Exception:
                pass
            window = self.driver.get_window_size()
            w, h = window.get("width", 375), window.get("height", 812)
            self.driver.execute_script("mobile: dragFromToForDuration", {
                "duration": 0.3,
                "fromX": int(w * 0.5),
                "fromY": int(h * 0.98),
                "toX": int(w * 0.5),
                "toY": int(h * 0.3)
            })
            time.sleep(0.8)
            if code:
                self._logger.info("Entering passcode digits on iOS lock keypad...")
                try:
                    self.driver.execute_script("mobile: unlock", {"key": str(code)})
                    time.sleep(1.0)
                except Exception:
                    pass
                if self.driver.is_locked():
                    try:
                        self.driver.implicitly_wait(0)
                        for digit in str(code):
                            try:
                                btn = self.driver.find_elements(
                                    AppiumBy.IOS_PREDICATE,
                                    f'name == "{digit}" OR label == "{digit}"'
                                )
                                if btn and btn[0].is_displayed():
                                    btn[0].click()
                                else:
                                    btn_id = self.driver.find_elements(AppiumBy.ACCESSIBILITY_ID,
                                                                       digit)
                                    if btn_id and btn_id[0].is_displayed():
                                        btn_id[0].click()
                            except Exception as click_err:
                                self._logger.debug(f"Digit '{digit}' click error: {click_err}")
                    finally:
                        try:
                            self.driver.implicitly_wait(default_wait)
                        except Exception:
                            pass
                    time.sleep(1.0)
            else:
                try:
                    self.driver.unlock()
                except Exception:
                    pass
            is_unlocked = not self.driver.is_locked()
            self._logger.info(
                f"Screen unlock status: {'SUCCESS (Unlocked)' if is_unlocked else 'STILL_LOCKED'}")
            return is_unlocked
        except Exception as e:
            self._logger.error(f"Failed to auto-unlock device: {e}")
            return False

    def _resume_if_suspended(self) -> None:
        """Auto-heal: If GHA is suspended/backgrounded, pull it back to foreground."""
        bundle_id = getattr(constants, "GHA_BUNDLE_ID", "com.google.Chromecast.enterprise")
        try:
            if self.driver.query_app_state(bundle_id) != 4:
                self._logger.warning(
                    f"Detected App suspended in background. Auto-resuming '{bundle_id}'...")
                self.driver.activate_app(bundle_id)
                time.sleep(1.0)
        except Exception:
            pass
