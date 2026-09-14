"""Base Page Object providing core verification, page source dumping, and wait helpers for iOS Appium."""

import time
from lib2to3.pgen2 import driver
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

    def __init__(self, locator: Tuple[AppiumBy, str], page_name: str, message: Optional[str] = None) -> None:
        self.locator = locator
        self.page_name = page_name
        default_msg = f"Expected component {locator} on page '{page_name}' is not present or visible on screen."
        super().__init__(message or default_msg)


class BasePage:
    """Base class for all iOS Appium Page Objects."""

    PAGE_HEADLINE: Optional[str] = None
    PAGE_LOCATOR: Optional[Tuple[AppiumBy, str]] = None

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
        self._resume_if_suspended()
        self._unlock_device_if_locked()

    def _log_page_entry(self) -> None:
        """Log page entry banner when page object is instantiated or verified."""
        page_name = self.__class__.__name__
        self._logger.info(f"<<< {page_name} >>>")

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
            self._logger.warning(f"Expected component {by}={value} in '{self.__class__.__name__}' is not present.")
            raise PageNotPresentException(locator=(by, value), page_name=self.__class__.__name__)

    def is_current_page(self) -> str:
        """Verify if current active screen matches this Page Object."""
        page_text = self.driver.find_element(by=AppiumBy.ACCESSIBILITY_ID, value=constants.GHA_CONNECTING_TITLE_ACCESSIBILITY_ID).text
        time.sleep(1)
        self._logger.info(f"Checking current '{page_text}'")
        return page_text

    def _unlock_device_if_locked(self) -> bool:
        """Check if iOS device screen is locked, swipe up to show keypad, and enter passcode."""
        code = constants.IOS_DEVICE_PASSCODE
        try:
            if not self.driver.is_locked():
                return True
            self._logger.warning(f"iOS device screen is LOCKED. Auto-unlocking (passcode configured: {bool(code)})...")
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
                    for digit in str(code):
                        try:
                            btn = self.driver.find_elements(
                                AppiumBy.IOS_PREDICATE,
                                f'name == "{digit}" OR label == "{digit}"'
                            )
                            if btn and btn[0].is_displayed():
                                btn[0].click()
                            else:
                                btn_id = self.driver.find_elements(AppiumBy.ACCESSIBILITY_ID, digit)
                                if btn_id and btn_id[0].is_displayed():
                                    btn_id[0].click()
                        except Exception as click_err:
                            self._logger.debug(f"Digit '{digit}' click error: {click_err}")
                    time.sleep(1.0)
            else:
                try:
                    self.driver.unlock()
                except Exception:
                    pass
            is_unlocked = not self.driver.is_locked()
            self._logger.info(f"Screen unlock status: {'SUCCESS (Unlocked)' if is_unlocked else 'STILL_LOCKED'}")
            return is_unlocked
        except Exception as e:
            self._logger.error(f"Failed to auto-unlock device: {e}")
            return False

    def _resume_if_suspended(self) -> None:
        """Auto-heal: If GHA is suspended/backgrounded, pull it back to foreground."""
        bundle_id = getattr(constants, "GHA_BUNDLE_ID", "com.google.Chromecast.enterprise")
        try:
            if self.driver.query_app_state(bundle_id) != 4:
                self._logger.warning(f"Detected App suspended in background. Auto-resuming '{bundle_id}'...")
                self.driver.activate_app(bundle_id)
                time.sleep(1.0)
        except Exception:
            pass