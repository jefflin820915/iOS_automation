"""Page object for handling the Device Settings page, mDNS discovery, and removing device on iOS."""
import re
import time
from typing import Optional, Dict, List, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    StaleElementReferenceException
)
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
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

    def _get_visible_remove_btn(self) -> Optional[WebElement]:
        """Find visible and hittable 'Remove device' button with multi-strategy locators."""
        try:
            window_size = self.driver.get_window_size()
            screen_height = window_size["height"]
        except Exception:
            screen_height = 9999
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
            for by, val in self.CONFIRM_REMOVE_LOCATORS:
                try:
                    elems = self.driver.find_elements(by, val)
                    for elem in elems:
                        if elem.is_displayed():
                            try:
                                elem.click()
                                self._logger.info("Clicked confirmation 'Remove' button.")
                                return True
                            except Exception:
                                rect = elem.rect
                                tap_x = int(rect["x"] + rect["width"] / 2)
                                tap_y = int(rect["y"] + rect["height"] / 2)
                                self.driver.execute_script("mobile: tap", {"x": tap_x, "y": tap_y})
                                self._logger.info(f"Coordinate-tapped confirmation 'Remove' button at ({tap_x}, {tap_y}).")
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
                click_success = False
                try:
                    remove_btn.click()
                    click_success = True
                except (WebDriverException, StaleElementReferenceException) as err:
                    self._logger.warning(f"Standard click failed: {err}. Trying coordinate tap...")
                if not click_success:
                    try:
                        rect = remove_btn.rect
                        tap_x = int(rect["x"] + rect["width"] / 2)
                        tap_y = int(rect["y"] + rect["height"] / 2)
                        self.driver.execute_script("mobile: tap", {"x": tap_x, "y": tap_y})
                        self._logger.info(f"Successfully coordinate-tapped 'Remove device' at ({tap_x}, {tap_y}).")
                        click_success = True
                    except Exception as tap_err:
                        self._logger.error(f"Coordinate tap failed: {tap_err}")
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
        dev_info_btn = None
        for _ in range(3):
            elems = self.driver.find_elements(
                AppiumBy.XPATH,
                '//XCUIElementTypeCell[.//XCUIElementTypeStaticText[@name="Device information"]] | '
                '//XCUIElementTypeStaticText[@name="Device information"]'
            )
            if elems and elems[0].is_displayed():
                dev_info_btn = elems[0]
                break
            self._swipe_down_page()
        if not dev_info_btn:
            self._logger.warning("Could not find 'Device information' entry on Device Settings page.")
            return device_details
        try:
            dev_info_btn.click()
        except WebDriverException:
            self.driver.execute_script("mobile: tap", {"elementId": dev_info_btn.id})
        try:
            back_btn = WebDriverWait(self.driver, 5.0).until(
                EC.element_to_be_clickable((AppiumBy.XPATH, '//XCUIElementTypeButton[@name="BackButton"]'))
            )
            self._logger.info("Entered 'Device information' page. Extracting technical info...")
            time.sleep(1.0)
            raw_text = ""
            tech_elems = self.driver.find_elements(
                AppiumBy.XPATH,
                '//XCUIElementTypeStaticText[contains(@value, "Device ID:") or contains(@label, "Device ID:")] | '
                '//XCUIElementTypeTextView[contains(@value, "Device ID:")]'
            )
            if tech_elems:
                raw_text = tech_elems[0].get_attribute("value") or tech_elems[0].get_attribute("label") or tech_elems[0].text
            else:
                all_texts = [e.text for e in self.driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText")]
                for t in all_texts:
                    if "Device ID:" in t:
                        raw_text = t
                        break
            if raw_text:
                self._logger.info(f"Raw Technical Info Text: {raw_text}")
                if m_dev := re.search(r"Device ID:\s*([A-Za-z0-9]+)", raw_text):
                    device_details["device_id"] = m_dev.group(1).strip()
                if m_sn := re.search(r"Serial no\.:\s*([A-Za-z0-9]+)", raw_text):
                    device_details["serial_number"] = m_sn.group(1).strip()
                if m_sw := re.search(r"Software version:\s*([^\n\r]+?)(?:\s+Updated:|$)", raw_text):
                    device_details["software_version"] = m_sw.group(1).strip()
                if m_ip := re.search(r"\bIP:\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", raw_text):
                    device_details["device_ip"] = m_ip.group(1).strip()
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
            self._logger.info("Clicking '< Back' button to return to Device Settings...")
            back_btn.click()
            time.sleep(1.5)
        except Exception as e:
            self._logger.error(f"Error during Device information extraction: {e}")
            try:
                self.driver.find_element(AppiumBy.XPATH, '//XCUIElementTypeButton[@name="BackButton"]').click()
            except Exception:
                pass
        return device_details