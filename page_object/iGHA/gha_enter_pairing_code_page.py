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


class GHAEnterPairingCodePage(BasePage):
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

    def _continue_btn(self):
        continue_btn = self.driver.find_element(by=AppiumBy.XPATH, value=constants.GHA_CONTINUE_BTN_XPATH)
        return continue_btn

    def enter_pairing_code(self, pairing_code):
        pairing_code_field = self._find_element(AppiumBy.CLASS_NAME, constants.GHA_TEXT_EDIT_VIEW_CLASS_NAME)
        pairing_code_field.send_keys(pairing_code)
        self._continue_btn().click()





