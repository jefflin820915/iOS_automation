"""Page object for handling the GHA Settings page and horizontal device card selection on iOS."""
import time
from typing import List, Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from common.base_page import BasePage, PageNotPresentException
from utils import logging_utils


class GHASettingsPage(BasePage):
    """Class for interacting with GHA Settings page, horizontal device cards, and settings navigation."""
    PAGE_LOCATOR = (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeNavigationBar[`name == "Settings"`]')
    HORIZONTAL_CARDS_COLLECTION = "preferenceDisplayingCell_5_0"
    DEVICES_SECTION_LOCATOR = (
        AppiumBy.IOS_PREDICATE,
        'label CONTAINS "Devices, groups & rooms" OR name CONTAINS "preferenceDisplayingCell"'
    )

    def _find_element(self, by: AppiumBy, locator_value: str) -> Optional[WebElement]:
        """Find an element using specified locator strategy with explicit wait."""
        try:
            return WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((by, locator_value))
            )
        except TimeoutException:
            self._logger.error(f"Timed out waiting for element: by={by}, value='{locator_value}'")
            return None

    def _find_elements(self, by: AppiumBy, value: str) -> List[WebElement]:
        """Find an element using specified locator strategy with explicit wait."""
        try:
            return WebDriverWait(self.driver, 2.0).until(
                EC.presence_of_all_elements_located((by, value))
            )
        except TimeoutException:
            self._logger.error(f"Timed out waiting for element: by={by}, value='{value}'")
            return None

    def _get_visible_device_card(self, device_name: str) -> Optional[WebElement]:
        """Find a visible device card button matching device_name on the current viewport."""
        locators = [
            f'**/XCUIElementTypeButton[`name == "categoryCard" AND label CONTAINS "{device_name}" AND visible == 1`]',
            f'**/XCUIElementTypeCell[`label CONTAINS "{device_name}" AND visible == 1`]',
            f'**/XCUIElementTypeStaticText[`name CONTAINS "{device_name}" AND visible == 1`]',
        ]
        for loc in locators:
            try:
                elems = self._find_elements(AppiumBy.IOS_CLASS_CHAIN, loc)
                for elem in elems:
                    if elem.is_displayed():
                        rect = elem.rect
                        window_width = self.driver.get_window_size().get("width", 375)
                        if 0 <= rect["x"] < window_width:
                            return elem
            except Exception:
                pass
        return None

    def _get_visible_card_labels(self) -> List[str]:
        """Fetch all visible categoryCard labels on current screen to detect scroll termination."""
        labels: List[str] = []
        try:
            elems = self._find_elements(
                AppiumBy.IOS_CLASS_CHAIN,
                '**/XCUIElementTypeButton[`name == "categoryCard" AND visible == 1`]'
            )
            for elem in elems:
                if elem.is_displayed():
                    if label := (elem.get_attribute("label") or elem.get_attribute("name")):
                        labels.append(label.strip())
        except Exception:
            pass
        return labels

    def _swipe_horizontal(self, direction: str = "left") -> None:
        """Perform a horizontal swipe on the device cards collection view."""
        self._logger.info(f"Swiping {direction} on horizontal device card list...")
        try:
            collection = self._find_elements(AppiumBy.ACCESSIBILITY_ID, self.HORIZONTAL_CARDS_COLLECTION)
            if collection and collection[0].is_displayed():
                self.driver.execute_script("mobile: swipe", {"direction": direction, "elementId": collection[0].id})
                return
        except WebDriverException:
            pass
        window = self.driver.get_window_size()
        w, h = window.get("width", 375), window.get("height", 812)
        y_pos = int(h * 0.6)
        start_x = int(w * 0.85) if direction == "left" else int(w * 0.15)
        end_x = int(w * 0.15) if direction == "left" else int(w * 0.85)
        try:
            self.driver.execute_script("mobile: dragFromToForDuration", {
                "duration": 0.5,
                "fromX": start_x,
                "fromY": y_pos,
                "toX": end_x,
                "toY": y_pos
            })
        except Exception as e:
            self._logger.warning(f"Coordinate swipe failed: {e}")

    def find_target_device(self, device_name: str, max_swipes: int = 10) -> Optional[WebElement]:
        """Search for a target device card by swiping horizontally across the cards list.
        Args:
            device_name (str): Visible name of the target device (e.g. 'Onn Wired Indoor Camera').
            max_swipes (int): Maximum number of swipe attempts. Defaults to 10.
        Returns:
            Optional[WebElement]: The matching card WebElement if found, else None.
        """
        self._logger.info(f"Start searching for device card: '{device_name}' in Settings...")
        last_seen_labels: List[str] = []
        for swipe_idx in range(max_swipes):
            if card_elem := self._get_visible_device_card(device_name):
                self._logger.info(f"Target device card '{device_name}' is VISIBLE! (Swipe #{swipe_idx})")
                return card_elem
            current_labels = self._get_visible_card_labels()
            if current_labels and current_labels == last_seen_labels and swipe_idx > 0:
                self._logger.info("Reached the end of horizontal card list.")
                break
            last_seen_labels = current_labels
            self._swipe_horizontal(direction="left")
        self._logger.info(f"Device '{device_name}' not found swiping left. Swiping right back...")
        for _ in range(3):
            self._swipe_horizontal(direction="right")
            if card_elem := self._get_visible_device_card(device_name):
                return card_elem
        self._logger.warning(f"Could not find device card '{device_name}' in Settings.")
        return None

    def open_device_settings(self, device_name: str) -> bool:
        """Find and click on the target device card to open its settings page.
        Args:
            device_name (str): Visible name of the device.
        Returns:
            bool: True if clicked successfully, False otherwise.
        """
        target_card = self.find_target_device(device_name)
        if not target_card:
            self._logger.error(f"Cannot open device settings: '{device_name}' not found.")
            return False
        try:
            self._logger.info(f"Clicking device card: '{device_name}'...")
            target_card.click()
            return True
        except WebDriverException as e:
            self._logger.warning(f"Direct click failed: {e}. Trying tap fallback...")
            try:
                self.driver.execute_script("mobile: tap", {"elementId": target_card.id})
                return True
            except Exception as tap_err:
                self._logger.error(f"Tap fallback failed: {tap_err}")
                return False

    def has_devices_groups_rooms_page(self) -> bool:
        """Check if 'Devices, groups & rooms' section exists on the Settings page."""
        try:
            elems = self.driver.find_elements(*self.DEVICES_SECTION_LOCATOR)
            return any(e.is_displayed() for e in elems)
        except Exception:
            return False


    def enter_devices_groups_rooms_page(self) -> bool:
        """Click on 'Devices, groups & rooms' row to open the full devices/rooms list."""
        self._logger.info("Entering 'Devices, groups & rooms' page...")
        try:
            elems = self._find_elements(*self.DEVICES_SECTION_LOCATOR)
            if elems and elems[0].is_displayed():
                elems[0].click()
                time.sleep(2.0)
                return True
        except Exception as e:
            self._logger.error(f"Failed to enter 'Devices, groups & rooms': {e}")
        return False

    def back_to_main_page(self) -> bool:
        """Click the close (X) button on the top-left of Settings navigation bar to return home."""
        self._logger.info("Navigating back to main page from Settings...")
        close_locators = [
            (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeNavigationBar[`name == "Settings"`]/**/XCUIElementTypeButton[1]'),
            (AppiumBy.ACCESSIBILITY_ID, "close"),
            (AppiumBy.ACCESSIBILITY_ID, "Close"),
            (AppiumBy.IOS_PREDICATE, 'label == "Close" OR name == "close"'),
        ]
        for by, value in close_locators:
            try:
                elems = self._find_elements(by, value)
                if elems and elems[0].is_displayed():
                    elems[0].click()
                    time.sleep(1.5)
                    return True
            except Exception:
                pass
        self._logger.warning("Close button not found in Settings navigation bar.")
        return False