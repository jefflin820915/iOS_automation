"""Page object for handling GHA Single Device Found page on iOS."""
import time
from typing import Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException, StaleElementReferenceException
from common.base_page import BasePage
from utils import logging_utils
from page_object.iGHA import gha_session
from page_object.iGHA.gha_add_page import GHAAddPage


class GHASingleDeviceFoundPage(BasePage):
    """Class for handling Single Device Found screen during GHA setup."""
    NEXT_BTN_LOCATORS = [
        (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "Footer_actionBar" AND label == "Next"`]'),
        (AppiumBy.XPATH, '//XCUIElementTypeButton[@name="Footer_actionBar" and @label="Next"]'),
        (AppiumBy.ACCESSIBILITY_ID, "Next"),
    ]
    DIFFERENT_DEVICE_BTN_LOCATORS = [
        (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "Footer_actionBar" AND label == "Set up a different device"`]'),
        (AppiumBy.ACCESSIBILITY_ID, "Set up a different device"),
        (AppiumBy.XPATH, '//XCUIElementTypeButton[@label="Set up a different device"]'),
    ]
    HEADER_TITLE = (AppiumBy.ACCESSIBILITY_ID, "Header_title")
    HEADER_SUBTITLE = (AppiumBy.ACCESSIBILITY_ID, "Header_subtitle")
    NAV_BAR = (
        AppiumBy.IOS_CLASS_CHAIN,
        '**/XCUIElementTypeNavigationBar[`name CONTAINS "SingleDeviceFoundView"`]'
    )

    def _get_element_safe(self, by: AppiumBy, value: str) -> Optional[WebElement]:
        """Safely find a visible element."""
        try:
            elems = self.driver.find_elements(by, value)
            for elem in elems:
                if elem.is_displayed():
                    return elem
        except Exception:
            pass
        return None

    def is_single_device_found_page(self, timeout: float = 2.0) -> bool:
        """Strictly determine if the current screen is 'Single Device Found' page.

        Rule:
        - Must directly have a visible 'Next' button.
        - Must have Single-page unique markers ('Set up a different device' / SingleDeviceFoundView nav / nearby subtitle).
        - If it is a multi-device list, this will safely return False.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                next_btn = self._get_next_button()
                if not next_btn:
                    time.sleep(0.3)
                    continue
                diff_btn = self._get_different_device_button()
                has_single_navbar = bool(self._get_element_safe(*self.NAV_BAR))
                has_nearby_subtitle = False
                if sub_elem := self._get_element_safe(*self.HEADER_SUBTITLE):
                    sub_text = sub_elem.get_attribute("label") or sub_elem.text or ""
                    has_nearby_subtitle = "detected nearby" in sub_text
                if diff_btn or has_single_navbar or has_nearby_subtitle:
                    self._logger.info("Confirmed current screen is 'Single Device Found' page (Next button verified).")
                    return True
            except Exception:
                pass
            time.sleep(0.3)
        return False

    def _get_next_button(self) -> Optional[WebElement]:
        """Find the visible 'Next' button."""
        for by, val in self.NEXT_BTN_LOCATORS:
            elem = self._get_element_safe(by, val)
            if elem:
                return elem
        return None

    def _get_different_device_button(self) -> Optional[WebElement]:
        """Find the 'Set up a different device' button."""
        for by, val in self.DIFFERENT_DEVICE_BTN_LOCATORS:
            elem = self._get_element_safe(by, val)
            if elem:
                return elem
        return None

    def get_detected_device_title(self) -> str:
        """Extract device name from Header_title (e.g. 'Set up Ref2 Battery Camera')."""
        elem = self._get_element_safe(*self.HEADER_TITLE)
        if elem:
            return (elem.get_attribute("value") or elem.get_attribute("label") or elem.text or "").strip()
        return ""

    def is_title_match_device(self, target_device_name: str) -> bool:
        """Verify whether the title contains the target device name."""
        detected_title = self.get_detected_device_title()
        self._logger.info(f"Single device title: '{detected_title}', Expected: '{target_device_name}'")
        if not target_device_name:
            return True
        return target_device_name.lower() in detected_title.lower()

    def click_next_button(self) -> bool:
        """Click the 'Next' button."""
        next_btn = self._get_next_button()
        if not next_btn:
            self._logger.error("Next button not found when attempting to click.")
            return False
        try:
            next_btn.click()
            time.sleep(2.5)
            self._logger.info("Successfully clicked 'Next' on Single Device Found page.")
            return True
        except (WebDriverException, StaleElementReferenceException) as err:
            self._logger.warning(f"Normal click failed ({err}), trying coordinate tap...")
            try:
                rect = next_btn.rect
                tap_x = int(rect["x"] + rect["width"] / 2)
                tap_y = int(rect["y"] + rect["height"] / 2)
                self.driver.execute_script("mobile: tap", {"x": tap_x, "y": tap_y})
                time.sleep(2.5)
                self._logger.info(f"Successfully coordinate-tapped 'Next' at ({tap_x}, {tap_y}).")
                return True
            except Exception as tap_err:
                self._logger.error(f"Coordinate tap also failed: {tap_err}")
                return False

    def click_back_btn(self) -> bool:
        """Click the top-left back/close button to exit the Camera Live stream page."""
        self._logger.info("Exiting Camera Live screen: looking for back/close button...")
        back_locators = [
            (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "closeButton"`]'),
            (AppiumBy.ACCESSIBILITY_ID, "closeButton"),
            (AppiumBy.ACCESSIBILITY_ID, "close"),
            (AppiumBy.ACCESSIBILITY_ID, "Close"),
            (AppiumBy.ACCESSIBILITY_ID, "Back"),
            (AppiumBy.ACCESSIBILITY_ID, "back"),
            (AppiumBy.IOS_PREDICATE, 'label == "Back" OR name == "Back" OR label == "Close" OR name == "close"'),
        ]
        try:
            self.driver.execute_script("mobile: tap", {"x": 50, "y": 100})
            time.sleep(0.5)
            elems = self.driver.find_element(AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "closeButton"`]')
            elems.click()
            self._logger.info("Successfully clicked back button.")
            return True
        except Exception:
            pass
        self._logger.info("Navigation bar may be hidden. Tapping screen to reveal controls...")
        try:
            self.driver.execute_script("mobile: tap", {"x": 200, "y": 300})
            time.sleep(1.0)
            for by, val in back_locators:
                elems = self.driver.find_elements(by, val)
                if elems and elems[0].is_displayed():
                    elems[0].click()
                    time.sleep(1.5)
                    self._logger.info("Successfully clicked back button after revealing controls.")
                    return True
        except Exception as e:
            self._logger.warning(f"Error tapping screen to reveal controls: {e}")
        self._logger.warning("Fallback: Tapping top-left corner coordinates to exit live view...")
        try:
            self.driver.execute_script("mobile: tap", {"x": 25, "y": 55})
            time.sleep(1.5)
            return True
        except Exception as e:
            self._logger.error(f"Failed to click back: {e}")
            return False

    def click_different_device_button(self) -> bool:
        """Click 'Set up a different device' if detected device is not what we want."""
        diff_btn = self._get_different_device_button()
        if diff_btn:
            diff_btn.click()
            time.sleep(2.0)
            self._logger.info("Clicked 'Set up a different device' to return to device list.")
            return True
        return False

    @classmethod
    def handle_if_present(cls, session_or_page, target_device_name: str, timeout: float = 2.5) -> bool:
        """Check for Single Device Found screen:
        1. If it directly has Next button + Single features -> Confirm it is Single.
        2. Check title:
           - Matches target_device_name -> Click 'Next'.
           - Doesn't match -> Click 'Set up a different device' to switch to list.
        3. If it is Multiple devices (list screen) -> Returns False, let normal list flow handle it.
        """
        driver = getattr(session_or_page, "driver", session_or_page)
        page = cls(driver)
        if not page.is_single_device_found_page(timeout=timeout):
            page._logger.info("Not a Single Device screen (likely multi-device list or normal flow). Proceeding...")
            return False
        detected_title = page.get_detected_device_title()
        if page.is_title_match_device(target_device_name):
            page._logger.info(f"Single device title '{detected_title}' matches '{target_device_name}'. Clicking Next...")
            return page.click_next_button()
        else:
            page._logger.warning(
                f"Single device title '{detected_title}' does NOT match '{target_device_name}'. "
                f"Clicking 'Set up a different device'..."
            )
            page.click_different_device_button()
            page.click_back_btn()
            gha_session.GHAHomePage(driver).click_add_devices_button()
            GHAAddPage(driver).navigate_to_setup_device_page()
            return False