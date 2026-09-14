"""Page object method for verifying device existence on the Devices page in iOS."""
import time
from typing import Optional, List, Dict, Any, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException, StaleElementReferenceException
from common.base_page import BasePage, PageNotPresentException
from utils import logging_utils


class GHASetUpDevicePage(BasePage):
    """Class for handling Google Home device setup page on iOS."""

    def _get_all_visible_device_items(self) -> List[Dict[str, Any]]:
        """Retrieve all currently VISIBLE device cards on screen with title, subtitle, and element."""
        visible_items: List[Dict[str, Any]] = []
        button_predicate = (
            'type == "XCUIElementTypeButton" AND '
            'name == "image-title-subtitle" AND '
            'visible == 1'
        )
        try:
            buttons = self.driver.find_elements(AppiumBy.IOS_PREDICATE, button_predicate)
            for btn in buttons:
                try:
                    if not btn.is_displayed():
                        continue
                    rect = btn.rect
                    if rect["y"] < 0 or rect["height"] <= 0:
                        continue
                    raw_label = btn.get_attribute("label") or btn.get_attribute("value") or ""
                    raw_label = raw_label.strip()
                    if not raw_label:
                        continue
                    if ", " in raw_label:
                        title, subtitle = raw_label.rsplit(", ", 1)
                    elif "," in raw_label:
                        title, subtitle = raw_label.rsplit(",", 1)
                    else:
                        title, subtitle = raw_label, ""
                    title = title.strip()
                    subtitle = subtitle.strip()
                    display_name = f"{title} ({subtitle})" if subtitle else title
                    visible_items.append({
                        "title": title,
                        "subtitle": subtitle,
                        "display_name": display_name,
                        "element": btn,
                    })
                except (StaleElementReferenceException, WebDriverException):
                    continue
        except WebDriverException as e:
            self._logger.debug(f"Error finding device buttons via predicate: {e}")
        if not visible_items:
            try:
                title_elements = self.driver.find_elements(
                    AppiumBy.IOS_PREDICATE, 'name == "title" AND visible == 1'
                )
                subtitle_elements = self.driver.find_elements(
                    AppiumBy.IOS_PREDICATE, 'name == "subtitle" AND visible == 1'
                )
                for t_elem in title_elements:
                    try:
                        if not t_elem.is_displayed():
                            continue
                        t_text = (t_elem.get_attribute("value") or t_elem.get_attribute("label") or t_elem.text or "").strip()
                        if not t_text:
                            continue
                        t_y = t_elem.rect["y"]
                        matching_sub = ""
                        for s_elem in subtitle_elements:
                            s_y = s_elem.rect["y"]
                            if 0 <= (s_y - t_y) <= 60:
                                matching_sub = (s_elem.get_attribute("value") or s_elem.get_attribute("label") or s_elem.text or "").strip()
                                break
                        display_name = f"{t_text} ({matching_sub})" if matching_sub else t_text
                        visible_items.append({
                            "title": t_text,
                            "subtitle": matching_sub,
                            "display_name": display_name,
                            "element": t_elem,
                        })
                    except (StaleElementReferenceException, WebDriverException):
                        continue
            except WebDriverException as e:
                self._logger.debug(f"Fallback title/subtitle query error: {e}")
        return visible_items

    def _is_target_device_match(self, target_name: str, item: Dict[str, Any]) -> bool:
        """Check if a device item matches the target device name/pairing code."""
        target = target_name.strip().lower()
        title = item["title"].strip().lower()
        subtitle = item["subtitle"].strip().lower()
        display = item["display_name"].strip().lower()
        if target == title or target == subtitle or target == display:
            return True
        if target in title or title in target:
            return True
        if subtitle and (target in subtitle or subtitle in target):
            return True
        if target in display:
            return True
        return False

    def _is_at_top_of_page(self) -> bool:
        """Check if currently at the very top of the setup nearby devices page."""
        try:
            headers = self.driver.find_elements(
                AppiumBy.IOS_PREDICATE,
                'name == "header_rootView" OR label CONTAINS "Set up nearby devices"'
            )
            return any(h.is_displayed() for h in headers)
        except Exception:
            return False

    def _safe_click_target_device(self, target_name: str) -> bool:
        """Safely locate, bounds-check, and click the target device card.
        Handles list shifting, devices pushed to the bottom edge, and race conditions.
        Returns:
            bool: True if clicked successfully, False if not visible or shifted out.
        """
        win_size = self.driver.get_window_size()
        win_h = win_size.get("height", 800)
        for attempt in range(3):
            items = self._get_all_visible_device_items()
            target_item = None
            for item in items:
                if self._is_target_device_match(target_name, item):
                    target_item = item
                    break
            if not target_item:
                return False
            elem = target_item["element"]
            try:
                rect = elem.rect
                if (rect["y"] + rect["height"]) > (win_h - 100):
                    self._logger.info(
                        f"Target '{target_item['display_name']}' pushed to bottom edge (y={rect['y']}). "
                        f"Swiping up slightly to pull it into safe view..."
                    )
                    self.driver.execute_script("mobile: swipe", {"direction": "up"})
                    time.sleep(1.0)
                    continue
                if rect["y"] < 80:
                    self._logger.info(
                        f"Target '{target_item['display_name']}' clipped at top. Swiping down..."
                    )
                    self.driver.execute_script("mobile: swipe", {"direction": "down"})
                    time.sleep(1.0)
                    continue
                current_label = elem.get_attribute("label") or elem.get_attribute("value") or ""
                if target_item["title"].lower() not in current_label.lower():
                    self._logger.warning(
                        f"List shifted! Element is now '{current_label}' instead of target. Re-locating..."
                    )
                    time.sleep(0.5)
                    continue
                self._logger.info(f"Target device '{target_item['display_name']}' is safe in viewport! Clicking now...")
                try:
                    elem.click()
                    self._logger.info("Successfully clicked device card.")
                    return True
                except WebDriverException:
                    self.driver.execute_script("mobile: tap", {"elementId": elem.id})
                    self._logger.info("mobile: tap succeeded.")
                    return True
            except (StaleElementReferenceException, WebDriverException) as e:
                self._logger.warning(f"List re-rendered during click ({e.__class__.__name__}). Retrying ({attempt + 1}/3)...")
                time.sleep(0.8)
        return False

    def is_device_exist_in_setup_device_page(
            self, device_name: str, max_scrolls: int = 15, initial_wait_seconds: int = 6
    ) -> bool:
        """Scan nearby devices, log discovered device list (title + subtitle), and click the target device.
        Handles devices that take longer to be discovered or show up at the top after scrolling down.
        """
        self._logger.info(f"Start scanning nearby devices for target: '{device_name}'...")
        time.sleep(5)
        discovered_device_names: List[str] = []
        self._logger.info(
            f"Phase 1: Waiting at top for up to {initial_wait_seconds}s for nearby device discovery to populate..."
        )
        poll_start = time.time()
        while time.time() - poll_start < initial_wait_seconds:
            items = self._get_all_visible_device_items()
            target_found = False
            for item in items:
                name = item["display_name"]
                if name not in discovered_device_names:
                    discovered_device_names.append(name)
                if self._is_target_device_match(device_name, item):
                    target_found = True
            self._logger.info(f"Discovered Device Name List ({len(discovered_device_names)}): {discovered_device_names}")
            if target_found:
                self._logger.info(f"Target device '{device_name}' detected! Attempting safe click...")
                if self._safe_click_target_device(device_name):
                    return True
                else:
                    self._logger.info("Target was pushed off-screen by newly discovered devices. Proceeding to Phase 2 scroll...")
                    break
            time.sleep(2)
        self._logger.info("Phase 2: Scanning downwards through the device list...")
        consecutive_no_new_devices = 0
        scroll_down_count = 0
        for scroll_idx in range(max_scrolls):
            time.sleep(1.5)
            items = self._get_all_visible_device_items()
            new_devices_found = False
            target_found = False
            for item in items:
                name = item["display_name"]
                if name not in discovered_device_names:
                    discovered_device_names.append(name)
                    new_devices_found = True
                if self._is_target_device_match(device_name, item):
                    target_found = True
            self._logger.info(f"Discovered Device Name List ({len(discovered_device_names)}): {discovered_device_names}")
            if target_found:
                self._logger.info(f"Target device '{device_name}' found during scroll! Attempting safe click...")
                if self._safe_click_target_device(device_name):
                    return True
            if new_devices_found:
                consecutive_no_new_devices = 0
            else:
                consecutive_no_new_devices += 1
            if consecutive_no_new_devices >= 2:
                self._logger.info("Reached bottom of nearby device list in downward scan.")
                break
            scroll_down_count += 1
            self._logger.info(
                f"Device '{device_name}' not yet in safe view. Scrolling down ({scroll_idx + 1}/{max_scrolls})..."
            )
            try:
                self.driver.execute_script("mobile: swipe", {"direction": "up"})
            except WebDriverException as e:
                self._logger.warning(f"mobile: swipe down failed: {e}")
                break

        self._logger.info(
            "Phase 3: Target not found downwards. Scrolling BACK UP to the top in case it appeared late..."
        )
        for scroll_idx in range(scroll_down_count + 3):
            time.sleep(1.5)
            items = self._get_all_visible_device_items()
            target_found = False
            for item in items:
                name = item["display_name"]
                if name not in discovered_device_names:
                    discovered_device_names.append(name)
                if self._is_target_device_match(device_name, item):
                    target_found = True
            if target_found:
                self._logger.info(f"Discovered Device Name List ({len(discovered_device_names)}): {discovered_device_names}")
                if self._safe_click_target_device(device_name):
                    return True
            if self._is_at_top_of_page():
                self._logger.info("Successfully returned to the top of the device list.")
                break
            self._logger.info(f"Scrolling up towards top ({scroll_idx + 1})...")
            try:
                self.driver.execute_script("mobile: swipe", {"direction": "down"})
            except WebDriverException as e:
                self._logger.warning(f"mobile: swipe up failed: {e}")
                break
        time.sleep(2)
        final_items = self._get_all_visible_device_items()
        for item in final_items:
            name = item["display_name"]
            if name not in discovered_device_names:
                discovered_device_names.append(name)
            if self._is_target_device_match(device_name, item):
                if self._safe_click_target_device(device_name):
                    return True
        self._logger.info(f"Final Discovered Device Name List ({len(discovered_device_names)}): {discovered_device_names}")
        self._logger.error(f"Could not find visible device '{device_name}' after full bidirectional scan.")
        return False