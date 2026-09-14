"""Page object for handling the Device Settings page and scrolling to remove device on iOS."""
import time
from typing import Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from common import constants
from common.base_page import BasePage, PageNotPresentException
from utils import logging_utils
class GHADeviceSettingPage(BasePage):
    """Class for managing device-specific settings and removing device on iOS."""

    REMOVE_DEVICE_LOCATORS = [
        AppiumBy.XPATH,
        '//XCUIElementTypeButton[@name="Remove device" or @label="Remove device"]'
    ]

    def _get_visible_remove_btn(self) -> Optional[WebElement]:
        """Find 'Remove device' button with 0s implicit wait to prevent freezing at top of page."""
        self.driver.implicitly_wait(0)
        try:
            elems = self.driver.find_elements(*self.REMOVE_DEVICE_LOCATORS)
            for elem in elems:
                if elem.is_displayed():
                    rect = elem.rect
                    if rect["y"] > 0:
                        return elem
        except Exception:
            pass
        finally:
            self.driver.implicitly_wait(getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0))
        return None

    def _fast_swipe_down(self) -> None:
        """Perform a fast full-page swipe down to reach the bottom quickly."""
        try:
            self.driver.execute_script("mobile: swipe", {"direction": "up"})
        except Exception:
            try:
                self.driver.execute_script("mobile: scroll", {"direction": "down"})
            except Exception:
                pass
    def click_remove_device_btn(self, max_scrolls: int = 5) -> bool:
        """Quickly swipe down the Device Settings page to locate and click 'Remove device' button.

        Args:
            max_scrolls (int): Maximum swipes to reach bottom. Usually only needs 1-2 swipes.
        Returns:
            bool: True if clicked successfully.
        """
        self._logger.info("Fast scrolling down to locate 'Remove device' button...")
        for scroll_idx in range(max_scrolls):
            remove_btn = self._get_visible_remove_btn()
            if remove_btn:
                self._logger.info(f"'Remove device' button found (after {scroll_idx} swipes)! Clicking...")
                try:
                    remove_btn.click()
                except WebDriverException:
                    self.driver.execute_script("mobile: tap", {"elementId": remove_btn.id})
                self._logger.info("Waiting for secondary 'Remove' confirmation dialog...")
                try:
                    confirm_btn = WebDriverWait(self.driver, 4.0).until(
                        EC.element_to_be_clickable((
                            AppiumBy.XPATH,
                            '//XCUIElementTypeButton[@name="Remove" or @label="Remove"]'
                        ))
                    )
                    confirm_btn.click()
                    self._logger.info("Successfully confirmed device removal.")
                    time.sleep(2.0)
                    return True
                except TimeoutException:
                    self._logger.warning("Confirmation 'Remove' dialog button did not appear within 4s.")
                    return True
            self._logger.info(f"Not visible yet. Fast swiping ({scroll_idx + 1}/{max_scrolls})...")
            self._fast_swipe_down()
            time.sleep(0.3)
        raise PageNotPresentException(
            locator=self.REMOVE_DEVICE_LOCATORS,
            page_name=self.__class__.__name__,
            message=f"Failed to find 'Remove device' button after {max_scrolls} swipes on Device Settings page."
        )