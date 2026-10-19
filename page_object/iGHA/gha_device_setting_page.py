"""Page object for handling the Device Settings page, mDNS discovery, and removing device on iOS."""
import contextlib
import re
import time
from typing import Dict, List, Optional, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from common import constants
from common.base_page import BasePage, PageNotPresentException
from utils import logging_utils
from utils.mdns_utils import MDNSUtils
class GHADeviceSettingPage(BasePage):
    """Class for managing device-specific settings, resolving mDNS, and removing device on iOS."""
    REMOVE_DEVICE_LOCATORS: List[Tuple[AppiumBy, str]] = [
        (AppiumBy.ACCESSIBILITY_ID, "Remove device"),
        (AppiumBy.ACCESSIBILITY_ID, "Unlink all"),
        (AppiumBy.ACCESSIBILITY_ID, "Remove this device"),
        (AppiumBy.ACCESSIBILITY_ID, "Delete device"),
        (AppiumBy.ACCESSIBILITY_ID, "Unlink device"),
        (
            AppiumBy.IOS_CLASS_CHAIN,
            '**/XCUIElementTypeButton[`name == "Remove device" OR label == "Remove device" '
            'OR name == "Unlink all" OR label == "Unlink all" '
            'OR name CONTAINS[c] "Remove device" OR label CONTAINS[c] "Remove device" '
            'OR name CONTAINS[c] "Remove this device" OR label CONTAINS[c] "Remove this device" '
            'OR name CONTAINS[c] "Unlink all" OR label CONTAINS[c] "Unlink all"`]',
        ),
        (
            AppiumBy.IOS_PREDICATE,
            'name == "Remove device" OR label == "Remove device" '
            'OR name == "Unlink all" OR label == "Unlink all" '
            'OR ((type == "XCUIElementTypeButton" OR type == "XCUIElementTypeCell" '
            'OR type == "XCUIElementTypeStaticText") AND ('
            'name CONTAINS[c] "Remove device" OR label CONTAINS[c] "Remove device" '
            'OR value CONTAINS[c] "Remove device" '
            'OR name CONTAINS[c] "Remove this device" OR label CONTAINS[c] "Remove this device" '
            'OR name CONTAINS[c] "Delete device" OR label CONTAINS[c] "Delete device" '
            'OR name CONTAINS[c] "Unlink all" OR label CONTAINS[c] "Unlink all" '
            'OR name CONTAINS[c] "Unlink device" OR label CONTAINS[c] "Unlink device"))',
        ),
        (
            AppiumBy.XPATH,
            '//XCUIElementTypeButton[@name="Remove device" or @label="Remove device" '
            'or @name="Unlink all" or @label="Unlink all" '
            'or contains(@name, "Remove device") or contains(@label, "Remove device") '
            'or contains(@name, "Remove this device") or contains(@label, "Remove this device")] | '
            '//XCUIElementTypeCell[.//XCUIElementTypeStaticText[@name="Remove device" or @label="Remove device" '
            'or @name="Unlink all" or @label="Unlink all" '
            'or contains(@name, "Remove device") or contains(@label, "Remove device")]] | '
            '//XCUIElementTypeStaticText[@name="Remove device" or @label="Remove device" '
            'or @name="Unlink all" or @label="Unlink all"]',
        ),
    ]
    DELETE_VIDEO_HISTORY_LOCATORS: List[Tuple[AppiumBy, str]] = [
        (AppiumBy.ACCESSIBILITY_ID, "Delete video history"),
        (
            AppiumBy.IOS_PREDICATE,
            '(type == "XCUIElementTypeButton" OR type == "XCUIElementTypeCell" '
            'OR type == "XCUIElementTypeStaticText") AND ('
            'name CONTAINS[c] "Delete video history" OR label CONTAINS[c] "Delete video history" '
            'OR value CONTAINS[c] "Delete video history")',
        ),
        (
            AppiumBy.XPATH,
            '//*[contains(@name, "Delete video history") or contains(@label, "Delete video history")]',
        ),
    ]
    DEVICE_SETTINGS_CLOSE_LOCATORS: List[Tuple[AppiumBy, str]] = [
        (AppiumBy.ACCESSIBILITY_ID, "closeButton"),
        (AppiumBy.ACCESSIBILITY_ID, "Close"),
        (AppiumBy.ACCESSIBILITY_ID, "BackButton"),
        (AppiumBy.ACCESSIBILITY_ID, "Back"),
        (
            AppiumBy.IOS_PREDICATE,
            'type == "XCUIElementTypeButton" AND ('
            'name IN {"closeButton", "Close", "close", "BackButton", "Back", "back", "xmark", "chevron.backward"} '
            'OR label IN {"Close", "close", "Back", "back", "Dismiss"})',
        ),
        (
            AppiumBy.XPATH,
            '//XCUIElementTypeNavigationBar//XCUIElementTypeButton[1]',
        ),
    ]
    CONFIRM_REMOVE_LOCATORS: List[Tuple[AppiumBy, str]] = [
        (
            AppiumBy.XPATH,
            '//XCUIElementTypeButton[@name="Remove" or @label="Remove" '
            'or @name="Unlink all" or @label="Unlink all" '
            'or @name="Unlink" or @label="Unlink"]',
        ),
        (AppiumBy.ACCESSIBILITY_ID, "Remove"),
        (AppiumBy.ACCESSIBILITY_ID, "Unlink all"),
        (AppiumBy.ACCESSIBILITY_ID, "Unlink"),
        (
            AppiumBy.IOS_CLASS_CHAIN,
            '**/XCUIElementTypeButton[`label == "Remove" OR name == "Remove" '
            'OR label == "Unlink all" OR name == "Unlink all" '
            'OR label == "Unlink" OR name == "Unlink"`]',
        ),
        (
            AppiumBy.IOS_PREDICATE,
            '(type == "XCUIElementTypeButton" OR type == "XCUIElementTypeStaticText") AND ('
            'name IN {"Remove", "Unlink all", "Unlink", "Delete"} OR '
            'label IN {"Remove", "Unlink all", "Unlink", "Delete"})',
        ),
        (AppiumBy.ACCESSIBILITY_ID, "Delete"),
    ]
    UNLINK_ALL_CONFIRM_LOCATORS: List[Tuple[AppiumBy, str]] = [
        (AppiumBy.ACCESSIBILITY_ID, "Unlink all"),
        (
            AppiumBy.IOS_CLASS_CHAIN,
            '**/XCUIElementTypeButton[`label == "Unlink all" OR name == "Unlink all"`]',
        ),
        (
            AppiumBy.XPATH,
            '//XCUIElementTypeButton[@name="Unlink all" or @label="Unlink all"]',
        ),
    ]
    DEVICE_INFO_ENTRY_LOCATORS: List[Tuple[AppiumBy, str]] = [
        (
            AppiumBy.XPATH,
            '//XCUIElementTypeCell[.//XCUIElementTypeStaticText[@name="Device information" '
            'or @label="Device information" or @value="Device information"]] | '
            '//XCUIElementTypeCell[contains(@label, "Device information")] | '
            '//XCUIElementTypeStaticText[@name="Device information" or @label="Device information"]',
        ),
        (AppiumBy.ACCESSIBILITY_ID, "Device information"),
        (
            AppiumBy.IOS_PREDICATE,
            'type == "XCUIElementTypeCell" AND label BEGINSWITH "Device information"',
        ),
    ]
    # On some iOS / GHA versions the '< Back' button has name="BackButton" and label="Back";
    # on others name and label are both "Back" (or it is the first button in the NavigationBar).
    DEVICE_INFO_BACK_LOCATORS: List[Tuple[AppiumBy, str]] = [
        (
            AppiumBy.IOS_PREDICATE,
            'type == "XCUIElementTypeButton" AND ('
            'name == "BackButton" OR label == "BackButton" OR '
            'name == "Back" OR label == "Back" OR '
            'name == "chevron.backward" OR '
            'name BEGINSWITH "Back" OR label BEGINSWITH "Back")',
        ),
        (AppiumBy.ACCESSIBILITY_ID, "BackButton"),
        (AppiumBy.ACCESSIBILITY_ID, "Back"),
        (
            AppiumBy.XPATH,
            '//XCUIElementTypeButton[@name="BackButton" or @label="Back" or @name="Back" '
            'or starts-with(@label, "Back") or starts-with(@name, "Back")] | '
            '//XCUIElementTypeNavigationBar//XCUIElementTypeButton[1]',
        ),
    ]
    DEVICE_INFO_PAGE_MARKERS: List[Tuple[AppiumBy, str]] = [
        (
            AppiumBy.IOS_PREDICATE,
            '(type == "XCUIElementTypeStaticText" OR type == "XCUIElementTypeTextView") AND ('
            'name == "Device information" OR label == "Device information" OR '
            'label BEGINSWITH "Technical information" OR '
            'value CONTAINS "Device ID:" OR label CONTAINS "Device ID:")',
        ),
        (
            AppiumBy.XPATH,
            '//XCUIElementTypeStaticText[contains(@value, "Device ID:") or contains(@label, "Device ID:") '
            'or starts-with(@label, "Technical information")] | '
            '//XCUIElementTypeTextView[contains(@value, "Device ID:") or contains(@label, "Device ID:")]',
        ),
    ]
    TECH_INFO_LOCATORS: List[Tuple[AppiumBy, str]] = [
        (
            AppiumBy.IOS_PREDICATE,
            '(type == "XCUIElementTypeStaticText" OR type == "XCUIElementTypeTextView") AND ('
            'value CONTAINS "Device ID:" OR label CONTAINS "Device ID:" OR name CONTAINS "Device ID:")',
        ),
        (
            AppiumBy.XPATH,
            '//XCUIElementTypeStaticText[contains(@value, "Device ID:") or contains(@label, "Device ID:")] | '
            '//XCUIElementTypeTextView[contains(@value, "Device ID:") or contains(@label, "Device ID:") '
            'or contains(@name, "Device ID:")]',
        ),
    ]
    @contextlib.contextmanager
    def _devset_no_implicit_wait(self):
        """Temporarily set implicit wait to 0s so multi-locator checks do not stall 10s per miss."""
        default_wait = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
        try:
            self.driver.implicitly_wait(0)
        except Exception:
            pass
        try:
            yield
        finally:
            try:
                self.driver.implicitly_wait(default_wait)
            except Exception:
                pass
    def _devset_tap_element(self, elem: WebElement, desc: str = "element") -> bool:
        """Click an element with fallback to mobile: tap by elementId, then by rect center."""
        try:
            elem.click()
            return True
        except (WebDriverException, StaleElementReferenceException) as err:
            self._logger.warning(f"Standard click on {desc} failed ({err}), trying tap fallbacks...")
        try:
            self.driver.execute_script("mobile: tap", {"elementId": elem.id})
            return True
        except Exception:
            pass
        try:
            rect = elem.rect
            tap_x = int(rect["x"] + rect["width"] / 2)
            tap_y = int(rect["y"] + rect["height"] / 2)
            self.driver.execute_script("mobile: tap", {"x": tap_x, "y": tap_y})
            self._logger.info(f"Coordinate-tapped {desc} at ({tap_x}, {tap_y}).")
            return True
        except Exception as tap_err:
            self._logger.error(f"All tap methods failed for {desc}: {tap_err}")
            return False
    @staticmethod
    def _devset_elem_label(elem: WebElement, default: str = "Remove") -> str:
        """Read human-readable label/name of an element for logging."""
        for attr in ("label", "name", "value"):
            try:
                val = (elem.get_attribute(attr) or "").strip()
                if val:
                    return val
            except Exception:
                pass
        return default
    def _devset_find_first(
            self, locators: List[Tuple[AppiumBy, str]], require_displayed: bool = True
    ) -> Optional[WebElement]:
        """Return the first matching element across locators (0s implicit wait), or None."""
        with self._devset_no_implicit_wait():
            for by, val in locators:
                try:
                    for elem in self.driver.find_elements(by, val):
                        try:
                            if not require_displayed or elem.is_displayed():
                                return elem
                        except Exception:
                            if not require_displayed:
                                return elem
                except Exception:
                    continue
        return None
    def _devset_is_on_device_info_page(self) -> bool:
        """Return True if the '< Back' button or Device information page content is present."""
        if self._devset_find_first(self.DEVICE_INFO_BACK_LOCATORS, require_displayed=True):
            return True
        if self._devset_find_first(self.DEVICE_INFO_PAGE_MARKERS, require_displayed=False):
            return True
        return False
    def _devset_wait_for_device_info_page(self, timeout: float = 8.0) -> bool:
        """Poll until the Device information page is loaded."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._devset_is_on_device_info_page():
                return True
            time.sleep(0.4)
        return False
    def _devset_read_tech_text(self, timeout: float = 5.0) -> str:
        """Extract raw technical info text ('Device ID: ...') from StaticText or TextView."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._devset_no_implicit_wait():
                for by, val in self.TECH_INFO_LOCATORS:
                    try:
                        elems = self.driver.find_elements(by, val)
                    except Exception:
                        continue
                    for elem in elems:
                        for attr in ("value", "label", "name"):
                            try:
                                txt = elem.get_attribute(attr)
                                if txt and "Device ID:" in txt:
                                    return txt
                            except Exception:
                                pass
                        try:
                            txt = elem.text
                            if txt and "Device ID:" in txt:
                                return txt
                        except Exception:
                            pass
                for cls_name in ("XCUIElementTypeStaticText", "XCUIElementTypeTextView"):
                    try:
                        elems = self.driver.find_elements(AppiumBy.CLASS_NAME, cls_name)
                    except Exception:
                        continue
                    for elem in elems:
                        for attr in ("value", "label", "name"):
                            try:
                                txt = elem.get_attribute(attr)
                                if txt and "Device ID:" in txt:
                                    return txt
                            except Exception:
                                pass
                        try:
                            txt = elem.text
                            if txt and "Device ID:" in txt:
                                return txt
                        except Exception:
                            pass
            time.sleep(0.5)
        return ""
    def _devset_navigate_back_from_device_info(self) -> bool:
        """Return from 'Device information' to 'Device settings' via '< Back' button or driver.back()."""
        back_btn = (
                self._devset_find_first(self.DEVICE_INFO_BACK_LOCATORS, require_displayed=True)
                or self._devset_find_first(self.DEVICE_INFO_BACK_LOCATORS, require_displayed=False)
        )
        if back_btn and self._devset_tap_element(back_btn, "'< Back' button"):
            time.sleep(1.5)
            return True
        try:
            self._logger.info("'< Back' button locator did not match; trying driver.back()...")
            self.driver.back()
            time.sleep(1.5)
            return True
        except Exception as back_err:
            self._logger.warning(f"driver.back() failed: {back_err}")
            return False
    def _get_delete_video_history_y(self) -> Optional[int]:
        """Return the current vertical y-coordinate of 'Delete video history' if visible on screen, else None."""
        try:
            window_size = self.driver.get_window_size()
            screen_height = window_size["height"]
        except Exception:
            screen_height = 9999
        with self._devset_no_implicit_wait():
            for by, val in self.DELETE_VIDEO_HISTORY_LOCATORS:
                try:
                    for elem in self.driver.find_elements(by, val):
                        try:
                            rect = elem.rect
                            if 40 < rect["y"] < screen_height - 2 and rect["height"] > 10:
                                if elem.is_displayed() or rect.get("width", 0) > 20:
                                    return int(rect["y"])
                        except Exception:
                            continue
                except Exception:
                    continue
        return None
    def _is_delete_video_history_visible(self) -> bool:
        """Return True if the 'Delete video history' button/cell at the bottom of Device Settings is visible."""
        return self._get_delete_video_history_y() is not None
    def _get_visible_remove_btn(self) -> Optional[WebElement]:
        """Find visible and hittable 'Remove device' or 'Unlink all' button with multi-strategy locators."""
        try:
            window_size = self.driver.get_window_size()
            screen_height = window_size["height"]
        except Exception:
            screen_height = 9999
        fallback_candidate: Optional[WebElement] = None
        with self._devset_no_implicit_wait():
            for by, val in self.REMOVE_DEVICE_LOCATORS:
                try:
                    elems = self.driver.find_elements(by, val)
                    for elem in elems:
                        label_lower = self._devset_elem_label(elem, "").lower()
                        if "video history" in label_lower or "delete history" in label_lower:
                            continue
                        try:
                            rect = elem.rect
                        except Exception:
                            continue
                        in_viewport = 40 < rect["y"] < screen_height - 2 and rect["height"] > 10
                        if not in_viewport:
                            continue
                        try:
                            if elem.is_displayed():
                                return elem
                        except Exception:
                            pass
                        if fallback_candidate is None and rect.get("width", 0) > 20:
                            fallback_candidate = elem
                except Exception:
                    continue
        return fallback_candidate
    def _swipe_down_page(self, force_scroll_to_bottom: bool = False) -> None:
        """Perform a controlled physical swipe down (content moves up) with settling sleep."""
        try:
            size = self.driver.get_window_size()
            start_x = size["width"] // 2
            start_y = int(size["height"] * 0.78)
            end_y = int(size["height"] * 0.22)
            self.driver.swipe(start_x, start_y, start_x, end_y, duration=350)
            time.sleep(1.0)
        except Exception as e:
            self._logger.warning(f"Coordinate swipe failed ({e}), trying mobile: swipe fallback...")
            try:
                self.driver.execute_script("mobile: swipe", {"direction": "up"})
                time.sleep(1.0)
            except Exception:
                pass
        if force_scroll_to_bottom and hasattr(self.driver, "execute_script"):
            try:
                self.driver.execute_script("mobile: scroll", {"direction": "down"})
                time.sleep(0.8)
            except Exception:
                pass
    def _swipe_up_page(self) -> None:
        """Perform a controlled physical swipe up (content moves down, back toward top of page)."""
        try:
            size = self.driver.get_window_size()
            start_x = size["width"] // 2
            start_y = int(size["height"] * 0.30)
            end_y = int(size["height"] * 0.75)
            self.driver.swipe(start_x, start_y, start_x, end_y, duration=450)
            time.sleep(1.0)
        except Exception as e:
            self._logger.warning(f"Coordinate swipe up failed ({e}), trying mobile: swipe fallback...")
            try:
                self.driver.execute_script("mobile: swipe", {"direction": "down"})
                time.sleep(1.0)
            except Exception:
                pass
    def close_device_settings_page(self) -> bool:
        """Close the 'Device settings' screen (top-left 'X' / 'Close' / 'Back') to return to Camera Live View."""
        self._logger.info("Closing 'Device settings' page to reload fresh settings...")
        close_btn = (
                self._devset_find_first(self.DEVICE_SETTINGS_CLOSE_LOCATORS, require_displayed=True)
                or self._devset_find_first(self.DEVICE_SETTINGS_CLOSE_LOCATORS, require_displayed=False)
        )
        if close_btn and self._devset_tap_element(close_btn, "'Close / Back' button on Device Settings"):
            time.sleep(1.5)
            return True
        if hasattr(self.driver, "execute_script"):
            try:
                self._logger.info("Close button locator not matched; coordinate-tapping top-left (28, 56)...")
                self.driver.execute_script("mobile: tap", {"x": 28, "y": 56})
                time.sleep(1.5)
                return True
            except Exception as tap_err:
                self._logger.warning(f"Top-left coordinate tap failed: {tap_err}")
        return False
    def _confirm_secondary_remove_dialog(
            self,
            timeout: float = 6.0,
            locators: Optional[List[Tuple[AppiumBy, str]]] = None,
            exclude_rect: Optional[Dict[str, int]] = None,
    ) -> Optional[str]:
        """Wait for and click the secondary confirmation 'Remove' / 'Unlink all' button.
        Returns:
            Optional[str]: The clicked button label if confirmed, or None if timed out.
        """
        active_locators = locators or self.CONFIRM_REMOVE_LOCATORS
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self._devset_no_implicit_wait():
                for by, val in active_locators:
                    try:
                        elems = self.driver.find_elements(by, val)
                        # Iterate in reverse so topmost modal/alert buttons take precedence over background page buttons.
                        for elem in reversed(elems):
                            if not elem.is_displayed():
                                continue
                            if exclude_rect is not None:
                                try:
                                    if elem.rect == exclude_rect:
                                        continue
                                except Exception:
                                    pass
                            btn_label = self._devset_elem_label(elem, "Remove")
                            if self._devset_tap_element(elem, f"confirmation '{btn_label}' button"):
                                self._logger.info(f"Clicked confirmation '{btn_label}' button.")
                                return btn_label
                    except Exception:
                        pass
            time.sleep(0.5)
        return None
    def _tap_and_confirm_remove_btn(self, remove_btn: WebElement, swipe_desc: str) -> bool:
        """Click the located 'Remove device' / 'Unlink all' element and confirm the modal alert."""
        btn_label = self._devset_elem_label(remove_btn, "Remove device")
        btn_rect = None
        if btn_label.lower() == "unlink all":
            try:
                btn_rect = remove_btn.rect
            except Exception:
                btn_rect = None
        self._logger.info(f"'{btn_label}' button found ({swipe_desc})! Clicking...")
        self._devset_tap_element(remove_btn, f"'{btn_label}' button")
        self._logger.info("Waiting for secondary 'Remove' / 'Unlink all' confirmation dialog...")
        confirmed_label = self._confirm_secondary_remove_dialog(
            timeout=6.0, exclude_rect=btn_rect
        )
        if confirmed_label:
            self._logger.info(f"Successfully confirmed device removal via '{confirmed_label}'.")
            if confirmed_label.lower() != "unlink all":
                # If the first confirmation was 'Remove', check briefly in case a follow-up 'Unlink all' dialog appears.
                time.sleep(1.5)
                followup = self._confirm_secondary_remove_dialog(
                    timeout=2.0, locators=self.UNLINK_ALL_CONFIRM_LOCATORS
                )
                if followup:
                    self._logger.info(f"Confirmed follow-up '{followup}' dialog.")
                    time.sleep(5.0)
                else:
                    time.sleep(1.5)
            else:
                time.sleep(5)
            return True
        self._logger.warning("Confirmation 'Remove' / 'Unlink all' dialog button did not appear within 6s, proceeding...")
        return True
    def click_remove_device_btn(self, max_scrolls: int = 8) -> bool:
        """Quickly swipe down the Device Settings page to locate and click 'Remove device' or 'Unlink all' button.
        Args:
            max_scrolls (int): Maximum swipes to reach bottom. Defaults to 8.
        Returns:
            bool: True if clicked and confirmed successfully.
        """
        self._logger.info("Locating 'Remove device' / 'Unlink all' button on Device Settings page...")
        time.sleep(1.0)
        prev_delete_history_y: Optional[int] = None
        for scroll_idx in range(max_scrolls):
            remove_btn = self._get_visible_remove_btn()
            if remove_btn:
                return self._tap_and_confirm_remove_btn(remove_btn, f"after {scroll_idx} swipes")
            cur_delete_history_y = self._get_delete_video_history_y()
            # If 'Delete video history' is already on screen (e.g. near the bottom edge when 'Rotate image 180°'
            # pushes 'Remove device' below the fold) and a standard swipe did not move it up, also trigger
            # native 'mobile: scroll' down so the collection view is guaranteed to reach the very bottom.
            force_bottom = (
                    cur_delete_history_y is not None
                    and prev_delete_history_y is not None
                    and abs(cur_delete_history_y - prev_delete_history_y) < 10
            )
            prev_delete_history_y = cur_delete_history_y
            self._logger.info(
                f"'Remove device' / 'Unlink all' not visible yet. Swiping ({scroll_idx + 1}/{max_scrolls})..."
            )
            self._swipe_down_page(force_scroll_to_bottom=force_bottom)
        # Final check at bottom after all downward swipes
        remove_btn = self._get_visible_remove_btn()
        if remove_btn:
            return self._tap_and_confirm_remove_btn(remove_btn, "at bottom of page")
        raise PageNotPresentException(
            locator=self.REMOVE_DEVICE_LOCATORS[0],
            page_name=self.__class__.__name__,
            message=f"Failed to find 'Remove device' or 'Unlink all' button after {max_scrolls} swipes on Device Settings page."
        )
    def get_device_information(self) -> Dict[str, str]:
        """Navigate into Device Information page, extract technical metadata, resolve mDNS, and return.
        Returns:
            Dict[str, str]: Dictionary containing device_id, serial_number, software_version, device_ip,
                            mdns_hostname, mdns_service_name, mdns_port, mdns_status
        """
        self._logger.info("Locating and clicking 'Device information'...")
        device_details = {
            "device_id": "UNKNOWN",
            "serial_number": "UNKNOWN",
            "software_version": "UNKNOWN",
            "device_ip": "UNKNOWN",
            "mdns_hostname": "UNKNOWN",
            "mdns_service_name": "UNKNOWN",
            "mdns_port": "UNKNOWN",
            "mdns_status": "UNKNOWN",
            "mdns_txt": "N/A"
        }
        # Clear any previous iteration's cached tech info first so a failed read never leaks stale data.
        self.device_tech_info = device_details
        if hasattr(self, "driver") and self.driver:
            self.driver.device_tech_info = device_details
        dev_info_btn = None
        for _ in range(4):
            # In GHA on some iOS versions, the inner StaticText has visible=false while the parent Cell
            # is visible; accept either a displayed match or any present match on the current screen.
            dev_info_btn = (
                    self._devset_find_first(self.DEVICE_INFO_ENTRY_LOCATORS, require_displayed=True)
                    or self._devset_find_first(self.DEVICE_INFO_ENTRY_LOCATORS, require_displayed=False)
            )
            if dev_info_btn:
                break
            self._swipe_down_page()
        if not dev_info_btn:
            self._logger.warning("Could not find 'Device information' entry on Device Settings page.")
            return device_details
        if not self._devset_tap_element(dev_info_btn, "'Device information' entry"):
            return device_details
        entered_info_page = False
        try:
            entered_info_page = self._devset_wait_for_device_info_page(timeout=8.0)
            if not entered_info_page:
                retry_entry = (
                        self._devset_find_first(self.DEVICE_INFO_ENTRY_LOCATORS, require_displayed=True)
                        or self._devset_find_first(self.DEVICE_INFO_ENTRY_LOCATORS, require_displayed=False)
                )
                if retry_entry:
                    self._logger.info("Retrying tap on 'Device information' entry...")
                    self._devset_tap_element(retry_entry, "'Device information' entry (retry)")
                    entered_info_page = self._devset_wait_for_device_info_page(timeout=6.0)
            if not entered_info_page:
                self._logger.warning("Timed out waiting to enter 'Device information' page.")
                return device_details
            self._logger.info("Entered 'Device information' page. Extracting technical info...")
            raw_text = self._devset_read_tech_text(timeout=5.0)
            if not raw_text:
                self._swipe_down_page()
                raw_text = self._devset_read_tech_text(timeout=3.0)
            if raw_text:
                self._logger.info(f"Raw Technical Info Text: {raw_text}")
                if m_dev := re.search(r"Device ID:\s*([A-Za-z0-9]+)", raw_text):
                    device_details["device_id"] = m_dev.group(1).strip()
                if m_sn := re.search(r"Serial no\.:\s*([A-Za-z0-9]+)", raw_text):
                    device_details["serial_number"] = m_sn.group(1).strip()
                if m_sw := re.search(
                        r"Software version:\s*([^\n\r]+?)(?=\s+(?:Updated:|IP:|Last contact:)|[\r\n]|$)",
                        raw_text,
                ):
                    device_details["software_version"] = m_sw.group(1).strip()
                if m_ip := re.search(r"\bIP:\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", raw_text):
                    device_details["device_ip"] = m_ip.group(1).strip()
            else:
                self._logger.warning("Could not locate 'Device ID:' text on 'Device information' page.")
            target_ip = device_details.get("device_ip", "")
            if target_ip and target_ip != "UNKNOWN":
                mdns_info = MDNSUtils.resolve_mdns_by_ip(target_ip=target_ip, timeout=3.5)
                device_details.update(mdns_info)
            else:
                device_details["mdns_status"] = "NO_IP"
            self._logger.info(f"Extracted Device & mDNS Information: {device_details}")
            self.device_tech_info = device_details
            if hasattr(self, "driver") and self.driver:
                self.driver.device_tech_info = device_details
        except Exception as e:
            self._logger.error(f"Error during Device information extraction: {e}")
        finally:
            if entered_info_page or self._devset_is_on_device_info_page():
                self._logger.info("Clicking '< Back' button to return to Device Settings...")
                self._devset_navigate_back_from_device_info()
        return device_details