"""Page object for handling GHA (Google Home App) bottom tab navigation on iOS."""
import time
from typing import Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from common.base_page import BasePage, PageNotPresentException
from common import constants
from utils import logging_utils


class GHAStayInTheKnowPage(BasePage):
    """Class for handling GHA bottom navigation tab interactions on iOS."""

    PAGE_HEADLINE = "Stay in the know"

    def _find_element(self, by: AppiumBy, locator_value: str) -> Optional[WebElement]:
        """Find an element using specified locator strategy with explicit wait."""
        try:
            return WebDriverWait(self.driver, 120).until(
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

    def _get_no_thanks_btn(self) -> Optional[WebElement]:
        """Get the 'Add Devices' button using ACCESSIBILITY_ID."""
        return self._find_by_accessibility_id(constants.GHA_NO_THANKS_BTN_ACCESSIBILITY_ID)

    def _click_no_thanks_btn(self) -> bool:
        """Wait for live video page to appear and click the 'Next' button.
        Args:
            wait_page_timeout (float): Time to wait for live video page. Defaults to 120.0s.
        Returns:
            bool: True if clicked successfully, False otherwise.
        """
        btn = self._get_no_thanks_btn()
        if not btn:
            self._logger.error("Cannot click 'No thanks': Button was not found or page did not load.")
            return False
        try:
            self._logger.info("Clicking 'No thanks' button...")
            btn.click()
            time.sleep(2.0)
            return True
        except WebDriverException as e:
            self._logger.warning(f"Direct click failed: {e}. Trying tap fallback...")
            try:
                self.driver.execute_script("mobile: tap", {"elementId": btn.id})
                time.sleep(2.0)
                return True
            except Exception as tap_err:
                self._logger.error(f"Tap fallback also failed: {tap_err}")
                return False

    def handle_stay_in_the_know_page_process(self):
        return self._click_no_thanks_btn()
