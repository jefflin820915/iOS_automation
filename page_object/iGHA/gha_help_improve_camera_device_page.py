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


class GHAHelpImproveCameraDevicePage(BasePage):
    """Class for handling GHA bottom navigation tab interactions on iOS."""
    PAGE_HEADLINE = "Help improve camera device screen."

    # def __init__(self, driver: WebDriver, timeout: float = 10.0) -> None:
    #     """Initialize GHAHomeTabObject with iOS Appium driver.
    #
    #     Args:
    #         driver (WebDriver): The iOS Appium driver instance.
    #         timeout (float): Default timeout in seconds for finding elements.
    #     """
    #     self.driver = driver
    #     self.timeout = timeout
    #     self._logger = logging_utils.get_logger(__name__, "privacy")

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

    def _get_yes_i_m_in_btn(self) -> Optional[WebElement]:
        """Get the 'Add Devices' button using ACCESSIBILITY_ID."""
        return self._find_by_class_chain(constants.GHA_YES_I_M_IN_BTN_CLASS_CHAIN)

    def _get_no_thanks_btn(self) -> Optional[WebElement]:
        """Get the 'Add Devices' button using ACCESSIBILITY_ID."""
        return self._find_by_class_chain(constants.GHA_NO_THANKS_BTN_CLASS_CHAIN)

    def click_yes_i_m_in_btn(self) -> bool:
        """Ensure the 'Devices' tab is selected in GHA."""
        return self._get_yes_i_m_in_btn().click()

    def click_no_thanks_btn(self) -> bool:
        """Ensure the 'Devices' tab is selected in GHA."""
        return self._get_no_thanks_btn().click()

