"""Page object for handling the Device Settings page and scrolling to remove device on iOS."""
import re
import time
from typing import Optional, Dict
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

    def get_device_information(self) -> Dict[str, str]:
        """Navigate into the Device Information page, extract technical metadata, and return to Device Settings.
        Returns:
            Dict[str, str]: Dictionary containing device_id, serial_number, software_version, and camera_ip.
        """


        self._logger.info("Locating and clicking 'Device information'...")
        device_details = {
            "device_id": "UNKNOWN",
            "serial_number": "UNKNOWN",
            "software_version": "UNKNOWN",
            "device_ip": "UNKNOWN"
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
            self._fast_swipe_down()
            time.sleep(0.3)
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
            self._logger.info(f"Extracted Device Information: {device_details}")
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