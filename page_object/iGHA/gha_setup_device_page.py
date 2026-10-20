"""Page object method for verifying device existence on the Set up nearby devices page in iOS."""
import time
from typing import Optional, List, Dict, Any, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException, StaleElementReferenceException
from common.base_page import BasePage, PageNotPresentException
from utils import logging_utils


class GHASetUpDevicePage(BasePage):
    """Class for handling Google Home device setup ('Set up nearby devices') page on iOS."""
    EXPECTED_DEVICE_IDENTIFIERS: Dict[str, str] = {
        "Onn Wired Indoor Camera": "5502:4233:1658",
        "Ref2 Battery Camera": "4738:21505:2329",
        "HD Wired Indoor Camera": "4738:20482:2443",
    }

    def _get_expected_identifier(self, target_name: str) -> Optional[str]:
        """Return the hardcoded device identifier (subtitle) for known devices, or None."""
        target_lower = target_name.strip().lower()
        for dev_name, identifier in self.EXPECTED_DEVICE_IDENTIFIERS.items():
            if target_lower == dev_name.strip().lower():
                return identifier.strip().lower()
        return None

    def _get_window_size_safe(self) -> Tuple[int, int]:
        """Return (width, height) of the screen with safe defaults."""
        try:
            win_size = self.driver.get_window_size()
            return int(win_size.get("width", 390)), int(win_size.get("height", 844))
        except Exception:
            return 390, 844

    def _get_footer_top_y(self) -> int:
        """Return the top y-coordinate of the sticky 'Set up a different device' footer container.
        On iOS GHA, the white footer container sits at roughly the bottom 22% of the screen (~y=650 on 844pt),
        and any tap at y >= footer_top_y risks hitting the 'Set up a different device' button (e.g. y=719).
        """
        _, win_h = self._get_window_size_safe()
        default_footer_top = int(win_h * 0.77)  # ~650 on 844pt screen, ~625 on 812pt screen
        try:
            footer_btns = self.driver.find_elements(
                AppiumBy.IOS_PREDICATE,
                'type == "XCUIElementTypeButton" AND '
                '(label CONTAINS[c] "Set up a different device" OR name CONTAINS[c] "Set up a different device" '
                'OR name == "Footer_actionBar")',
            )
            for btn in footer_btns:
                try:
                    r = btn.rect
                    btn_y = int(r.get("y", 0))
                    if btn_y > win_h * 0.5:
                        # The white footer panel extends ~25pt above the button's top edge
                        return min(default_footer_top, btn_y - 25)
                except Exception:
                    continue
        except Exception:
            pass
        return default_footer_top

    def _get_all_visible_device_items(self) -> List[Dict[str, Any]]:
        """Retrieve all currently VISIBLE device cards on screen with title, subtitle, and element.
        Includes cards near the bottom of the scroll view whose top edge is above the
        'Set up a different device' footer even if XCUITest reports visible=false due to partial clipping.
        """
        visible_items: List[Dict[str, Any]] = []
        _, win_h = self._get_window_size_safe()
        footer_cutoff_y = int(win_h * 0.80)
        button_predicate = (
            'type == "XCUIElementTypeButton" AND '
            'name == "image-title-subtitle"'
        )
        try:
            buttons = self.driver.find_elements(AppiumBy.IOS_PREDICATE, button_predicate)
            for btn in buttons:
                try:
                    rect = btn.rect
                    if rect["height"] <= 0 or rect["y"] < 0 or rect["y"] >= win_h:
                        continue
                    is_vis = False
                    try:
                        is_vis = bool(btn.is_displayed())
                    except Exception:
                        is_vis = False
                    # Accept the card if XCUITest marks it displayed OR if its top is clearly inside
                    # the scrollable viewport above the 'Set up a different device' footer.
                    if not is_vis and not (
                            0 <= rect["y"] < footer_cutoff_y and (rect["y"] + rect["height"]) > 60):
                        continue
                    raw_label = btn.get_attribute("label") or btn.get_attribute(
                        "value") or btn.text or ""
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
                        "rect": dict(rect),
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
                        t_rect = t_elem.rect
                        if t_rect["y"] < 0 or t_rect["y"] >= win_h:
                            continue
                        t_text = (t_elem.get_attribute("value") or t_elem.get_attribute(
                            "label") or t_elem.text or "").strip()
                        if not t_text:
                            continue
                        t_y = t_rect["y"]
                        matching_sub = ""
                        for s_elem in subtitle_elements:
                            s_y = s_elem.rect["y"]
                            if 0 <= (s_y - t_y) <= 60:
                                matching_sub = (
                                            s_elem.get_attribute("value") or s_elem.get_attribute(
                                        "label") or s_elem.text or "").strip()
                                break
                        display_name = f"{t_text} ({matching_sub})" if matching_sub else t_text
                        visible_items.append({
                            "title": t_text,
                            "subtitle": matching_sub,
                            "display_name": display_name,
                            "element": t_elem,
                            "rect": dict(t_rect),
                        })
                    except (StaleElementReferenceException, WebDriverException):
                        continue
            except WebDriverException as e:
                self._logger.debug(f"Fallback title/subtitle query error: {e}")
        return visible_items

    @staticmethod
    def _get_viewport_signature(items: List[Dict[str, Any]]) -> Tuple[Tuple[str, int], ...]:
        """Build a geometry signature of visible cards (display_name + quantized y) to detect scroll movement."""
        sig: List[Tuple[str, int]] = []
        for item in items:
            rect = item.get("rect") or {}
            y_bucket = int(round(float(rect.get("y", 0)) / 15.0))
            sig.append((item.get("display_name", ""), y_bucket))
        return tuple(sig)

    def _is_target_device_match(self, target_name: str, item: Dict[str, Any]) -> bool:
        """Check if a device item matches the target device name and its expected identifier."""
        target = target_name.strip().lower()
        title = item["title"].strip().lower()
        subtitle = item["subtitle"].strip().lower()
        display = item["display_name"].strip().lower()
        expected_id = self._get_expected_identifier(target_name)
        if expected_id:
            name_matched = (target == title) or (target in title) or (title in target)
            id_matched = (expected_id == subtitle) or (expected_id in subtitle) or (
                        expected_id in display)
            return name_matched and id_matched
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

    def _nudge_scroll_vertical(self, start_y: int, end_y: int) -> None:
        """Perform a vertical drag inside the scrollable area (above the footer) to bring a card into safe view."""
        win_w, _ = self._get_window_size_safe()
        cx = win_w // 2
        try:
            self.driver.swipe(cx, start_y, cx, end_y, duration=500)
        except Exception:
            direction = "up" if start_y > end_y else "down"
            try:
                self.driver.execute_script("mobile: swipe", {"direction": direction})
            except Exception:
                pass
        time.sleep(1.0)

    def _scroll_down_page(self, deep: bool = False) -> None:
        """Scroll down the 'Set up nearby devices' list starting well above the 'Set up a different device' footer."""
        win_w, win_h = self._get_window_size_safe()
        cx = win_w // 2
        # Start at 62% of screen height (~520 on 844pt) so the finger NEVER starts on the 'Set up a different device' footer
        start_y = int(win_h * 0.62)
        end_y = int(win_h * (0.18 if deep else 0.24))
        try:
            self.driver.swipe(cx, start_y, cx, end_y, duration=450)
        except Exception as swipe_err:
            self._logger.debug(
                f"Coordinate swipe down failed ({swipe_err}), falling back to mobile: swipe...")
            try:
                self.driver.execute_script("mobile: swipe", {"direction": "up"})
            except Exception as fallback_err:
                self._logger.warning(f"mobile: swipe down failed: {fallback_err}")

    def _scroll_up_page(self) -> None:
        """Scroll up towards the top of the 'Set up nearby devices' list."""
        win_w, win_h = self._get_window_size_safe()
        cx = win_w // 2
        start_y = int(win_h * 0.25)
        end_y = int(win_h * 0.65)
        try:
            self.driver.swipe(cx, start_y, cx, end_y, duration=450)
        except Exception as swipe_err:
            self._logger.debug(
                f"Coordinate swipe up failed ({swipe_err}), falling back to mobile: swipe...")
            try:
                self.driver.execute_script("mobile: swipe", {"direction": "down"})
            except Exception as fallback_err:
                self._logger.warning(f"mobile: swipe up failed: {fallback_err}")

    def _tap_card_with_fallbacks(
            self, elem: WebElement, rect: Dict[str, int], display_name: str, footer_top_y: int
    ) -> bool:
        """Click the device card element safely above the 'Set up a different device' footer.
        IMPORTANT: In XCUITest, elem.click() always taps the geometric center (cx, cy) of the element.
        If cy is near or below footer_top_y (e.g. y=608, cy=719), elem.click() will hit the
        'Set up a different device' button! In that case, we use coordinate tap clamped above footer_top_y.
        """
        safe_max_tap_y = footer_top_y - 35
        cx = int(rect["x"] + rect["width"] / 2)
        raw_cy = int(rect["y"] + rect["height"] / 2)
        safe_cy = max(int(rect["y"]) + 30, min(raw_cy, safe_max_tap_y))
        tapped = False
        if raw_cy > safe_max_tap_y:
            self._logger.info(
                f"Card '{display_name}' center (cy={raw_cy}) is too close to footer (footer_top={footer_top_y}); "
                f"using safe coordinate tap at ({cx}, {safe_cy}) instead of elem.click()..."
            )
            try:
                self.driver.execute_script("mobile: tap", {"x": cx, "y": safe_cy})
                tapped = True
            except Exception as tap_err:
                self._logger.error(f"Safe coordinate tap failed for '{display_name}': {tap_err}")
                return False
        else:
            try:
                elem.click()
                self._logger.info(
                    f"Clicked device card '{display_name}' via elem.click() at cy={raw_cy}.")
                tapped = True
            except (StaleElementReferenceException, WebDriverException) as click_err:
                self._logger.warning(
                    f"elem.click() on '{display_name}' failed ({click_err}); trying mobile: tap...")
                try:
                    self.driver.execute_script("mobile: tap", {"x": cx, "y": safe_cy})
                    self._logger.info(
                        f"Coordinate-tapped device card '{display_name}' at ({cx}, {safe_cy}).")
                    tapped = True
                except Exception as tap_err:
                    self._logger.error(f"All tap methods failed for '{display_name}': {tap_err}")
                    return False
        # If the list was still decelerating from a scroll, the first tap may have only stopped inertia.
        # Check after 1.0s if the same card is still visible on this page; if so, tap its safe coordinates.
        time.sleep(1.0)
        still_present = None
        for item in self._get_all_visible_device_items():
            if item["display_name"].strip().lower() == display_name.strip().lower():
                still_present = item
                break
        if still_present is not None:
            try:
                r2 = still_present.get("rect") or still_present["element"].rect
                cx2 = int(r2["x"] + r2["width"] / 2)
                raw_cy2 = int(r2["y"] + r2["height"] / 2)
                cy2 = max(int(r2["y"]) + 30, min(raw_cy2, safe_max_tap_y))
                self._logger.info(
                    f"Device card '{display_name}' still visible after initial click; "
                    f"sending follow-up coordinate tap at ({cx2}, {cy2})..."
                )
                self.driver.execute_script("mobile: tap", {"x": cx2, "y": cy2})
                time.sleep(0.8)
            except Exception:
                pass
        return tapped

    def _safe_click_target_device(
            self, target_name: str, initial_item: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Safely locate, bounds-check, and click the target device card.
        Guarantees that a card at the bottom of the list (e.g. y=608, cy=719) is scrolled up
        completely above the 'Set up a different device' footer before clicking so it never
        accidentally clicks 'Set up a different device'.
        Returns:
            bool: True if clicked successfully, False if not visible or shifted out.
        """
        _, win_h = self._get_window_size_safe()
        footer_top_y = self._get_footer_top_y()
        # Require card center cy to be at least 55pt above the footer container (~595 on 844pt screen)
        safe_bottom_cy = footer_top_y - 55
        for attempt in range(4):
            items = self._get_all_visible_device_items()
            target_item = None
            for item in items:
                if self._is_target_device_match(target_name, item):
                    target_item = item
                    break
            if target_item is None and attempt == 0 and initial_item is not None:
                target_item = initial_item
            if not target_item:
                self._logger.warning(
                    f"Target '{target_name}' not visible on click attempt {attempt + 1}/4. Retrying..."
                )
                time.sleep(0.6)
                continue
            elem = target_item["element"]
            try:
                rect = target_item.get("rect") or elem.rect
                cy = int(rect["y"] + rect["height"] / 2)
                card_bottom = int(rect["y"] + rect["height"])
                if (cy > safe_bottom_cy or card_bottom > footer_top_y + 15) and attempt < 3:
                    self._logger.info(
                        f"Target '{target_item['display_name']}' overlaps or is too close to 'Set up a different device' "
                        f"footer (y={rect['y']}, cy={cy}, bottom={card_bottom}, footer_top={footer_top_y}). "
                        f"Scrolling up to pull card into safe view (attempt {attempt + 1}/3)..."
                    )
                    # Start drag at 62% of screen height (well above the footer) and pull up to 24%
                    self._nudge_scroll_vertical(int(win_h * 0.62), int(win_h * 0.24))
                    continue
                if cy < 35 and attempt < 3:
                    self._logger.info(
                        f"Target '{target_item['display_name']}' clipped at top edge (y={rect['y']}, cy={cy}). "
                        f"Nudging down slightly..."
                    )
                    self._nudge_scroll_vertical(int(win_h * 0.35), int(win_h * 0.60))
                    continue
                current_label = (
                        elem.get_attribute("label") or elem.get_attribute(
                    "value") or elem.text or ""
                ).lower()
                expected_sub = target_item["subtitle"].lower()
                if current_label and (
                        target_item["title"].lower() not in current_label
                        or (
                                expected_sub and "," in current_label and expected_sub not in current_label)
                ):
                    self._logger.warning(
                        f"List shifted! Element is now '{current_label}' instead of '{target_item['display_name']}'. Re-locating..."
                    )
                    time.sleep(0.5)
                    continue
                self._logger.info(
                    f"Target device '{target_item['display_name']}' is in safe viewport "
                    f"(y={rect['y']}, cy={cy}, footer_top={footer_top_y})! Clicking now..."
                )
                if self._tap_card_with_fallbacks(elem, rect, target_item["display_name"],
                                                 footer_top_y):
                    return True
            except (StaleElementReferenceException, WebDriverException) as e:
                self._logger.warning(
                    f"List re-rendered during click ({e.__class__.__name__}). Retrying ({attempt + 1}/4)..."
                )
                time.sleep(0.8)
        return False

    def is_device_exist_in_setup_device_page(
            self, device_name: str, max_scrolls: int = 15, initial_wait_seconds: int = 6
    ) -> bool:
        """Scan nearby devices, log discovered device list (title + subtitle), and click the target device.
        Guarantees scrolling all the way to the bottom of the 'Set up nearby devices' list before
        scanning back up to the top.
        """
        expected_id = self._get_expected_identifier(device_name)
        target_desc = f"{device_name} ({expected_id})" if expected_id else device_name
        self._logger.info(f"Start scanning nearby devices for target: '{target_desc}'...")
        time.sleep(5)
        discovered_device_names: List[str] = []
        self._logger.info(
            f"Phase 1: Waiting at top for up to {initial_wait_seconds}s for nearby device discovery to populate..."
        )
        poll_start = time.time()
        last_items: List[Dict[str, Any]] = []
        ran_phase1 = False
        while time.time() - poll_start < initial_wait_seconds:
            ran_phase1 = True
            items = self._get_all_visible_device_items()
            last_items = items
            matched_item = None
            for item in items:
                name = item["display_name"]
                if name not in discovered_device_names:
                    discovered_device_names.append(name)
                if matched_item is None and self._is_target_device_match(device_name, item):
                    matched_item = item
            self._logger.info(
                f"Discovered Device Name List ({len(discovered_device_names)}): {discovered_device_names}")
            if matched_item is not None:
                self._logger.info(
                    f"Target device '{target_desc}' detected! Attempting safe click...")
                if self._safe_click_target_device(device_name, initial_item=matched_item):
                    return True
                else:
                    self._logger.info(
                        "Target was pushed off-screen by newly discovered devices. Proceeding to Phase 2 scroll...")
                    break
            time.sleep(2)
        if not ran_phase1:
            items = self._get_all_visible_device_items()
            last_items = items
            matched_item = None
            for item in items:
                name = item["display_name"]
                if name not in discovered_device_names:
                    discovered_device_names.append(name)
                if matched_item is None and self._is_target_device_match(device_name, item):
                    matched_item = item
            self._logger.info(
                f"Discovered Device Name List ({len(discovered_device_names)}): {discovered_device_names}")
            if matched_item is not None:
                self._logger.info(
                    f"Target device '{target_desc}' detected at top! Attempting safe click...")
                if self._safe_click_target_device(device_name, initial_item=matched_item):
                    return True
        self._logger.info("Phase 2: Scanning downwards through the device list...")
        prev_viewport_sig = self._get_viewport_signature(last_items)
        consecutive_no_new_devices = 0
        unchanged_viewport_count = 0
        scroll_down_count = 0
        for scroll_idx in range(max_scrolls):
            scroll_down_count += 1
            use_deep_scroll = (unchanged_viewport_count >= 1 or consecutive_no_new_devices >= 2)
            self._logger.info(
                f"Device '{target_desc}' not yet in safe view. Scrolling down ({scroll_idx + 1}/{max_scrolls})..."
            )
            self._scroll_down_page(deep=use_deep_scroll)
            time.sleep(1.5)
            items = self._get_all_visible_device_items()
            new_devices_found = False
            matched_item = None
            for item in items:
                name = item["display_name"]
                if name not in discovered_device_names:
                    discovered_device_names.append(name)
                    new_devices_found = True
                if matched_item is None and self._is_target_device_match(device_name, item):
                    matched_item = item
            self._logger.info(
                f"Discovered Device Name List ({len(discovered_device_names)}): {discovered_device_names}")
            if matched_item is not None:
                self._logger.info(
                    f"Target device '{target_desc}' found during downward scroll! Attempting safe click...")
                if self._safe_click_target_device(device_name, initial_item=matched_item):
                    return True
            curr_viewport_sig = self._get_viewport_signature(items)
            viewport_moved = bool(curr_viewport_sig) and (curr_viewport_sig != prev_viewport_sig)
            prev_viewport_sig = curr_viewport_sig
            if new_devices_found:
                consecutive_no_new_devices = 0
                unchanged_viewport_count = 0
            else:
                consecutive_no_new_devices += 1
                if viewport_moved:
                    unchanged_viewport_count = 0
                else:
                    unchanged_viewport_count += 1
            if unchanged_viewport_count >= 2 or consecutive_no_new_devices >= 4:
                self._logger.info(
                    f"Reached bottom of nearby device list in downward scan "
                    f"(unchanged_viewport={unchanged_viewport_count}, no_new_devices={consecutive_no_new_devices})."
                )
                break
        self._logger.info(
            "Phase 3: Target not found downwards. Scrolling BACK UP to the top in case it appeared late..."
        )
        for scroll_idx in range(scroll_down_count + 3):
            time.sleep(1.5)
            items = self._get_all_visible_device_items()
            matched_item = None
            for item in items:
                name = item["display_name"]
                if name not in discovered_device_names:
                    discovered_device_names.append(name)
                if matched_item is None and self._is_target_device_match(device_name, item):
                    matched_item = item
            if matched_item is not None:
                self._logger.info(
                    f"Discovered Device Name List ({len(discovered_device_names)}): {discovered_device_names}")
                self._logger.info(
                    f"Target device '{target_desc}' found during upward scroll! Attempting safe click...")
                if self._safe_click_target_device(device_name, initial_item=matched_item):
                    return True
            if self._is_at_top_of_page():
                self._logger.info("Successfully returned to the top of the device list.")
                break
            self._logger.info(f"Scrolling up towards top ({scroll_idx + 1})...")
            self._scroll_up_page()
        time.sleep(2)
        final_items = self._get_all_visible_device_items()
        for item in final_items:
            name = item["display_name"]
            if name not in discovered_device_names:
                discovered_device_names.append(name)
            if self._is_target_device_match(device_name, item):
                self._logger.info(
                    f"Target device '{target_desc}' found at top after Phase 3! Attempting safe click...")
                if self._safe_click_target_device(device_name, initial_item=item):
                    return True
        self._logger.info(
            f"Final Discovered Device Name List ({len(discovered_device_names)}): {discovered_device_names}")
        self._logger.error(
            f"Could not find visible device '{target_desc}' after full bidirectional scan.")
        return False
