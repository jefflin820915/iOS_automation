"""Page object for handling GHA (Google Home App) bottom tab navigation on iOS."""
import time
from typing import Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from common import constants
from common.base_page import BasePage, PageNotPresentException


class GHAChooseWhetherYouWantToTurnOnVideoPage(BasePage):
    """Class for handling GHA bottom navigation tab interactions on iOS."""

    def _find_element(self, by: AppiumBy, locator_value: str) -> Optional[WebElement]:
        """Find an element using specified locator strategy with explicit wait."""
        try:
            return WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((by, locator_value))
            )
        except TimeoutException:
            self._logger.error(f"Timed out waiting for element: by={by}, value='{locator_value}'")
            return None

    def _find_by_class_chain(self, class_chain: str) -> Optional[WebElement]:
        """Convenient helper to find an element by IOS_CLASS_CHAIN."""
        return self._find_element(AppiumBy.IOS_CLASS_CHAIN, class_chain)

    def _find_by_accessibility_id(self, accessibility_id: str) -> Optional[WebElement]:
        """Convenient helper to find an element by ACCESSIBILITY_ID."""
        return self._find_element(AppiumBy.ACCESSIBILITY_ID, accessibility_id)

    def _get_next_btn(self) -> Optional[WebElement]:
        """Get the 'Add Devices' button using ACCESSIBILITY_ID."""
        return self._find_element(AppiumBy.ACCESSIBILITY_ID, constants.GHA_NEXT_BTN_ACCESSIBILITY_ID)

    def _get_video_history_toggle(self) -> Optional[WebElement]:
        """Get the 'Video history' switch element (XCUIElementTypeSwitch)."""
        return self._find_by_accessibility_id(constants.GHA_TOGGLE_ACCESSIBILITY_ID)

    def _get_video_history_title(self) -> Optional[WebElement]:
        """Get the 'Video history' title element (XCUIElementTypeSwitch)."""
        return self._find_by_accessibility_id(constants.GHA_VIDEO_HISTORY_ACCESSIBILITY_ID)

    # ==================== Page Actions ====================
    def is_video_history_enabled(self) -> bool:
        """Check if the video history toggle is currently turned ON (value == '1').
        Returns:
            bool: True if turned ON, False otherwise.
        """
        toggle = self._get_video_history_toggle()
        if not toggle:
            self._logger.warning("Video history toggle not found on screen.")
            return False
        value = str(toggle.get_attribute("value") or "0")
        is_on = value in ("1", "true")
        self._logger.info(f"Current Video History Toggle state: {'ON' if is_on else 'OFF'} (value={value})")
        return is_on

    def _turn_on_video_history_toggle(self) -> bool:
        """Ensure the video history toggle is turned ON."""
        self._logger.info("Executing flow: Turn ON Video History and proceed with Next...")
        toggle = self._get_video_history_toggle()
        title = self._get_video_history_title()
        if not title:
            self._logger.error("Cannot turn on Video History: Toggle element not found.")
            return False
        try:
            if not self.is_video_history_enabled():
                self._logger.info("Video History toggle is OFF. Clicking to turn ON...")
                toggle.click()
                time.sleep(1.0)
                if self.is_video_history_enabled():
                    self._logger.info("Successfully turned ON Video History toggle.")
                    return True
                else:
                    self._logger.warning("Toggle click did not change state to ON. Retrying tap...")
                    self.driver.execute_script("mobile: tap", {"elementId": toggle.id})
                    time.sleep(1.0)
                    return self.is_video_history_enabled()
            else:
                self._logger.info("Video History toggle is already ON.")
                return True
        except WebDriverException as e:
            self._logger.error(f"Failed to interact with Video History toggle: {e}")
            return False

    def _click_next_btn(self) -> bool:
        """Click the 'Next' button to proceed to the next setup step.
        Returns:
            bool: True if clicked successfully, False otherwise.
        """
        btn = self._get_next_btn()
        if not btn:
            self._logger.error("Cannot click 'Next': Button element not found.")
            return False
        try:
            self._logger.info("Clicking 'Next' button...")
            btn.click()
            time.sleep(5.0)
            return True
        except WebDriverException as e:
            self._logger.warning(f"Direct click failed: {e}. Trying tap fallback...")
            try:
                self.driver.execute_script("mobile: tap", {"elementId": btn.id})
                time.sleep(5.0)
                return True
            except Exception as tap_err:
                self._logger.error(f"Failed to click 'Next' button: {tap_err}")
                return False

    def enable_video_history_and_proceed(self) -> bool:
        """Convenient method to turn on the video history toggle and click Next.
        Returns:
            bool: True if both actions succeeded, False otherwise.
        """
        turned_on = self._turn_on_video_history_toggle()
        clicked_next = self._click_next_btn()
        return turned_on and clicked_next