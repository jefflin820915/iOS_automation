"""Page object method for verifying device existence on the Devices page in iOS."""
import time
from typing import List, Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException, StaleElementReferenceException
from common.base_page import BasePage, PageNotPresentException
from common import constants
from utils import logging_utils


class GHADevicePage(BasePage):
    """Class for handling device tiles, discovery, and navigation on iOS Devices page."""

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Collapse newlines and multiple spaces into a single space."""
        if not text:
            return ""
        return " ".join(text.replace("\n", " ").replace("\r", " ").split()).strip()

    def _is_target_device_visible_on_screen(self, device_name: str) -> Optional[WebElement]:
        """Directly check if target device tile/text is currently visible on screen.
        Uses case-insensitive CONTAINS[c] predicate and normalized text matching.
        Returns:
            WebElement if found and displayed, None otherwise.
        """
        norm_target = self._normalize_text(device_name).lower()
        default_wait = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
        self.driver.implicitly_wait(0)
        try:
            strategies = [
                # 策略 1: iOS Predicate 不分大小寫 [c] 搜尋
                (
                    AppiumBy.IOS_PREDICATE,
                    f'label CONTAINS[c] "{device_name}" OR '
                    f'name CONTAINS[c] "{device_name}" OR '
                    f'value CONTAINS[c] "{device_name}"'
                ),
                (
                    AppiumBy.XPATH,
                    f'//XCUIElementTypeCell[contains(@label, "{device_name}")] | '
                    f'//XCUIElementTypeButton[contains(@label, "{device_name}")] | '
                    f'//XCUIElementTypeStaticText[contains(@label, "{device_name}") or contains(@value, "{device_name}")]'
                ),
                (AppiumBy.ACCESSIBILITY_ID, device_name),
            ]
            for by, loc in strategies:
                try:
                    elems = self.driver.find_elements(by, loc)
                    for elem in elems:
                        if elem.is_displayed():
                            rect = elem.rect
                            if rect["y"] > 50 and rect["height"] > 10:
                                return elem
                except Exception:
                    continue
            for elem in self._get_device_tab_device_name_elements():
                try:
                    raw_text = (
                            elem.get_attribute("label")
                            or elem.get_attribute("name")
                            or elem.get_attribute("value")
                            or elem.text
                            or ""
                    )
                    norm_curr = self._normalize_text(raw_text).lower()
                    if norm_target and norm_target in norm_curr and elem.is_displayed():
                        rect = elem.rect
                        if rect["y"] > 50 and rect["height"] > 10:
                            return elem
                except Exception:
                    continue
        finally:
            self.driver.implicitly_wait(default_wait)
        return None

    def _get_device_tab_device_name_elements(self) -> List[WebElement]:
        """Retrieve all visible device candidate elements (Cells, Buttons, and StaticTexts)."""
        default_wait = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
        self.driver.implicitly_wait(0)
        collected: List[WebElement] = []
        try:
            locators = [
                (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeCell[`name BEGINSWITH "deviceTileCell"`]'),
                (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "deviceTile"`]'),
                (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeStaticText[`name == "deviceTileTitleTextView"`]'),
                (AppiumBy.IOS_CLASS_CHAIN, getattr(constants, "GHA_DEVICE_NAME_CLASS_CHAIN", '**/XCUIElementTypeCell')),
            ]
            for by, loc in locators:
                try:
                    elems = self.driver.find_elements(by, loc)
                    if elems:
                        collected.extend(elems)
                except WebDriverException:
                    pass
        finally:
            self.driver.implicitly_wait(default_wait)
        return collected

    def _swipe_down_page(self) -> None:
        """Perform a controlled swipe down (viewport moves down, content moves up)."""
        try:
            size = self.driver.get_window_size()
            start_x = size["width"] // 2
            start_y = int(size["height"] * 0.68)
            end_y = int(size["height"] * 0.38)
            self.driver.swipe(start_x, start_y, start_x, end_y, duration=450)
            time.sleep(1.0)
        except Exception as e:
            self._logger.warning(f"Swipe failed ({e}), attempting mobile: scroll fallback...")
            try:
                self.driver.execute_script("mobile: scroll", {"direction": "down"})
                time.sleep(1.0)
            except Exception:
                pass

    def _swipe_up_to_top(self) -> None:
        """Swipe from top to bottom to return viewport to the top of the device list (Attic)."""
        try:
            size = self.driver.get_window_size()
            start_x = size["width"] // 2
            start_y = int(size["height"] * 0.28)
            end_y = int(size["height"] * 0.80)
            for _ in range(2):
                self.driver.swipe(start_x, start_y, start_x, end_y, duration=350)
                time.sleep(0.6)
        except Exception:
            pass

    def is_device_exist_device_page(self, device_name: str, max_scrolls: int = 15) -> bool:
        """Check if a specific device exists on the Devices page by polling top screen first, then scrolling.
        Args:
            device_name (str): The name of the device to locate.
            max_scrolls (int): Maximum number of scroll attempts. Defaults to 15.
        Returns:
            bool: True if the device is found, False otherwise.
        """
        self._logger.info(f"Start searching for device: '{device_name}' on Devices page...")
        norm_target = self._normalize_text(device_name).lower()
        poll_deadline = time.time() + 6.0
        while time.time() < poll_deadline:
            if self._is_target_device_visible_on_screen(device_name):
                self._logger.info(f"Target device '{device_name}' detected on initial top screen without scrolling!")
                return True
            initial_elems = self._get_device_tab_device_name_elements()
            if initial_elems:
                for elem in initial_elems:
                    try:
                        raw_lbl = elem.get_attribute("label") or elem.get_attribute("name") or elem.text or ""
                        if norm_target in self._normalize_text(raw_lbl).lower():
                            self._logger.info(f"Target device '{device_name}' matched during initial load: '{raw_lbl}'!")
                            return True
                    except Exception:
                        continue
            time.sleep(0.8)
        seen_device_names = set()
        consecutive_no_new_devices = 0
        for scroll_idx in range(max_scrolls):
            target_elem = self._is_target_device_visible_on_screen(device_name)
            if target_elem:
                self._logger.info(f"Target device '{device_name}' found directly on screen (scroll {scroll_idx})!")
                return True
            device_elements = self._get_device_tab_device_name_elements()
            new_devices_found = False
            for elem in device_elements:
                try:
                    raw_name = (
                            elem.get_attribute("label")
                            or elem.get_attribute("name")
                            or elem.get_attribute("value")
                            or elem.text
                            or ""
                    )
                    current_name = self._normalize_text(raw_name)
                    if not current_name or current_name.startswith("deviceTile"):
                        continue
                    clean_name = current_name.split(",")[0].strip()
                    if clean_name and clean_name not in seen_device_names:
                        seen_device_names.add(clean_name)
                        new_devices_found = True
                        self._logger.info(f"Discovered device: '{clean_name}' (Raw: '{current_name}')")
                    norm_curr = current_name.lower()
                    norm_clean = clean_name.lower()
                    if (
                            norm_target == norm_curr
                            or norm_target == norm_clean
                            or norm_curr.startswith(f"{norm_target},")
                            or norm_target in norm_curr
                    ):
                        self._logger.info(f"Target device '{device_name}' matched from element text: '{current_name}'!")
                        return True
                except (StaleElementReferenceException, WebDriverException):
                    continue
            if not seen_device_names and scroll_idx < 2:
                self._logger.info("Device grid still loading (0 tiles seen). Waiting 1.5s before scrolling...")
                time.sleep(1.5)
                continue
            if not new_devices_found:
                consecutive_no_new_devices += 1
            else:
                consecutive_no_new_devices = 0
            if consecutive_no_new_devices >= 3 and scroll_idx >= 2:
                self._logger.info("Reached end of list. Scrolling back to top (Attic) for a final check...")
                self._swipe_up_to_top()
                if self._is_target_device_visible_on_screen(device_name):
                    self._logger.info(f"Target device '{device_name}' found after returning to top of list!")
                    return True
                raise AssertionError(
                    f"Reached the end of device list. Target '{device_name}' not found. Discovered: {list(seen_device_names)}"
                )
            self._logger.info(f"Device '{device_name}' not in current view. Scrolling down ({scroll_idx + 1}/{max_scrolls})...")
            self._swipe_down_page()
        self._logger.info(f"Could not find device '{device_name}' after {max_scrolls} scrolls.")
        raise AssertionError(
            f"Could not find device '{device_name}' after {max_scrolls} scrolls. Discovered: {list(seen_device_names)}"
        )

    def _is_in_device_or_camera_page(self) -> bool:
        """Check if navigation into device details or camera live page has completed."""
        nav_locators = [
            (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "closeButton" AND visible == 1`]'),
            (AppiumBy.ACCESSIBILITY_ID, "closeButton"),
            (AppiumBy.ACCESSIBILITY_ID, "close"),
            (AppiumBy.ACCESSIBILITY_ID, "Close"),
            (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "CamerazillaPlayerView" AND visible == 1`]'),
            (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeOther[`name == "CamerazillaPlayerView" AND visible == 1`]'),
            (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "cameraStatusBadgeView" AND visible == 1`]'),
            (AppiumBy.IOS_PREDICATE, 'label == "Back" OR name == "Back" OR name == "chevron.backward"'),
            (AppiumBy.ACCESSIBILITY_ID, "Back"),
            (AppiumBy.ACCESSIBILITY_ID, "chevron.backward"),
        ]
        default_wait = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
        try:
            self.driver.implicitly_wait(0)
            for by, loc in nav_locators:
                matches = self.driver.find_elements(by, loc)
                for elem in matches:
                    if elem.is_displayed():
                        return True
        except Exception:
            pass
        finally:
            self.driver.implicitly_wait(default_wait)
        return False

    def enter_device_page(self, device_name: str, duration: float = 2.5, max_retries: int = 2) -> bool:
        """Robustly tap or long-press on a device tile to enter its detail/control page on iOS."""
        self._logger.info(f"Attempting to enter device page for: '{device_name}'...")
        def find_target_tile() -> Optional[WebElement]:
            """Find fresh target element on current screen with multiple resilient locators."""
            elem = self._is_target_device_visible_on_screen(device_name)
            if elem:
                return elem
            locators = [
                (AppiumBy.IOS_PREDICATE, f'label CONTAINS[c] "{device_name}" OR name CONTAINS[c] "{device_name}"'),
                (AppiumBy.XPATH, f"//XCUIElementTypeCell[contains(@label, '{device_name}')]"),
                (AppiumBy.XPATH, f"//XCUIElementTypeButton[contains(@label, '{device_name}')]"),
            ]
            for by, loc in locators:
                try:
                    elems = self.driver.find_elements(by=by, value=loc)
                    for e in elems:
                        if e.is_displayed():
                            return e
                except Exception:
                    continue
            return None
        if self._is_in_device_or_camera_page():
            self._logger.info(f"Already detected in device/camera page for '{device_name}'.")
            return True
        for attempt in range(1, max_retries + 1):
            if self._is_in_device_or_camera_page():
                self._logger.info(f"Successfully entered device page for '{device_name}' (confirmed on attempt {attempt})!")
                return True
            self._logger.info(f"[Attempt {attempt}/{max_retries}] Triggering interaction on '{device_name}'...")
            target_element = find_target_tile()
            if not target_element:
                time.sleep(1.5)
                if self._is_in_device_or_camera_page():
                    self._logger.info(f"Device tile disappeared because device page loaded! (Attempt {attempt})")
                    return True
                self._logger.warning(f"Device tile for '{device_name}' not found on attempt {attempt}.")
                continue
            try:
                rect = target_element.rect
                center_x = int(rect['x'] + rect['width'] / 2)
                center_y = int(rect['y'] + rect['height'] / 2)
                if duration >= 2.0 or attempt > 1:
                    self._logger.info(f"Executing mobile: touchAndHold at ({center_x}, {center_y}) for {duration}s...")
                    try:
                        self.driver.execute_script("mobile: touchAndHold", {
                            "elementId": target_element.id,
                            "duration": duration
                        })
                    except Exception:
                        self.driver.execute_script("mobile: touchAndHold", {
                            "x": center_x,
                            "y": center_y,
                            "duration": duration
                        })
                else:
                    self._logger.info(f"Executing direct click / coordinate tap at ({center_x}, {center_y})...")
                    try:
                        target_element.click()
                    except Exception:
                        self.driver.execute_script("mobile: tap", {"x": center_x, "y": center_y})
            except (StaleElementReferenceException, WebDriverException) as interact_err:
                self._logger.warning(f"Interaction exception: {interact_err}. Verifying if navigation occurred...")
                time.sleep(2.0)
                if self._is_in_device_or_camera_page():
                    self._logger.info(f"Navigation confirmed after interaction exception! (Attempt {attempt})")
                    return True
                continue
            poll_start = time.time()
            navigated = False
            while time.time() - poll_start < 5.0:
                if self._is_in_device_or_camera_page():
                    navigated = True
                    break
                time.sleep(0.5)
            if navigated:
                self._logger.info(f"Successfully entered device page for '{device_name}' on attempt {attempt}!")
                return True
            self._logger.warning(f"Did not detect navigation after attempt {attempt}. Retrying...")
        if self._is_in_device_or_camera_page():
            self._logger.info(f"Final check passed: inside device page for '{device_name}'.")
            return True
        self._logger.error(f"Failed to enter device page for '{device_name}' after {max_retries} attempts.")
        raise AssertionError(f"Failed to enter device page for '{device_name}' after {max_retries} attempts.")