"""Page object method for verifying device existence on the Set up nearby devices page in iOS."""
import contextlib
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
from common import constants
from common.base_page import BasePage, PageNotPresentException
from utils import logging_utils


class GHASetUpDevicePage(BasePage):
    """Class for handling Google Home device setup ('Set up nearby devices') page on iOS."""
    EXPECTED_DEVICE_IDENTIFIERS: Dict[str, str] = {
        "Onn Wired Indoor Camera": "5502:4233:1658",
        "Ref2 Battery Camera": "4738:21505:2329",
        "HD Wired Indoor Camera": "4738:20482:2447",
        "2K Battery Doorbell Camera": "4738:21009:1573",
        "Onn Wired Indoor Camera New": "5502:4233:687",
    }

    @contextlib.contextmanager
    def _setup_no_implicit_wait(self) -> Iterator[None]:
        """Temporarily set Appium implicit wait to 0s so element queries do not block 10s on miss."""
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

    def _get_expected_identifier(self, target_name: str) -> Optional[str]:
        """Return the hardcoded device identifier (subtitle) for known devices, or None.
        Checks exact key match first so 'Onn Wired Indoor Camera New' resolves to '5502:4233:687'
        while 'Onn Wired Indoor Camera' resolves to '5502:4233:1658'.
        """
        target_norm = " ".join(target_name.strip().lower().split())
        if not target_norm:
            return None
        for dev_name, identifier in self.EXPECTED_DEVICE_IDENTIFIERS.items():
            dev_norm = " ".join(dev_name.strip().lower().split())
            if target_norm == dev_norm:
                return identifier.strip().lower()
        return None

    @staticmethod
    def _is_name_contained(target_name: str, card_title: str, card_display: str = "") -> bool:
        """Check whether target_name and card_title contain each other (case-insensitive).
        Examples:
            target_name='Onn Wired Indoor Camera New', card_title='Onn Wired Indoor Camera' -> True
            target_name='Onn Wired Indoor Camera',     card_title='Onn Wired Indoor Camera' -> True
            target_name='Ref2 Battery Doorbell Camera', card_title='2K Battery Doorbell Camera' -> True
        """
        target = " ".join(target_name.strip().lower().split())
        title = " ".join(card_title.strip().lower().split())
        display = " ".join(card_display.strip().lower().split())
        if not target or not title:
            return False
        if target == title or target in title or title in target:
            return True
        if display and (target == display or target in display or display in target):
            return True
        # Handle model prefix aliases such as 'Ref2 Battery Doorbell Camera' vs '2K Battery Doorbell Camera'
        target_words = target.split()
        if len(target_words) >= 3:
            core_suffix = " ".join(target_words[1:])
            if len(core_suffix) >= 6 and core_suffix in title:
                return True
        title_words = title.split()
        if len(title_words) >= 3:
            title_suffix = " ".join(title_words[1:])
            if len(title_suffix) >= 6 and title_suffix in target:
                return True
        return False

    def _get_window_size_safe(self) -> Tuple[int, int]:
        """Return (width, height) of the screen with safe defaults."""
        try:
            win_size = self.driver.get_window_size()
            return int(win_size.get("width", 390)), int(win_size.get("height", 844))
        except Exception:
            return 390, 844

    def _get_footer_top_y(self) -> int:
        """Return the top y-coordinate of the sticky 'Set up a different device' footer container.
        On iOS GHA, the white footer container sits at roughly the bottom 22% of the screen (~y=650 on 844pt,
        ~y=625 on 812pt), and any element or text at y >= footer_top_y is covered by the footer.
        """
        _, win_h = self._get_window_size_safe()
        default_footer_top = int(win_h * 0.77)  # ~650 on 844pt screen, ~625 on 812pt screen
        with self._setup_no_implicit_wait():
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
                            # The white footer panel extends ~20pt above the button's top edge
                            return min(default_footer_top, btn_y - 20)
                    except Exception:
                        continue
            except Exception:
                pass
        return default_footer_top

    @staticmethod
    def _compute_name_bounds(
            top_y: int,
            height: int,
            footer_top_y: int,
            title_rect: Optional[Dict[str, int]] = None,
            has_visible_title_elem: bool = True,
    ) -> Tuple[int, int, bool]:
        """Compute (name_top_y, name_bottom_y, name_visible) for a device card.
        On GHA 'Set up nearby devices', each ~223pt card renders the illustration image in the upper ~135pt
        and the device name ('title') + identifier ('subtitle') in the bottom ~88pt (bottom_y - 88 .. bottom_y - 12).
        A card's device name is only visible on the UI (`name_visible=True`) when that bottom text region is
        completely above `footer_top_y - 10` (not covered by 'Set up a different device') and below the top header (y >= 90).
        """
        bottom_y = top_y + height
        if height >= 140:
            est_name_top = bottom_y - 88
            est_name_bottom = bottom_y - 12
        else:
            est_name_top = max(top_y + 5, bottom_y - 40)
            est_name_bottom = bottom_y - 5
        if title_rect is not None:
            t_top = int(title_rect.get("y", est_name_top))
            t_bottom = t_top + int(title_rect.get("height", 24))
            name_top_y = min(est_name_top, t_top)
            name_bottom_y = max(est_name_bottom, t_bottom)
        else:
            name_top_y = est_name_top
            name_bottom_y = est_name_bottom
        name_visible = (
                has_visible_title_elem
                and top_y >= 60
                and name_top_y >= 90
                and name_bottom_y <= (footer_top_y - 10)
        )
        return name_top_y, name_bottom_y, name_visible

    def _get_all_visible_device_items(self) -> List[Dict[str, Any]]:
        """Retrieve all currently detected device cards on screen with title, subtitle, element,
        and `name_visible` indicating whether the device name text is actually visible on the UI
        (not covered by the sticky 'Set up a different device' footer or top header).
        """
        visible_items: List[Dict[str, Any]] = []
        _, win_h = self._get_window_size_safe()
        footer_top_y = self._get_footer_top_y()
        footer_cutoff_y = int(win_h * 0.82)
        button_predicate = (
            'type == "XCUIElementTypeButton" AND '
            'name == "image-title-subtitle"'
        )
        with self._setup_no_implicit_wait():
            title_meta: List[Tuple[str, Dict[str, int]]] = []
            try:
                raw_titles = self.driver.find_elements(
                    AppiumBy.IOS_PREDICATE, 'name == "title" AND visible == 1'
                )
                for t_el in raw_titles:
                    try:
                        if not t_el.is_displayed():
                            continue
                        tr = dict(t_el.rect)
                        tt = (
                                t_el.get_attribute("value")
                                or t_el.get_attribute("label")
                                or t_el.text
                                or ""
                        ).strip()
                        # Ignore mock echoes where find_elements returns the card button itself for every query
                        if int(tr.get("height", 0)) < 120 and tt and "," not in tt:
                            title_meta.append((tt.lower(), tr))
                    except Exception:
                        continue
            except Exception:
                pass
            try:
                buttons = self.driver.find_elements(AppiumBy.IOS_PREDICATE, button_predicate)
                for btn in buttons:
                    try:
                        rect = btn.rect
                        height = int(rect.get("height", 0))
                        top_y = int(rect.get("y", 0))
                        bottom_y = top_y + height
                        # Skip cards that are completely off-screen above the header or below the screen
                        if height <= 0 or bottom_y <= 90 or top_y >= win_h:
                            continue
                        is_vis = False
                        try:
                            is_vis = bool(btn.is_displayed())
                        except Exception:
                            is_vis = False
                        # Accept the card for discovery logging if XCUITest marks it displayed OR if a portion of it
                        # sits inside the scrollable viewport between the header (y=90) and footer_cutoff_y.
                        if not is_vis and not (top_y < footer_cutoff_y and bottom_y > 110):
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
                        matched_title_rect: Optional[Dict[str, int]] = None
                        has_visible_title_elem = True
                        if title_meta:
                            has_visible_title_elem = False
                            for t_text_lower, t_rect in title_meta:
                                t_cy = int(t_rect["y"] + t_rect["height"] / 2)
                                if (top_y - 10 <= t_cy <= bottom_y + 15) and (
                                        t_text_lower == title.lower() or t_text_lower in title.lower()
                                ):
                                    matched_title_rect = t_rect
                                    has_visible_title_elem = True
                                    break
                        name_top_y, name_bottom_y, name_visible = self._compute_name_bounds(
                            top_y=top_y,
                            height=height,
                            footer_top_y=footer_top_y,
                            title_rect=matched_title_rect,
                            has_visible_title_elem=has_visible_title_elem,
                        )
                        visible_items.append({
                            "title": title,
                            "subtitle": subtitle,
                            "display_name": display_name,
                            "element": btn,
                            "rect": dict(rect),
                            "name_top_y": name_top_y,
                            "name_bottom_y": name_bottom_y,
                            "name_visible": name_visible,
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
                            t_text = (
                                    t_elem.get_attribute("value")
                                    or t_elem.get_attribute("label")
                                    or t_elem.text
                                    or ""
                            ).strip()
                            if not t_text:
                                continue
                            t_y = int(t_rect["y"])
                            t_h = int(t_rect.get("height", 24))
                            matching_sub = ""
                            sub_bottom = t_y + t_h
                            for s_elem in subtitle_elements:
                                s_rect = s_elem.rect
                                s_y = int(s_rect["y"])
                                if 0 <= (s_y - t_y) <= 60:
                                    matching_sub = (
                                            s_elem.get_attribute("value")
                                            or s_elem.get_attribute("label")
                                            or s_elem.text
                                            or ""
                                    ).strip()
                                    sub_bottom = max(sub_bottom,
                                                     s_y + int(s_rect.get("height", 20)))
                                    break
                            display_name = f"{t_text} ({matching_sub})" if matching_sub else t_text
                            name_visible = (t_y >= 90) and (sub_bottom <= footer_top_y - 10)
                            visible_items.append({
                                "title": t_text,
                                "subtitle": matching_sub,
                                "display_name": display_name,
                                "element": t_elem,
                                "rect": dict(t_rect),
                                "name_top_y": t_y,
                                "name_bottom_y": sub_bottom,
                                "name_visible": name_visible,
                            })
                        except (StaleElementReferenceException, WebDriverException):
                            continue
                except WebDriverException as e:
                    self._logger.debug(f"Fallback title/subtitle query error: {e}")
        return visible_items

    @staticmethod
    def _get_viewport_signature(items: List[Dict[str, Any]]) -> Tuple[Tuple[str, int], ...]:
        """Build a geometry signature of visible cards (display_name + quantized y) to detect scroll movement."""
        sig: List[Tuple[str, int], ...] = []
        for item in items:
            rect = item.get("rect") or {}
            y_bucket = int(round(float(rect.get("y", 0)) / 15.0))
            sig.append((item.get("display_name", ""), y_bucket))
        return tuple(sig)

    def _is_target_device_match(self, target_name: str, item: Dict[str, Any]) -> bool:
        """Check if a device item matches the target device name (by containment) and its expected identifier."""
        target = target_name.strip().lower()
        title = item["title"].strip().lower()
        subtitle = item["subtitle"].strip().lower()
        display = item["display_name"].strip().lower()
        name_matched = self._is_name_contained(target_name, title, display)
        expected_id = self._get_expected_identifier(target_name)
        if expected_id:
            id_matched = (
                    (expected_id == subtitle)
                    or (expected_id in subtitle)
                    or (expected_id in display)
            )
            return name_matched and id_matched
        if name_matched:
            return True
        if subtitle and (target == subtitle or target in subtitle or subtitle in target):
            return True
        return False

    def _is_at_top_of_page(self) -> bool:
        """Check if currently at the very top of the setup nearby devices page."""
        with self._setup_no_implicit_wait():
            try:
                headers = self.driver.find_elements(
                    AppiumBy.IOS_PREDICATE,
                    'name == "header_rootView" OR label CONTAINS "Set up nearby devices"',
                )
                return any(h.is_displayed() for h in headers)
            except Exception:
                return False

    def _nudge_scroll_vertical(self, start_y: int, end_y: int) -> None:
        """Perform a gentle, low-velocity vertical drag so iOS UIScrollView does not trigger inertia fling."""
        win_w, _ = self._get_window_size_safe()
        cx = win_w // 2
        try:
            self.driver.swipe(cx, start_y, cx, end_y, duration=800)
        except Exception:
            direction = "up" if start_y > end_y else "down"
            try:
                self.driver.execute_script("mobile: swipe", {"direction": direction})
            except Exception:
                pass
        time.sleep(0.8)

    def _scroll_down_page(self, deep: bool = False) -> None:
        """Scroll down the 'Set up nearby devices' list starting well above the 'Set up a different device' footer."""
        win_w, win_h = self._get_window_size_safe()
        cx = win_w // 2
        # Start at 58% of screen height (~470 on 812pt) and drag to 30% (~243pt) with 650ms duration
        # so we advance ~1 card height (~223pt) without flinging past multiple cards.
        start_y = int(win_h * 0.58)
        end_y = int(win_h * (0.22 if deep else 0.30))
        try:
            self.driver.swipe(cx, start_y, cx, end_y, duration=650)
        except Exception as swipe_err:
            self._logger.debug(
                f"Coordinate swipe down failed ({swipe_err}), falling back to mobile: swipe..."
            )
            try:
                self.driver.execute_script("mobile: swipe", {"direction": "up"})
            except Exception as fallback_err:
                self._logger.warning(f"mobile: swipe down failed: {fallback_err}")

    def _scroll_up_page(self) -> None:
        """Scroll up towards the top of the 'Set up nearby devices' list."""
        win_w, win_h = self._get_window_size_safe()
        cx = win_w // 2
        start_y = int(win_h * 0.28)
        end_y = int(win_h * 0.58)
        try:
            self.driver.swipe(cx, start_y, cx, end_y, duration=650)
        except Exception as swipe_err:
            self._logger.debug(
                f"Coordinate swipe up failed ({swipe_err}), falling back to mobile: swipe..."
            )
            try:
                self.driver.execute_script("mobile: swipe", {"direction": "down"})
            except Exception as fallback_err:
                self._logger.warning(f"mobile: swipe up failed: {fallback_err}")

    def _tap_card_with_fallbacks(
            self,
            target_name: str,
            elem: WebElement,
            rect: Dict[str, int],
            display_name: str,
            footer_top_y: int,
    ) -> bool:
        """Click the device card element only when its device name is visible above the footer,
        and verify that a sudden nearby-device list update did not shift the card away without navigating.
        """
        safe_min_tap_y = max(95, int(rect["y"]) + 30)
        safe_max_tap_y = footer_top_y - 30
        cx = int(rect["x"] + rect["width"] / 2)
        raw_cy = int(rect["y"] + rect["height"] / 2)
        safe_cy = max(safe_min_tap_y, min(raw_cy, safe_max_tap_y))
        tapped = False
        if raw_cy > safe_max_tap_y or int(rect["y"]) < 60:
            self._logger.info(
                f"Card '{display_name}' (y={rect['y']}, cy={raw_cy}, footer_top={footer_top_y}) "
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
                    f"Clicked device card '{display_name}' via elem.click() at cy={raw_cy}."
                )
                tapped = True
            except (StaleElementReferenceException, WebDriverException) as click_err:
                self._logger.warning(
                    f"elem.click() on '{display_name}' failed ({click_err}); trying mobile: tap..."
                )
                try:
                    self.driver.execute_script("mobile: tap", {"x": cx, "y": safe_cy})
                    self._logger.info(
                        f"Coordinate-tapped device card '{display_name}' at ({cx}, {safe_cy})."
                    )
                    tapped = True
                except Exception as tap_err:
                    self._logger.error(f"All tap methods failed for '{display_name}': {tap_err}")
                    return False
        # Wait 1.0s and inspect the screen:
        # 1) If no nearby-device cards remain on screen, we successfully navigated to the next setup page!
        # 2) If nearby-device cards are still on screen, check whether our target card ran away or is still visible.
        time.sleep(1.0)
        post_click_items = self._get_all_visible_device_items()
        if not post_click_items:
            return tapped
        still_present = None
        for item in post_click_items:
            if self._is_target_device_match(target_name, item):
                still_present = item
                break
        if still_present is None:
            # Other nearby device cards are still on screen, but our target card disappeared!
            # That means the nearby devices list updated right as we clicked and pushed our target card off-screen.
            self._logger.warning(
                f"Nearby devices list updated during click and '{display_name}' shifted off-screen "
                f"(still on 'Set up nearby devices' with {len(post_click_items)} visible card(s)). "
                f"Continuing scan to re-locate '{display_name}'..."
            )
            return False
        if not still_present.get("name_visible", False):
            self._logger.warning(
                f"After initial click, '{display_name}' shifted so its device name is now covered on UI "
                f"(y={still_present['rect']['y']}, name_bottom={still_present.get('name_bottom_y')}, "
                f"footer_top={footer_top_y}). Scrolling to reveal device name before re-clicking..."
            )
            return False
        try:
            r2 = still_present.get("rect") or still_present["element"].rect
            cx2 = int(r2["x"] + r2["width"] / 2)
            raw_cy2 = int(r2["y"] + r2["height"] / 2)
            min_y2 = max(95, int(r2["y"]) + 30)
            cy2 = max(min_y2, min(raw_cy2, safe_max_tap_y))
            self._logger.info(
                f"Device card '{display_name}' still visible with device name on UI after initial click; "
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
        """Safely locate, verify that the device name is visible on the UI (not covered by the footer or header),
        confirm list position stability against sudden nearby-device list updates, and click the target device card.
        Returns:
            bool: True if clicked and navigated successfully, False if not visible or shifted out.
        """
        _, win_h = self._get_window_size_safe()
        footer_top_y = self._get_footer_top_y()
        last_nudge: Optional[str] = None
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
                if last_nudge == "up" and attempt < 3:
                    self._logger.info(
                        "Reversing previous upward nudge to pull target card back into view..."
                    )
                    self._nudge_scroll_vertical(int(win_h * 0.35), int(win_h * 0.55))
                    last_nudge = "down"
                else:
                    time.sleep(0.5)
                continue
            elem = target_item["element"]
            try:
                rect = target_item.get("rect") or elem.rect
                top_y = int(rect["y"])
                height = int(rect["height"])
                cy = int(top_y + height / 2)
                card_bottom = int(top_y + height)
                name_top_y = int(target_item.get("name_top_y", card_bottom - 88))
                name_bottom_y = int(target_item.get("name_bottom_y", card_bottom - 12))
                name_visible = bool(target_item.get("name_visible", False))
                # Requirement: Device name MUST be visible on the UI (not covered by 'Set up a different device' footer)
                if not name_visible and attempt < 3:
                    if name_bottom_y > footer_top_y - 10:
                        self._logger.info(
                            f"Target '{target_item['display_name']}' is detected on screen, but its device name is "
                            f"covered by the 'Set up a different device' footer (y={top_y}, bottom={card_bottom}, "
                            f"name_bottom={name_bottom_y}, footer_top={footer_top_y}). "
                            f"Scrolling up gently so device name is visible on UI (attempt {attempt + 1}/3)..."
                        )
                        # Calculate gentle drag distance to pull name_bottom_y ~65pt above footer_top_y
                        needed_shift = max(135, min(210, name_bottom_y - (footer_top_y - 65)))
                        start_y = int(win_h * 0.56)
                        end_y = max(int(win_h * 0.25), start_y - needed_shift)
                        self._nudge_scroll_vertical(start_y, end_y)
                        last_nudge = "up"
                        continue
                    if top_y < 60 or name_top_y < 90:
                        self._logger.info(
                            f"Target '{target_item['display_name']}' is clipped near the top header "
                            f"(y={top_y}, name_top={name_top_y}). Nudging down gently (attempt {attempt + 1}/3)..."
                        )
                        self._nudge_scroll_vertical(int(win_h * 0.35), int(win_h * 0.53))
                        last_nudge = "down"
                        continue
                # Pre-click stability re-verification: pause briefly and re-check the live UI to ensure
                # the nearby devices list did not suddenly update and shift the card or cover its name.
                time.sleep(0.4)
                fresh_items = self._get_all_visible_device_items()
                if fresh_items:
                    fresh_target = None
                    for f_item in fresh_items:
                        if self._is_target_device_match(target_name, f_item):
                            fresh_target = f_item
                            break
                    if fresh_target is None:
                        self._logger.warning(
                            f"Target '{target_item['display_name']}' disappeared from viewport right before click "
                            f"(nearby devices list updated). Re-locating..."
                        )
                        continue
                    fresh_rect = fresh_target.get("rect") or fresh_target["element"].rect
                    fresh_top_y = int(fresh_rect["y"])
                    if not fresh_target.get("name_visible", False) and attempt < 3:
                        self._logger.warning(
                            f"Nearby devices list updated and '{fresh_target['display_name']}' device name is now "
                            f"covered (y={fresh_top_y}, name_bottom={fresh_target.get('name_bottom_y')}, "
                            f"footer_top={footer_top_y}). Scrolling to reveal device name before clicking..."
                        )
                        continue
                    if abs(fresh_top_y - top_y) > 35 and attempt < 3:
                        self._logger.warning(
                            f"Nearby devices list is shifting ('{fresh_target['display_name']}' moved from "
                            f"y={top_y} to y={fresh_top_y}). Waiting for list to stabilize before clicking..."
                        )
                        continue
                    target_item = fresh_target
                    elem = fresh_target["element"]
                    rect = fresh_rect
                    top_y = fresh_top_y
                    cy = int(rect["y"] + rect["height"] / 2)
                current_label = (
                        elem.get_attribute("label") or elem.get_attribute(
                    "value") or elem.text or ""
                ).lower()
                expected_sub = target_item["subtitle"].lower()
                if current_label and (
                        not self._is_name_contained(target_item["title"], current_label)
                        or (
                                expected_sub and "," in current_label and expected_sub not in current_label)
                ):
                    self._logger.warning(
                        f"List shifted! Element is now '{current_label}' instead of '{target_item['display_name']}'. Re-locating..."
                    )
                    time.sleep(0.5)
                    continue
                self._logger.info(
                    f"Target device '{target_item['display_name']}' has device name clearly visible on UI "
                    f"(y={top_y}, cy={cy}, name_bottom={target_item.get('name_bottom_y')}, footer_top={footer_top_y})! "
                    f"Clicking now..."
                )
                if self._tap_card_with_fallbacks(
                        target_name, elem, rect, target_item["display_name"], footer_top_y
                ):
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
        """Scan nearby devices, log discovered device list (title + subtitle), and click the target device
        only when its device name is visible on the UI.
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
                f"Discovered Device Name List ({len(discovered_device_names)}): {discovered_device_names}"
            )
            if matched_item is not None:
                self._logger.info(
                    f"Target device '{target_desc}' matched card '{matched_item['display_name']}' "
                    f"(name_visible={matched_item.get('name_visible')})! Attempting safe click..."
                )
                if self._safe_click_target_device(device_name, initial_item=matched_item):
                    return True
                else:
                    self._logger.info(
                        "Target was pushed off-screen or list updated during Phase 1. Proceeding to Phase 2 scroll..."
                    )
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
                f"Discovered Device Name List ({len(discovered_device_names)}): {discovered_device_names}"
            )
            if matched_item is not None:
                self._logger.info(
                    f"Target device '{target_desc}' matched card '{matched_item['display_name']}' at top "
                    f"(name_visible={matched_item.get('name_visible')})! Attempting safe click..."
                )
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
                f"Discovered Device Name List ({len(discovered_device_names)}): {discovered_device_names}"
            )
            if matched_item is not None:
                self._logger.info(
                    f"Target device '{target_desc}' matched card '{matched_item['display_name']}' during downward scroll "
                    f"(name_visible={matched_item.get('name_visible')})! Attempting safe click..."
                )
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
                    f"Discovered Device Name List ({len(discovered_device_names)}): {discovered_device_names}"
                )
                self._logger.info(
                    f"Target device '{target_desc}' matched card '{matched_item['display_name']}' during upward scroll "
                    f"(name_visible={matched_item.get('name_visible')})! Attempting safe click..."
                )
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
                    f"Target device '{target_desc}' matched card '{item['display_name']}' at top after Phase 3 "
                    f"(name_visible={item.get('name_visible')})! Attempting safe click..."
                )
                if self._safe_click_target_device(device_name, initial_item=item):
                    return True
        self._logger.info(
            f"Final Discovered Device Name List ({len(discovered_device_names)}): {discovered_device_names}"
        )
        self._logger.error(
            f"Could not find visible device '{target_desc}' after full bidirectional scan."
        )
        return False
