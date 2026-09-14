"""Page object for handling the 'Where is this device?' room selection flow on iOS."""
import time
from typing import List, Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from common import constants
from common.base_page import BasePage, PageNotPresentException
from utils import logging_utils


class GHAWhereIsThisDevicePage(BasePage):
    """Class for selecting or creating rooms on the 'Where is this device?' page."""
    ADD_CUSTOM_ROOM_CELL = "setupCheckmarkCollectionViewCell_Add custom room"

    def _get_visible_room_element(self, room_name: str) -> Optional[WebElement]:
        """Find a visible room cell or text matching room_name on current viewport."""
        locators = [
            (AppiumBy.IOS_CLASS_CHAIN, f'**/XCUIElementTypeCell[`name == "setupCheckmarkCollectionViewCell_{room_name}" AND visible == 1`]'),
            (AppiumBy.IOS_PREDICATE, f'type == "XCUIElementTypeCell" AND (label == "{room_name}" OR name CONTAINS "{room_name}") AND visible == 1'),
            (AppiumBy.IOS_CLASS_CHAIN, f'**/XCUIElementTypeStaticText[`name == "{room_name}" AND visible == 1`]'),
            (AppiumBy.ACCESSIBILITY_ID, room_name),
        ]
        window_height = self.driver.get_window_size().get("height", 800)
        for by, loc in locators:
            try:
                self.driver.implicitly_wait(0)
                elems = self.driver.find_elements(by, loc)
                for elem in elems:
                    if elem.is_displayed():
                        rect = elem.rect
                        if 0 <= rect["y"] < window_height and rect["height"] > 0:
                            return elem
            except Exception:
                pass
        return None

    def _click_next_button(self) -> bool:
        """Click the primary 'Next' button."""
        next_locators = [
            (AppiumBy.ACCESSIBILITY_ID, "Next"),
            (AppiumBy.ACCESSIBILITY_ID, getattr(constants, "GHA_NEXT_BTN_ACCESSIBILITY_ID", "Next")),
            (AppiumBy.IOS_PREDICATE, 'type == "XCUIElementTypeButton" AND (name == "actionBarPrimaryButton" OR label == "Next") AND visible == 1'),
        ]
        for by, value in next_locators:
            try:
                self.driver.implicitly_wait(0)
                elems = self.driver.find_elements(by, value)
                if elems and elems[0].is_displayed() and elems[0].is_enabled():
                    elems[0].click()
                    self._logger.info("Clicked 'Next' button.")
                    return True
            except Exception:
                pass
        return False

    def select_room_or_add_custom(self, room_name: Optional[str], max_scrolls: int = 15) -> bool:
        """Scroll to locate target room, select it, and click Next."""
        target_room = room_name or "Default Room"
        self._logger.info(f"Starting room selection for target: '{target_room}'...")
        for scroll_idx in range(max_scrolls):
            if room_elem := self._get_visible_room_element(target_room):
                self._logger.info(f"Target room '{target_room}' is VISIBLE! Selecting now...")
                try:
                    room_elem.click()
                except WebDriverException:
                    self.driver.execute_script("mobile: tap", {"elementId": room_elem.id})
                time.sleep(1.0)
                if self._click_next_button():
                    return True
                time.sleep(0.5)
                return self._click_next_button()
            custom_room_elems = self.driver.find_elements(
                AppiumBy.IOS_CLASS_CHAIN,
                f'**/XCUIElementTypeCell[`name == "{self.ADD_CUSTOM_ROOM_CELL}" AND visible == 1`]'
            )
            if custom_room_elems and custom_room_elems[0].is_displayed():
                self._logger.info(f"Room '{target_room}' not found in presets. Selecting 'Add custom room'...")
                custom_room_elems[0].click()
                time.sleep(1.0)
                self._click_next_button()
                self._handle_custom_room_text_input_if_present(target_room)
                return True
            self._logger.info(f"Room '{target_room}' not yet visible. Scrolling down ({scroll_idx + 1}/{max_scrolls})...")
            try:
                self.driver.execute_script("mobile: swipe", {"direction": "up"})
                time.sleep(1.0)
            except Exception:
                break
        self._logger.warning(f"Could not find '{target_room}'. Falling back to first available room on screen...")
        first_cells = self.driver.find_elements(AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeCell[`visible == 1`]')
        for cell in first_cells:
            if cell.is_displayed() and cell.rect["height"] > 0:
                cell.click()
                time.sleep(1.0)
                return self._click_next_button()
        return False
    def _handle_custom_room_text_input_if_present(self, custom_room_name: str) -> None:
        """Handle custom room name textfield if opened after clicking 'Add custom room'."""
        try:
            text_fields = self.driver.find_elements(AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeTextField[`visible == 1`]')
            if text_fields:
                self._logger.info(f"Entering custom room name: '{custom_room_name}'...")
                text_fields[0].send_keys(custom_room_name)
                time.sleep(1.0)
                self._click_next_button()
        except Exception as e:
            self._logger.debug(f"No custom room text field prompt: {e}")