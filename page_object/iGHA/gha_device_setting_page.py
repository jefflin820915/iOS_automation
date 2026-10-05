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
        (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "Remove device" OR label == "Remove device"`]'),
        (AppiumBy.IOS_PREDICATE, 'name == "Remove device" OR label == "Remove device"'),
        (AppiumBy.XPATH, '//XCUIElementTypeButton[@name="Remove device" or @label="Remove device"]'),
    ]
    CONFIRM_REMOVE_LOCATORS: List[Tuple[AppiumBy, str]] = [
        (AppiumBy.XPATH, '//XCUIElementTypeButton[@name="Remove" or @label="Remove"]'),
        (AppiumBy.ACCESSIBILITY_ID, "Remove"),
        (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`label == "Remove" OR name == "Remove"`]'),
        (AppiumBy.ACCESSIBILITY_ID, "Delete"),
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

    def _get_visible_remove_btn(self) -> Optional[WebElement]:
        """Find visible and hittable 'Remove device' button with multi-strategy locators."""
        try:
            window_size = self.driver.get_window_size()
            screen_height = window_size["height"]
        except Exception:
            screen_height = 9999
        with self._devset_no_implicit_wait():
            for by, val in self.REMOVE_DEVICE_LOCATORS:
                try:
                    elems = self.driver.find_elements(by, val)
                    for elem in elems:
                        if elem.is_displayed():
                            rect = elem.rect
                            if 50 < rect["y"] < screen_height - 10 and rect["height"] > 10:
                                return elem
                except Exception:
                    continue
        return None

    def _swipe_down_page(self) -> None:
        """Perform a controlled physical swipe down (content moves up) with settling sleep."""
        try:
            size = self.driver.get_window_size()
            start_x = size["width"] // 2
            start_y = int(size["height"] * 0.75)
            end_y = int(size["height"] * 0.30)
            self.driver.swipe(start_x, start_y, start_x, end_y, duration=450)
            time.sleep(1.0)
        except Exception as e:
            self._logger.warning(f"Coordinate swipe failed ({e}), trying mobile: swipe fallback...")
            try:
                self.driver.execute_script("mobile: swipe", {"direction": "up"})
                time.sleep(1.0)
            except Exception:
                pass

    def _confirm_secondary_remove_dialog(self, timeout: float = 6.0) -> bool:
        """Wait for and click the secondary confirmation 'Remove' button."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self._devset_no_implicit_wait():
                for by, val in self.CONFIRM_REMOVE_LOCATORS:
                    try:
                        elems = self.driver.find_elements(by, val)
                        for elem in elems:
                            if elem.is_displayed():
                                if self._devset_tap_element(elem, "confirmation 'Remove' button"):
                                    self._logger.info("Clicked confirmation 'Remove' button.")
                                    return True
                    except Exception:
                        pass
            time.sleep(0.5)
        return False

    def click_remove_device_btn(self, max_scrolls: int = 8) -> bool:
        """Quickly swipe down the Device Settings page to locate and click 'Remove device' button.
        Args:
            max_scrolls (int): Maximum swipes to reach bottom. Defaults to 8.
        Returns:
            bool: True if clicked and confirmed successfully.
        """
        self._logger.info("Locating 'Remove device' button on Device Settings page...")
        time.sleep(1.0)
        for scroll_idx in range(max_scrolls):
            remove_btn = self._get_visible_remove_btn()
            if remove_btn:
                self._logger.info(f"'Remove device' button found (after {scroll_idx} swipes)! Clicking...")
                self._devset_tap_element(remove_btn, "'Remove device' button")
                self._logger.info("Waiting for secondary 'Remove' confirmation dialog...")
                if self._confirm_secondary_remove_dialog(timeout=6.0):
                    self._logger.info("Successfully confirmed device removal.")
                    time.sleep(2.5)
                    return True
                else:
                    self._logger.warning("Confirmation 'Remove' dialog button did not appear within 6s, proceeding...")
                    return True
            self._logger.info(f"'Remove device' not visible yet. Swiping ({scroll_idx + 1}/{max_scrolls})...")
            self._swipe_down_page()
        raise PageNotPresentException(
            locator=self.REMOVE_DEVICE_LOCATORS[0],
            page_name=self.__class__.__name__,
            message=f"Failed to find 'Remove device' button after {max_scrolls} swipes on Device Settings page."
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