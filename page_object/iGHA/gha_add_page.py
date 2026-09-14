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
from utils import logging_utils


class GHAAddPage:
    """Class for handling GHA bottom navigation tab interactions on iOS."""

    def __init__(self, driver: WebDriver, timeout: float = 10.0) -> None:
        """Initialize GHAHomeTabObject with iOS Appium driver.

        Args:
            driver (WebDriver): The iOS Appium driver instance.
            timeout (float): Default timeout in seconds for finding elements.
        """
        self.driver = driver
        self.timeout = timeout
        self._logger = logging_utils.get_logger(__name__, "object")

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

    def _get_device_btn(self) -> Optional[WebElement]:
        """Get the 'Add Devices' button using ACCESSIBILITY_ID."""
        return self._find_by_accessibility_id(constants.GHA_ADD_PAGE_DEVICE_BTN_ACCESSIBILITY_ID)

    def _get_add_device_with_photo_btn(self) -> Optional[WebElement]:
        """Get the 'Add Devices' button using ACCESSIBILITY_ID."""
        return self._find_by_accessibility_id(constants.GHA_ADD_DEVICE_WITH_PHOTO_BTN_ACCESSIBILITY_ID)

    def _get_speaker_group_btn(self) -> Optional[WebElement]:
        """Get the 'Add Devices' button using ACCESSIBILITY_ID."""
        return self._find_by_accessibility_id(constants.GHA_SPEAKER_GROUP_BTN_ACCESSIBILITY_ID)

    def _get_automation_btn(self) -> Optional[WebElement]:
        """Get the 'Add Devices' button using ACCESSIBILITY_ID."""
        return self._find_by_accessibility_id(constants.GHA_AUTOMATION_BTN_ACCESSIBILITY_ID)

    def _get_link_app_service_btn(self) -> Optional[WebElement]:
        """Get the 'Add Devices' button using ACCESSIBILITY_ID."""
        return self._find_by_accessibility_id(constants.GHA_LINK_APP_SERVICE_BTN_ACCESSIBILITY_ID)

    def _get_home_member_btn(self) -> Optional[WebElement]:
        """Get the 'Add Devices' button using ACCESSIBILITY_ID."""
        return self._find_by_accessibility_id(constants.GHA_HOME_MEMBER_BTN_ACCESSIBILITY_ID)

    def _get_home_btn(self) -> Optional[WebElement]:
        """Get the 'Add Devices' button using ACCESSIBILITY_ID."""
        return self._find_by_accessibility_id(constants.GHA_HOME_BTN_ACCESSIBILITY_ID)


    def _switch_to_page(self, btn_element: Optional[WebElement], tab_name: str) -> bool:
        """Helper method to check tab selection state and click if not selected."""
        if not btn_element:
            self._logger.error(f"Cannot switch to '{tab_name}' tab: element not found.")
            return False
        try:
            is_selected = btn_element.get_attribute("value") == "1" or btn_element.is_selected()

            if not is_selected:
                self._logger.info(f"Clicking '{tab_name}' tab to switch...")
                btn_element.click()
                time.sleep(2)
            else:
                self._logger.info(f"'{tab_name}' tab is already selected.")
            return True
        except WebDriverException as e:
            self._logger.error(f"Failed to switch to '{tab_name}' tab: {e}")
            return False


    def navigate_to_setup_device_page(self) -> bool:
        """Ensure the 'Devices' tab is selected in GHA."""
        tab = self._get_device_btn()
        return self._switch_to_page(tab, "Device")

    def navigate_to_speaker_group_page(self) -> bool:
        """Ensure the 'Favorites' tab is selected in GHA."""
        tab = self._get_speaker_group_btn()
        return self._switch_to_page(tab, "Add device with photo")

    def navigate_to_add_device_with_photo_page(self) -> bool:
        """Ensure the 'Cameras' tab is selected in GHA."""
        tab = self._get_add_device_with_photo_btn()
        return self._switch_to_page(tab, "Speaker group")

    def navigate_to_automation_page(self) -> bool:
        """Ensure the 'Lights' tab is selected in GHA."""
        tab = self._get_automation_btn()
        return self._switch_to_page(tab, "Automation")

    def navigate_to_link_app_service_page(self) -> bool:
        """Ensure the 'Lights' tab is selected in GHA."""
        tab = self._get_link_app_service_btn()
        return self._switch_to_page(tab, "Link app or service")

    def navigate_to_home_member_page(self) -> bool:
        """Ensure the 'Lights' tab is selected in GHA."""
        tab = self._get_home_member_btn()
        return self._switch_to_page(tab, "Home member")

    def navigate_to_home_page(self) -> bool:
        """Ensure the 'Lights' tab is selected in GHA."""
        tab = self._get_home_btn()
        return self._switch_to_page(tab, "Home")
