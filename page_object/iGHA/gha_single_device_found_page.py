"""Page object for handling GHA Single Device Found page on iOS."""
import time
from typing import Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException, StaleElementReferenceException
from common.base_page import BasePage
from utils import logging_utils


logger = logging_utils.get_logger(__name__, "single_device_found_page")


class GHASingleDeviceFoundPage(BasePage):
    """Class for handling Single Device Found screen during GHA setup."""
    NAV_BAR = (
        AppiumBy.IOS_CLASS_CHAIN,
        '**/XCUIElementTypeNavigationBar[`name CONTAINS "SingleDeviceFoundView"`]'
    )
    HEADER_TITLE = (
        AppiumBy.ACCESSIBILITY_ID,
        "Header_title"
    )
    HEADER_SUBTITLE = (
        AppiumBy.IOS_CLASS_CHAIN,
        '**/XCUIElementTypeStaticText[`name == "Header_subtitle" AND label CONTAINS "detected nearby"`]'
    )
    NEXT_BTN_LOCATORS = [
        (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "Footer_actionBar" AND label == "Next"`]'),
        (AppiumBy.ACCESSIBILITY_ID, "Next"),
        (AppiumBy.XPATH, '//XCUIElementTypeButton[@label="Next"]'),
    ]
    DIFFERENT_DEVICE_BTN = (
        AppiumBy.ACCESSIBILITY_ID,
        "Set up a different device"
    )

    def is_page_present(self, timeout: float = 3.0) -> bool:
        """Check if the Single Device Found page is currently displayed."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                title_elem = self._get_title_element()
                if title_elem and title_elem.is_displayed():
                    return True
                navs = self.driver.find_elements(*self.NAV_BAR)
                if navs and navs[0].is_displayed():
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def _get_title_element(self) -> Optional[WebElement]:
        """Safely find the Header_title element."""
        try:
            elems = self.driver.find_elements(*self.HEADER_TITLE)
            for elem in elems:
                if elem.is_displayed():
                    return elem
        except Exception:
            pass
        return None

    def get_detected_device_title(self) -> str:
        """Extract the text from Header_title (e.g. 'Set up Ref2 Battery Camera')."""
        elem = self._get_title_element()
        if elem:
            return (elem.get_attribute("value") or elem.get_attribute("label") or elem.text or "").strip()
        return ""

    def is_target_device(self, target_device_name: str) -> bool:
        """Check if the detected device title contains the expected device name."""
        detected_title = self.get_detected_device_title()
        self._logger.info(f"Single device found title: '{detected_title}', Expected: '{target_device_name}'")
        if not target_device_name:
            return True
        return target_device_name.lower() in detected_title.lower()

    def click_next_button(self) -> bool:
        """Click the 'Next' button to proceed with setting up the detected device."""
        self._logger.info("Clicking 'Next' button on Single Device Found page...")
        for by, val in self.NEXT_BTN_LOCATORS:
            try:
                elems = self.driver.find_elements(by, val)
                for btn in elems:
                    if btn.is_displayed():
                        try:
                            btn.click()
                            time.sleep(2.0)
                            self._logger.info("Successfully clicked 'Next'.")
                            return True
                        except (WebDriverException, StaleElementReferenceException):
                            rect = btn.rect
                            tap_x = int(rect["x"] + rect["width"] / 2)
                            tap_y = int(rect["y"] + rect["height"] / 2)
                            self.driver.execute_script("mobile: tap", {"x": tap_x, "y": tap_y})
                            time.sleep(2.0)
                            self._logger.info(f"Coordinate-tapped 'Next' at ({tap_x}, {tap_y}).")
                            return True
            except Exception:
                continue
        self._logger.error("Failed to click 'Next' button on Single Device Found page.")
        return False

    @classmethod
    def handle_if_present(cls, session_or_page, target_device_name: str, timeout: float = 3.5) -> bool:
        """Class method helper that works directly with GHASession instance."""
        driver = getattr(session_or_page, "driver", session_or_page)
        page = cls(driver)
        return page.handle_target_device_flow(target_device_name, timeout=timeout)

    def handle_target_device_flow(self, target_device_name: str, timeout: float = 3.5) -> bool:
        if not self.is_page_present(timeout=timeout):
            return False
        detected_title = self.get_detected_device_title()
        self._logger.info(f"Single Device Found page appeared! Detected: '{detected_title}'")
        if self.is_target_device(target_device_name):
            self._logger.info(f"Title matched target device '{target_device_name}'. Proceeding with Next...")
            return self.click_next_button()
        else:
            self._logger.warning(
                f"Detected device '{detected_title}' did NOT match target '{target_device_name}'!"
            )
            return False