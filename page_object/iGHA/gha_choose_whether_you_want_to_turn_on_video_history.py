"""Page object for handling GHA Choose Whether You Want To Turn On Video History page on iOS."""
import time
from typing import Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from common import constants
from common.base_page import BasePage, PageNotPresentException


class OOBEInternalErrorException(Exception):
    """Raised when GHA displays 'Internal error encountered.' modal during post-commissioning OOBE."""
    pass


class GHAChooseWhetherYouWantToTurnOnVideoPage(BasePage):
    """Class for handling GHA Video History toggle and setup on iOS."""
    # Locators for internal error dialog
    INTERNAL_ERROR_PREDICATE = 'label == "Internal error encountered." OR name == "Internal error encountered."'
    ALERT_OK_PREDICATE = 'label == "OK" OR name == "OK"'

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
        """Get the 'Next' button using ACCESSIBILITY_ID or predicate fallback."""
        btn = self._find_element(AppiumBy.ACCESSIBILITY_ID, constants.GHA_NEXT_BTN_ACCESSIBILITY_ID)
        if not btn:
            btn = self._find_element(AppiumBy.IOS_PREDICATE, 'label == "Next" OR name == "actionBarPrimaryButton"')
        return btn

    def _get_video_history_toggle(self) -> Optional[WebElement]:
        """Get the 'Video history' switch element (XCUIElementTypeSwitch)."""
        return self._find_by_accessibility_id(constants.GHA_TOGGLE_ACCESSIBILITY_ID)

    def _get_video_history_title(self) -> Optional[WebElement]:
        """Get the 'Video history' title element."""
        return self._find_by_accessibility_id(constants.GHA_VIDEO_HISTORY_ACCESSIBILITY_ID)

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
        if not title or not toggle:
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

    def _check_for_internal_error(self, timeout: float = 4.0):
        """Check if 'Internal error encountered.' alert pops up and dismiss it."""
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((AppiumBy.IOS_PREDICATE, self.INTERNAL_ERROR_PREDICATE))
            )
            self._logger.warning("[VideoHistory] Detected 'Internal error encountered.' alert dialog!")
            # Dismiss alert by clicking OK
            try:
                ok_btn = WebDriverWait(self.driver, 2.0).until(
                    EC.element_to_be_clickable((AppiumBy.IOS_PREDICATE, self.ALERT_OK_PREDICATE))
                )
                ok_btn.click()
                self._logger.info("[VideoHistory] Clicked 'OK' on internal error alert.")
            except Exception as dismiss_err:
                self._logger.warning(f"[VideoHistory] Failed to click OK on alert: {dismiss_err}")
            raise OOBEInternalErrorException("GHA displayed 'Internal error encountered.' during Video History setup.")
        except TimeoutException:
            # Normal: no error alert appeared
            pass

    def _click_next_btn(self) -> bool:
        """Click the 'Next' button to proceed to the next setup step.
        Returns:
            bool: True if clicked successfully, False otherwise.
        Raises:
            OOBEInternalErrorException: If internal error dialog appears.
        """
        btn = self._get_next_btn()
        if not btn:
            self._logger.error("Cannot click 'Next': Button element not found.")
            return False
        try:
            self._logger.info("Clicking 'Next' button...")
            btn.click()
        except WebDriverException as e:
            self._logger.warning(f"Direct click failed: {e}. Trying tap fallback...")
            try:
                self.driver.execute_script("mobile: tap", {"elementId": btn.id})
            except Exception as tap_err:
                self._logger.error(f"Failed to click 'Next' button: {tap_err}")
                return False
        self._check_for_internal_error(timeout=4.0)
        return True

    def enable_video_history_and_proceed(self) -> bool:
        """Convenient method to turn on the video history toggle and click Next.
        Returns:
            bool: True if both actions succeeded, False otherwise.
        """
        turned_on = self._turn_on_video_history_toggle()
        clicked_next = self._click_next_btn()
        return turned_on and clicked_next