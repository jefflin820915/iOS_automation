"""Page object for handling GHA (Google Home App) bottom tab navigation on iOS."""
import time
from typing import Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from common import constants
from common.base_page import BasePage, PageNotPresentException
from utils import logging_utils


class GHAHomePage(BasePage):
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

    def _find_by_accessibility_id(self, accessibility_id: str) -> Optional[WebElement]:
        """Convenient helper to find an element by ACCESSIBILITY_ID."""
        return self._find_element(AppiumBy.ACCESSIBILITY_ID, accessibility_id)

    def _find_by_class_chain(self, class_chain: str) -> Optional[WebElement]:
        """Convenient helper to find an element by IOS_CLASS_CHAIN."""
        return self._find_element(AppiumBy.IOS_CLASS_CHAIN, class_chain)

    def _get_devices_tab(self) -> Optional[WebElement]:
        """Get the 'Devices' tab WebElement."""
        return self._find_by_class_chain(constants.GHA_DEVICE_TAB_CLASS_CHAIN)

    def _get_favorites_tab(self) -> Optional[WebElement]:
        """Get the 'Favorites' tab WebElement."""
        return self._find_by_class_chain(constants.GHA_FAVORITES_TAB_CLASS_CHAIN)

    def _get_cameras_tab(self) -> Optional[WebElement]:
        """Get the 'Cameras' tab WebElement."""
        return self._find_by_class_chain(constants.GHA_CAMERAS_TAB_CLASS_CHAIN)

    def _get_lights_tab(self) -> Optional[WebElement]:
        """Get the 'Lights' tab WebElement."""
        return self._find_by_class_chain(constants.GHA_LIGHTS_TAB_CLASS_CHAIN)

    def _get_add_devices_btn(self) -> Optional[WebElement]:
        """Get the 'Add Devices' button using ACCESSIBILITY_ID."""
        return self._find_by_accessibility_id(constants.GHA_ADD_DEVICES_BTN_ACCESSIBILITY_ID)

    def _switch_to_tab(self, tab_element: Optional[WebElement], tab_name: str) -> bool:
        """Helper method to check tab selection state and click if not selected."""
        if not tab_element:
            self._logger.error(f"Cannot switch to '{tab_name}' tab: element not found.")
            return False

        try:
            is_selected = tab_element.get_attribute("value") == "1" or tab_element.is_selected()

            if not is_selected:
                self._logger.info(f"Clicking '{tab_name}' tab to switch...")
                tab_element.click()
            else:
                self._logger.info(f"'{tab_name}' tab is already selected.")
            return True
        except WebDriverException as e:
            self._logger.error(f"Failed to switch to '{tab_name}' tab: {e}")
            return False

    def navigate_to_devices_tab(self) -> bool:
        """Ensure the 'Devices' tab is selected in GHA."""
        tab = self._get_devices_tab()
        return self._switch_to_tab(tab, "Devices")

    def navigate_to_favorites_tab(self) -> bool:
        """Ensure the 'Favorites' tab is selected in GHA."""
        tab = self._get_favorites_tab()
        return self._switch_to_tab(tab, "Favorites")

    def navigate_to_cameras_tab(self) -> bool:
        """Ensure the 'Cameras' tab is selected in GHA."""
        tab = self._get_cameras_tab()
        return self._switch_to_tab(tab, "Cameras")

    def navigate_to_lights_tab(self) -> bool:
        """Ensure the 'Lights' tab is selected in GHA."""
        tab = self._get_lights_tab()
        return self._switch_to_tab(tab, "Lights")

    def click_add_devices_button(self) -> bool:
        """Click on the 'Add Devices' (+) button."""
        btn = self._get_add_devices_btn()
        if not btn:
            self._logger.error("Cannot click 'Add Devices' button: element not found.")
            return False
        try:
            self._logger.info("Clicking 'Add Devices' button...")
            btn.click()
            time.sleep(2)
            return True
        except WebDriverException as e:
            self._logger.error(f"Failed to click 'Add Devices' button: {e}")
            return False