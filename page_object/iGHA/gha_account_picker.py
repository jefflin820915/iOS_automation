"""Page object for handling GHA (Google Home App) Account Selector on iOS."""
import time
from typing import List, Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException
from utils import logging_utils

class GHAAccountPicker:
    """Class for handling Google Account Picker dialog on iOS."""

    def __init__(self, driver: WebDriver) -> None:
        """Initialize GHAAccountPickerObject with iOS Appium driver.
        Args:
            driver (WebDriver): The iOS Appium driver instance.
        """
        self.driver = driver
        self.add_another_account_id = "Add another account"

    # ==================== Helper Methods ====================
    def _get_visible_emails(self) -> List[str]:
        """Fetch all currently visible email addresses on the screen."""
        try:
            elements = self.driver.find_elements(
                AppiumBy.IOS_PREDICATE,
                "name LIKE '*@*.*' AND visible == 1"
            )
            emails = [el.get_attribute("name") for el in elements if el.get_attribute("name")]
            self._logger.info(f"Currently visible emails: {emails}")
            return emails
        except WebDriverException as e:
            self._logger.error(f"Failed to fetch visible emails: {e}")
            return []
    def _scroll_down(self) -> bool:
        """Perform scroll down action to reveal more accounts below."""
        self._logger.info("Scrolling down to search for more accounts...")
        try:
            # Native iOS scroll down command
            self.driver.execute_script("mobile: scroll", {"direction": "down"})
            return True
        except WebDriverException as e:
            self._logger.warning(f"mobile: scroll failed: {e}. Trying mobile: swipe...")
            try:
                # Fallback: swipe upwards to move content up
                self.driver.execute_script("mobile: swipe", {"direction": "up"})
                return True
            except WebDriverException as swipe_err:
                self._logger.error(f"Failed to swipe: {swipe_err}")
                return False
    def _find_element_by_id(self, accessibility_id: str) -> Optional[WebElement]:
        """Helper to find a visible element by accessibility id."""
        elements = self.driver.find_elements(AppiumBy.ACCESSIBILITY_ID, accessibility_id)
        for el in elements:
            if el.is_displayed():
                return el
        return None

    # ==================== Core Business Logic ====================
    def select_or_add_account(self, target_email: str, max_scrolls: int = 10) -> str:
        """Search for the target email across the account list.
        If found, click on it. If not found after scrolling (or reaching 'Add another account'),
        click 'Add another account'.
        Args:
            target_email (str): The target Gmail address (e.g. 'test01@gmail.com').
            max_scrolls (int): Maximum number of scroll attempts.
        Returns:
            str: "SELECTED" if target email was found and clicked,
                 "ADD_NEW_CLICKED" if 'Add another account' was clicked,
                 "FAILED" if neither operation succeeded.
        """
        self._logger.info(f"Start searching for account: '{target_email}'")
        for scroll_count in range(max_scrolls):
            visible_emails = self._get_visible_emails()
            if target_email in visible_emails:
                self._logger.info(f"Target email '{target_email}' found on screen!")
                target_element = self._find_element_by_id(target_email)
                if target_element:
                    try:
                        target_element.click()
                        self._logger.info(f"Successfully clicked on '{target_email}'.")
                        return "SELECTED"
                    except WebDriverException as e:
                        self._logger.error(f"Failed to click '{target_email}': {e}")
                        return "FAILED"
            add_account_btn = self._find_element_by_id(self.add_another_account_id)
            if add_account_btn:
                self._logger.info(
                    f"'{target_email}' not found in the list, and '{self.add_another_account_id}' is visible."
                )
                try:
                    add_account_btn.click()
                    self._logger.info("Successfully clicked 'Add another account'.")
                    return "ADD_NEW_CLICKED"
                except WebDriverException as e:
                    self._logger.error(f"Failed to click 'Add another account': {e}")
                    return "FAILED"
            self._logger.info(f"Account not found in current view (Attempt {scroll_count + 1}/{max_scrolls}).")
            if not self._scroll_down():
                self._logger.warning("Reached the end of scrollable area or scroll failed.")
                break
        add_account_btn = self._find_element_by_id(self.add_another_account_id)
        if add_account_btn:
            try:
                add_account_btn.click()
                self._logger.info("Clicked 'Add another account' after maximum scrolls.")
                return "ADD_NEW_CLICKED"
            except WebDriverException as e:
                self._logger.error(f"Failed to click 'Add another account': {e}")
                return "FAILED"
        self._logger.error(f"Could not find '{target_email}' or 'Add another account'.")
        return "FAILED"