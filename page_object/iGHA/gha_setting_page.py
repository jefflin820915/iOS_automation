"""Page object for handling the GHA Settings page and horizontal device card selection on iOS."""
import contextlib
import re
import time
from typing import Dict, Iterator, List, Optional, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException, \
    WebDriverException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from common import constants
from common.base_page import BasePage, PageNotPresentException
from utils import logging_utils


class GHASettingsPage(BasePage):
    """Class for interacting with GHA Settings page, horizontal device cards, and settings navigation."""
    PAGE_LOCATOR = (AppiumBy.IOS_CLASS_CHAIN,
                    '**/XCUIElementTypeNavigationBar[`name == "Settings"`]')
    HORIZONTAL_CARDS_COLLECTION = "preferenceHorizontalCardsListCellCollectionView"
    LEGACY_HORIZONTAL_CARDS_CELL = "preferenceDisplayingCell_5_0"
    DEVICES_CARDS_CONTAINER_LOCATORS: List[Tuple[str, str]] = [
        (
            AppiumBy.IOS_CLASS_CHAIN,
            '**/XCUIElementTypeCollectionView[`name == "preferenceHorizontalCardsListCellCollectionView"`]',
        ),
        (AppiumBy.ACCESSIBILITY_ID, "preferenceHorizontalCardsListCellCollectionView"),
        (AppiumBy.ACCESSIBILITY_ID, "preferenceDisplayingCell_5_0"),
    ]
    DEVICES_SECTION_LOCATOR = (
        AppiumBy.IOS_PREDICATE,
        'label CONTAINS "Devices, groups & rooms" OR name CONTAINS "preferenceDisplayingCell"'
    )
    HOME_SETTINGS_MARKER_LOCATOR = (
        AppiumBy.IOS_PREDICATE,
        'label CONTAINS "Devices, groups & rooms"'
    )
    SERVICES_SECTION_LOCATOR = (
        AppiumBy.IOS_PREDICATE,
        'name == "Services" OR label == "Services"'
    )
    _POSITION_SUFFIX_RE = re.compile(r"\s*\b\d+\s+of\s+\d+\s*$", re.IGNORECASE)
    _POSITION_NUMS_RE = re.compile(r"(\d+)\s+of\s+(\d+)\s*$", re.IGNORECASE)

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Collapse newlines, directional marks, and multiple spaces into a single space."""
        if not text or not isinstance(text, str):
            return ""
        cleaned = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069]", "", text)
        return " ".join(cleaned.replace("\n", " ").replace("\r", " ").split()).strip()

    @classmethod
    def _extract_card_title(cls, raw_text: str) -> str:
        """Extract the device title from a categoryCard label such as 'Ref2 Battery Camera\\n 1 of 17'."""
        if not raw_text:
            return ""
        lines = [line.strip() for line in raw_text.replace("\r", "\n").split("\n") if line.strip()]
        if not lines:
            return ""
        first_line = cls._POSITION_SUFFIX_RE.sub("", lines[0]).strip()
        if not first_line and len(lines) > 1:
            first_line = cls._POSITION_SUFFIX_RE.sub("", lines[1]).strip()
        return cls._normalize_text(first_line.split(",")[0])

    @classmethod
    def _extract_card_position(cls, raw_text: str) -> Optional[Tuple[int, int]]:
        """Extract (index, total) from a categoryCard label like 'Ref2 Battery Camera\\n 1 of 17'."""
        if not raw_text:
            return None
        match = cls._POSITION_NUMS_RE.search(cls._normalize_text(raw_text))
        if not match:
            return None
        return int(match.group(1)), int(match.group(2))

    @classmethod
    def _get_fallback_device_names(cls, device_name: str) -> List[str]:
        """Return default GHA hardware-type fallback names when custom naming falls back during commissioning.
        Examples:
            '2K Battery Doorbell Camera' -> ['Doorbell']
            'Ref2 Battery Camera'        -> ['Camera']
        """
        norm = cls._normalize_text(device_name).lower()
        if not norm:
            return []
        if "doorbell" in norm and norm != "doorbell":
            return ["Doorbell"]
        if "camera" in norm and norm != "camera":
            return ["Camera"]
        return []

    @classmethod
    def _matches_exact_card_name(cls, raw_text: str, target_name: str) -> bool:
        """Check whether a Settings card label represents a device whose title is exactly target_name.
        Matches e.g. 'Doorbell, Attic', 'Doorbell\\nAttic', 'Camera, Attic', 'Camera\\nAttic',
        'Doorbell\\n 1 of 17', while rejecting unrelated rows or other devices.
        """
        norm_target = cls._normalize_text(target_name).lower()
        if not norm_target or not raw_text:
            return False
        stripped = cls._POSITION_SUFFIX_RE.sub("", raw_text.replace("\r", "\n")).strip()
        first_part = cls._normalize_text(stripped.replace("\n", ",").split(",")[0]).lower()
        return first_part == norm_target or first_part == f"attic {norm_target}"

    @classmethod
    def _matches_primary_card_name(cls, raw_text: str, target_name: str) -> bool:
        """Check whether raw card label matches the target device name (exact title or case-insensitive substring)."""
        norm_target = cls._normalize_text(target_name).lower()
        if not norm_target or not raw_text:
            return False
        title = cls._extract_card_title(raw_text).lower()
        norm_full = cls._normalize_text(cls._POSITION_SUFFIX_RE.sub("", raw_text)).lower()
        return (
                title == norm_target
                or norm_target in title
                or norm_target in norm_full
        )

    def _get_resolved_device_name(self) -> Optional[str]:
        """Return previously resolved fallback/actual device name from self or session, if any."""
        for obj in (
                self,
                getattr(self, "session", None),
                getattr(self, "ghasettingspage", None),
        ):
            if obj is not None:
                resolved = getattr(obj, "_resolved_device_name", None)
                if isinstance(resolved, str) and resolved.strip():
                    return resolved
        return None

    @contextlib.contextmanager
    def _settings_no_implicit_wait(self) -> Iterator[None]:
        """Temporarily set Appium implicit wait to 0s so absent locators fail immediately."""
        default_wait = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
        try:
            if hasattr(self.driver, "implicitly_wait"):
                self.driver.implicitly_wait(0)
            yield
        finally:
            try:
                if hasattr(self.driver, "implicitly_wait"):
                    self.driver.implicitly_wait(default_wait)
            except Exception:
                pass

    def _find_element(self, by: AppiumBy, locator_value: str) -> Optional[WebElement]:
        """Find an element using specified locator strategy with explicit wait (0s implicit wait)."""
        try:
            with GHASettingsPage._settings_no_implicit_wait(self):
                return WebDriverWait(self.driver, self.timeout).until(
                    EC.presence_of_element_located((by, locator_value))
                )
        except TimeoutException:
            self._logger.error(f"Timed out waiting for element: by={by}, value='{locator_value}'")
            return None

    def _find_elements(self, by: AppiumBy, value: str, timeout: float = 0.0) -> List[WebElement]:
        """Fast non-blocking element probe with 0s implicit wait; returns [] when none match."""
        try:
            with GHASettingsPage._settings_no_implicit_wait(self):
                if timeout <= 0:
                    return self.driver.find_elements(by, value) or []
                return WebDriverWait(self.driver, timeout).until(
                    lambda d: d.find_elements(by, value) or False
                ) or []
        except (TimeoutException, WebDriverException):
            return []

    @staticmethod
    def _get_safe_rect(elem: WebElement) -> Optional[Dict[str, float]]:
        """Read element rect safely; return None if missing or non-numeric."""
        try:
            rect = elem.rect
            if (
                    isinstance(rect, dict)
                    and isinstance(rect.get("x"), (int, float))
                    and isinstance(rect.get("y"), (int, float))
                    and isinstance(rect.get("width"), (int, float))
                    and isinstance(rect.get("height"), (int, float))
                    and rect["width"] > 0
                    and rect["height"] > 0
            ):
                return rect
        except (StaleElementReferenceException, WebDriverException, Exception):
            pass
        return None

    def _get_window_size_safe(self) -> Tuple[float, float]:
        """Return (width, height) of the current window with safe defaults."""
        try:
            win = self.driver.get_window_size() or {}
            w = float(win.get("width", 375) or 375)
            h = float(win.get("height", 812) or 812)
            return w, h
        except Exception:
            return 375.0, 812.0

    @staticmethod
    def _get_card_label(elem: WebElement) -> str:
        """Read best non-empty text identifier from a Settings element."""
        for attr in ("label", "name", "value"):
            try:
                val = elem.get_attribute(attr)
                if val and str(val).strip():
                    return str(val).strip()
            except Exception:
                pass
        try:
            txt = getattr(elem, "text", None)
            if txt and str(txt).strip():
                return str(txt).strip()
        except Exception:
            pass
        return ""

    @staticmethod
    def _is_card_in_viewport(rect: Optional[Dict[str, float]], window_width: float) -> bool:
        """Return True if a horizontal card has enough area inside [0, window_width] to be clickable.
        Tolerates partially clipped left/right cards (e.g. x = -15, width = 109) when >= 40%
        or >= 40pt of the card is cleanly on screen and its visible midpoint is inside viewport.
        """
        if not rect:
            return False
        left = float(rect["x"])
        width = float(rect["width"])
        right = left + width
        visible_left = max(0.0, left)
        visible_right = min(window_width, right)
        overlap = visible_right - visible_left
        if overlap < min(40.0, width * 0.45):
            return False
        visible_mid = (visible_left + visible_right) / 2.0
        return 0.0 < visible_mid < window_width

    def _dispatch_find_elements(self, by: AppiumBy, value: str, timeout: float = 0.0) -> List[
        WebElement]:
        """Invoke _find_elements safely whether self is GHASettingsPage or an unbound GHASession."""
        if isinstance(self, GHASettingsPage):
            return self._find_elements(by, value,
                                       timeout=timeout) if timeout > 0 else self._find_elements(by,
                                                                                                value)
        return GHASettingsPage._find_elements(self, by, value, timeout=timeout)

    def _get_section_y_bounds_markers(self) -> Tuple[Optional[float], Optional[float]]:
        """Return (devices_header_y, services_header_y) for the Home Settings sections, or (None, None)."""
        _, window_height = GHASettingsPage._get_window_size_safe(self)
        devices_y: Optional[float] = None
        for elem in GHASettingsPage._dispatch_find_elements(self,
                                                            *GHASettingsPage.HOME_SETTINGS_MARKER_LOCATOR):
            rect = GHASettingsPage._get_safe_rect(elem)
            if not rect or not (60.0 <= float(rect["y"]) < window_height):
                continue
            try:
                if not elem.is_displayed():
                    continue
            except Exception:
                pass
            devices_y = float(rect["y"])
            break

        services_y: Optional[float] = None
        for elem in GHASettingsPage._dispatch_find_elements(self,
                                                            *GHASettingsPage.SERVICES_SECTION_LOCATOR):
            rect = GHASettingsPage._get_safe_rect(elem)
            if not rect or not (100.0 < float(rect["y"]) < window_height):
                continue
            try:
                if not elem.is_displayed():
                    continue
            except Exception:
                pass
            if devices_y is not None and float(rect["y"]) <= devices_y + 20.0:
                continue
            services_y = float(rect["y"])
            break
        return devices_y, services_y

    def _get_devices_carousel_element_and_y_bounds(
            self,
    ) -> Tuple[Optional[WebElement], Optional[Tuple[float, float]]]:
        """Locate the Devices horizontal UICollectionView (above Services) and its vertical (y_min, y_max) band."""
        _, window_height = GHASettingsPage._get_window_size_safe(self)
        devices_y, services_y = GHASettingsPage._get_section_y_bounds_markers(self)

        best_elem: Optional[WebElement] = None
        best_rect: Optional[Dict[str, float]] = None
        for by, loc in GHASettingsPage.DEVICES_CARDS_CONTAINER_LOCATORS:
            candidates = GHASettingsPage._dispatch_find_elements(self, by, loc)
            valid: List[Tuple[WebElement, Dict[str, float]]] = []
            for cand in candidates:
                rect = GHASettingsPage._get_safe_rect(cand)
                if not rect:
                    continue
                if rect["height"] < 55.0 or rect["width"] < 100.0:
                    continue
                if not (0.0 <= float(rect["y"]) < window_height):
                    continue
                if services_y is not None and float(rect["y"]) >= services_y:
                    continue
                if devices_y is not None and float(rect["y"]) + float(rect["height"]) <= devices_y:
                    continue
                valid.append((cand, rect))
            if valid:
                # Top-most horizontal carousel belongs to 'Devices, groups & rooms' (above 'Services').
                valid.sort(key=lambda item: item[1]["y"])
                best_elem, best_rect = valid[0]
                break

        if best_rect:
            return best_elem, (float(best_rect["y"]) - 12.0,
                               float(best_rect["y"] + best_rect["height"]) + 12.0)
        if services_y is not None:
            return best_elem, (float(devices_y) if devices_y is not None else 0.0, services_y)
        return best_elem, None

    def _collect_viewport_cards(
            self,
            y_bounds: Optional[Tuple[float, float]] = None,
    ) -> List[Tuple[WebElement, str, Optional[Dict[str, float]]]]:
        """Collect all Devices horizontal categoryCard elements currently in the viewport in left-to-right order."""
        window_width, window_height = GHASettingsPage._get_window_size_safe(self)
        if y_bounds is None:
            _, y_bounds = GHASettingsPage._get_devices_carousel_element_and_y_bounds(self)
        _, services_y = GHASettingsPage._get_section_y_bounds_markers(self)

        def _filter_elems(
                raw_elems: List[WebElement],
                active_y_bounds: Optional[Tuple[float, float]],
                require_displayed_when_no_bounds: bool = True,
        ) -> List[Tuple[WebElement, str, Optional[Dict[str, float]]]]:
            items: List[Tuple[WebElement, str, Optional[Dict[str, float]]]] = []
            for elem in raw_elems:
                rect = GHASettingsPage._get_safe_rect(elem)
                try:
                    displayed = bool(elem.is_displayed())
                except Exception:
                    displayed = False
                if rect is None and not displayed:
                    continue
                if rect is not None:
                    if not (0.0 <= float(rect["y"]) < window_height):
                        continue
                    mid_y = float(rect["y"]) + float(rect["height"]) / 2.0
                    if active_y_bounds:
                        if not (active_y_bounds[0] <= mid_y <= active_y_bounds[1]):
                            continue
                    else:
                        if services_y is not None and mid_y >= services_y:
                            continue
                        if require_displayed_when_no_bounds and not displayed:
                            continue
                    if not GHASettingsPage._is_card_in_viewport(rect, window_width):
                        continue
                label = GHASettingsPage._get_card_label(elem)
                if label:
                    items.append((elem, label, rect))
            return items

        def _pick_top_row(
                items: List[Tuple[WebElement, str, Optional[Dict[str, float]]]],
        ) -> List[Tuple[WebElement, str, Optional[Dict[str, float]]]]:
            with_rect = [item for item in items if item[2] is not None]
            if not with_rect:
                return items
            top_y = min(float(item[2]["y"]) for item in with_rect)
            return [
                item for item in items
                if item[2] is None or abs(float(item[2]["y"]) - top_y) <= 40.0
            ]

        elems_visible = GHASettingsPage._dispatch_find_elements(
            self,
            AppiumBy.IOS_CLASS_CHAIN,
            '**/XCUIElementTypeButton[`name == "categoryCard" AND visible == 1`]',
        )
        collected = _filter_elems(elems_visible, y_bounds)
        elems_all: List[WebElement] = []
        if not collected:
            # Some iOS horizontal UICollectionViews mark device cards visible=0 even when Services cards are visible=1.
            elems_all = GHASettingsPage._dispatch_find_elements(
                self,
                AppiumBy.IOS_CLASS_CHAIN,
                '**/XCUIElementTypeButton[`name == "categoryCard"`]',
            )
            collected = _filter_elems(elems_all, y_bounds)

        if not collected and y_bounds is not None:
            # If y_bounds rejected all visible/present categoryCards (e.g. shifted cell indices or container rect),
            # rescue the top-most horizontal row above Services instead of returning [].
            rescued = _filter_elems(elems_visible, None, require_displayed_when_no_bounds=True)
            if not rescued and elems_all:
                rescued = _filter_elems(elems_all, None, require_displayed_when_no_bounds=False)
            if rescued:
                collected = _pick_top_row(rescued)

        collected.sort(key=lambda item: float(item[2]["x"]) if item[2] else 0.0)
        return collected

    def _get_visible_device_card(
            self, device_name: str, exact_card_match: bool = False
    ) -> Optional[WebElement]:
        """Find a visible device card button matching device_name on the current viewport."""
        window_width, _ = GHASettingsPage._get_window_size_safe(self)
        _, y_bounds = GHASettingsPage._get_devices_carousel_element_and_y_bounds(self)
        cards = GHASettingsPage._collect_viewport_cards(self, y_bounds=y_bounds)
        for elem, label, _ in cards:
            if exact_card_match:
                if GHASettingsPage._matches_exact_card_name(label, device_name):
                    return elem
            elif GHASettingsPage._matches_primary_card_name(label, device_name):
                return elem

        # Skip redundant slow IOS_CLASS_CHAIN probes when visible categoryCards were already scanned.
        if cards:
            return None

        # Fallback to direct targeted locators (supports legacy Cell/StaticText UIs and mocked _find_elements tests)
        locators = [
            f'**/XCUIElementTypeButton[`name == "categoryCard" AND label CONTAINS[c] "{device_name}" AND visible == 1`]',
            f'**/XCUIElementTypeButton[`name == "categoryCard" AND label CONTAINS[c] "{device_name}"`]',
            f'**/XCUIElementTypeCell[`label CONTAINS[c] "{device_name}" AND visible == 1`]',
            f'**/XCUIElementTypeStaticText[`(name CONTAINS[c] "{device_name}" OR label CONTAINS[c] "{device_name}") AND visible == 1`]',
        ]
        for loc in locators:
            try:
                elems = GHASettingsPage._dispatch_find_elements(self, AppiumBy.IOS_CLASS_CHAIN, loc)
                for elem in elems:
                    if not elem.is_displayed():
                        continue
                    rect = GHASettingsPage._get_safe_rect(elem)
                    if y_bounds and rect:
                        mid_y = float(rect["y"]) + float(rect["height"]) / 2.0
                        if not (y_bounds[0] <= mid_y <= y_bounds[1]):
                            continue
                    raw_label = GHASettingsPage._get_card_label(elem)
                    if not raw_label:
                        continue
                    if exact_card_match:
                        if not GHASettingsPage._matches_exact_card_name(raw_label, device_name):
                            continue
                    elif not GHASettingsPage._matches_primary_card_name(raw_label, device_name):
                        continue
                    if rect is None or GHASettingsPage._is_card_in_viewport(rect, window_width):
                        return elem
            except Exception:
                pass
        return None

    def _get_visible_card_labels(self) -> List[str]:
        """Fetch all visible Devices categoryCard labels on current screen to detect scroll termination."""
        cards = GHASettingsPage._collect_viewport_cards(self)
        if cards:
            return [label for _, label, _ in cards]
        labels: List[str] = []
        try:
            elems = GHASettingsPage._dispatch_find_elements(
                self,
                AppiumBy.IOS_CLASS_CHAIN,
                '**/XCUIElementTypeButton[`name == "categoryCard" AND visible == 1`]'
            )
            for elem in elems:
                try:
                    if elem.is_displayed():
                        if label := GHASettingsPage._get_card_label(elem):
                            labels.append(label)
                except Exception:
                    pass
        except Exception:
            pass
        return labels

    def _swipe_horizontal(self, direction: str = "left", force_mobile_swipe: bool = False) -> None:
        """Perform a controlled horizontal drag across the Devices cards collection view.
        Uses bounded dragFromToForDuration (~62% carousel width) rather than inertial mobile: swipe
        so adjacent cards overlap by >= 1 card and no device card is skipped over.
        """
        self._logger.info(f"Swiping {direction} on horizontal device card list...")
        w, h = GHASettingsPage._get_window_size_safe(self)
        carousel, _ = GHASettingsPage._get_devices_carousel_element_and_y_bounds(self)
        carousel_rect = GHASettingsPage._get_safe_rect(carousel) if carousel is not None else None
        cards = GHASettingsPage._collect_viewport_cards(self)
        card_rect = next((c[2] for c in cards if c[2]), None)

        if force_mobile_swipe and carousel is not None:
            try:
                self.driver.execute_script(
                    "mobile: swipe",
                    {"direction": direction, "elementId": carousel.id},
                )
                time.sleep(0.35)
                return
            except Exception as swipe_err:
                self._logger.warning(
                    f"Forced mobile: swipe failed ({swipe_err}); falling back to drag...")

        use_carousel_rect = carousel_rect is not None and (
                card_rect is None
                or abs(
            (float(carousel_rect["y"]) + float(carousel_rect["height"]) / 2.0)
            - (float(card_rect["y"]) + float(card_rect["height"]) / 2.0)
        ) <= 50.0
        )

        if use_carousel_rect and carousel_rect is not None:
            y_pos = int(carousel_rect["y"] + carousel_rect["height"] / 2.0)
            x_left = int(max(16.0, carousel_rect["x"] + carousel_rect["width"] * 0.18))
            x_right = int(min(w - 16.0, carousel_rect["x"] + carousel_rect["width"] * 0.80))
        else:
            y_pos = int(card_rect["y"] + card_rect["height"] / 2.0) if card_rect else int(h * 0.58)
            x_left = int(w * 0.18)
            x_right = int(w * 0.80)

        if x_right <= x_left + 40:
            x_left, x_right = int(w * 0.18), int(w * 0.80)

        start_x = x_right if direction == "left" else x_left
        end_x = x_left if direction == "left" else x_right
        try:
            self.driver.execute_script("mobile: dragFromToForDuration", {
                "duration": 0.45,
                "fromX": start_x,
                "fromY": y_pos,
                "toX": end_x,
                "toY": y_pos
            })
            time.sleep(0.35)
        except Exception as e:
            self._logger.warning(f"Coordinate drag failed ({e}); trying mobile: swipe fallback...")
            if carousel is not None:
                try:
                    self.driver.execute_script(
                        "mobile: swipe",
                        {"direction": direction, "elementId": carousel.id},
                    )
                    time.sleep(0.35)
                except Exception as swipe_err:
                    self._logger.warning(f"mobile: swipe fallback failed: {swipe_err}")

    def _wait_for_cards_ready(self, timeout: float = 12.0) -> None:
        """Wait for Home Settings spinner to clear and Devices categoryCard items to finish rendering."""
        if GHASettingsPage._collect_viewport_cards(self):
            return
        spinner_present = any(
            getattr(e, "is_displayed", lambda: False)()
            for e in GHASettingsPage._dispatch_find_elements(
                self, AppiumBy.CLASS_NAME, "XCUIElementTypeActivityIndicator"
            )
        )
        section_present = GHASettingsPage.has_devices_groups_rooms_page(self)
        settings_nav_present = any(
            getattr(e, "is_displayed", lambda: False)()
            for e in GHASettingsPage._dispatch_find_elements(self, *GHASettingsPage.PAGE_LOCATOR)
        )
        if not (spinner_present or section_present or settings_nav_present):
            return
        self._logger.info("[Settings] Waiting for Home Settings device cards to finish loading...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            if GHASettingsPage._collect_viewport_cards(self):
                return
            time.sleep(0.4)

    def find_target_device(self, device_name: str, max_swipes: int = 12) -> Optional[WebElement]:
        """Search for a target device card by scanning and swiping horizontally across the Devices cards list.
        Supports fallback to default hardware names ('Doorbell' / 'Camera') if GHA failed
        to sync the custom device name during commissioning.
        Args:
            device_name (str): Visible name of the target device (e.g. '2K Battery Doorbell Camera').
            max_swipes (int): Maximum number of swipe attempts per direction. Defaults to 12.
        Returns:
            Optional[WebElement]: The matching card WebElement if found, else None.
        """
        self._logger.info(f"Start searching for device card: '{device_name}' in Settings...")
        GHASettingsPage._wait_for_cards_ready(self)
        resolved_name = GHASettingsPage._get_resolved_device_name(self)
        has_pre_resolved_fallback = bool(
            resolved_name and resolved_name.strip().lower() != device_name.strip().lower()
        )
        fallback_names: List[str] = []
        if has_pre_resolved_fallback:
            fallback_names.append(resolved_name)
        for fb in GHASettingsPage._get_fallback_device_names(device_name):
            if fb not in fallback_names:
                fallback_names.append(fb)

        def _check_primary_or_resolved() -> Optional[WebElement]:
            if card_elem := GHASettingsPage._get_visible_device_card(self, device_name):
                matched_label = GHASettingsPage._get_card_label(card_elem)
                self._logger.info(
                    f"Target device card '{device_name}' is VISIBLE (label='{matched_label}')!"
                )
                return card_elem
            if has_pre_resolved_fallback:
                if fb_card := GHASettingsPage._get_visible_device_card(
                        self, resolved_name, exact_card_match=True
                ):
                    matched_label = GHASettingsPage._get_card_label(fb_card)
                    self._logger.warning(
                        f"[Fallback Name] Target device card '{device_name}' found via pre-resolved fallback "
                        f"'{resolved_name}' in Settings (label='{matched_label}')!"
                    )
                    return fb_card
            return None

        last_seen_labels: List[str] = []
        swipes_done = 0
        retried_stuck_left = False
        for swipe_idx in range(max_swipes):
            if found := _check_primary_or_resolved():
                return found
            current_labels = GHASettingsPage._get_visible_card_labels(self)
            if current_labels and (swipe_idx == 0 or current_labels != last_seen_labels):
                pretty = [GHASettingsPage._normalize_text(lbl) for lbl in current_labels]
                self._logger.info(f"[SettingsScan left#{swipe_idx}] Visible cards: {pretty}")
            if current_labels and current_labels == last_seen_labels and swipe_idx > 0:
                last_pos = GHASettingsPage._extract_card_position(current_labels[-1])
                if last_pos and last_pos[0] < last_pos[1] and not retried_stuck_left:
                    self._logger.warning(
                        f"[SettingsScan left#{swipe_idx}] Carousel did not advance past "
                        f"{last_pos[0]} of {last_pos[1]}; retrying with mobile: swipe..."
                    )
                    retried_stuck_left = True
                    GHASettingsPage._swipe_horizontal(self, direction="left",
                                                      force_mobile_swipe=True)
                    swipes_done += 1
                    continue
                self._logger.info("Reached the end of horizontal card list.")
                break
            retried_stuck_left = False
            # Early stop if last visible card already shows 'N of N' (end of list reached).
            if current_labels and swipe_idx > 0:
                last_pos = GHASettingsPage._extract_card_position(current_labels[-1])
                if last_pos and last_pos[0] >= last_pos[1]:
                    self._logger.info(
                        f"Reached end of horizontal card list ({last_pos[0]} of {last_pos[1]})."
                    )
                    break
            last_seen_labels = current_labels
            GHASettingsPage._swipe_horizontal(self, direction="left")
            swipes_done += 1

        # Check fallback names at the current position before swiping right back
        for fb_name in fallback_names:
            if fb_card := GHASettingsPage._get_visible_device_card(self, fb_name,
                                                                   exact_card_match=True):
                self._logger.warning(
                    f"[Fallback Name] Target '{device_name}' not found in Settings, "
                    f"but default hardware card '{fb_name}' is VISIBLE! Selecting '{fb_name}'."
                )
                return fb_card

        self._logger.info(f"Device '{device_name}' not found swiping left. Swiping right back...")
        last_right_labels: List[str] = list(last_seen_labels)
        for right_idx in range(max(3, swipes_done + 1)):
            GHASettingsPage._swipe_horizontal(self, direction="right")
            if found := _check_primary_or_resolved():
                return found
            for fb_name in fallback_names:
                if fb_card := GHASettingsPage._get_visible_device_card(self, fb_name,
                                                                       exact_card_match=True):
                    self._logger.warning(
                        f"[Fallback Name] Target '{device_name}' matched via fallback card "
                        f"'{fb_name}' while swiping right in Settings!"
                    )
                    return fb_card
            cur_right = GHASettingsPage._get_visible_card_labels(self)
            if cur_right:
                if cur_right == last_right_labels and right_idx > 0:
                    self._logger.info("Reached the start of horizontal card list.")
                    break
                first_pos = GHASettingsPage._extract_card_position(cur_right[0])
                if first_pos and first_pos[0] <= 1:
                    self._logger.info(
                        f"Reached start of horizontal card list ({first_pos[0]} of {first_pos[1]})."
                    )
                    break
                last_right_labels = cur_right

        self._logger.warning(f"Could not find device card '{device_name}' in Settings.")
        return None

    def open_device_settings(self, device_name: str) -> bool:
        """Find and click on the target device card to open its settings page.
        Args:
            device_name (str): Visible name of the device.
        Returns:
            bool: True if clicked and navigated away from Home Settings, False otherwise.
        """
        target_card = GHASettingsPage.find_target_device(self, device_name)
        if not target_card:
            self._logger.error(f"Cannot open device settings: '{device_name}' not found.")
            return False
        matched_label = GHASettingsPage._get_card_label(target_card) or device_name

        def _tap_card_coords() -> bool:
            rect = GHASettingsPage._get_safe_rect(target_card)
            w, _ = GHASettingsPage._get_window_size_safe(self)
            if rect:
                vis_left = max(0.0, float(rect["x"]))
                vis_right = min(w, float(rect["x"]) + float(rect["width"]))
                if vis_right > vis_left:
                    tap_x = int((vis_left + vis_right) / 2.0)
                    tap_y = int(float(rect["y"]) + float(rect["height"]) / 2.0)
                    try:
                        self._logger.info(
                            f"Coordinate tapping device card '{matched_label}' at ({tap_x}, {tap_y})..."
                        )
                        self.driver.execute_script("mobile: tap", {"x": tap_x, "y": tap_y})
                        return True
                    except Exception as coord_err:
                        self._logger.error(f"Coordinate tap fallback failed: {coord_err}")
            return False

        def _is_on_home_settings() -> bool:
            elems = GHASettingsPage._dispatch_find_elements(
                self, *GHASettingsPage.HOME_SETTINGS_MARKER_LOCATOR
            )
            return any(getattr(e, "is_displayed", lambda: False)() for e in elems)

        def _left_home_settings(wait_s: float = 1.5) -> bool:
            # Wait briefly only when the Home Settings 'Devices, groups & rooms' marker is actually visible.
            if not _is_on_home_settings():
                return True
            deadline = time.time() + wait_s
            while time.time() < deadline:
                time.sleep(0.3)
                if not _is_on_home_settings():
                    return True
            return False

        clicked = False
        try:
            self._logger.info(f"Clicking device card: '{matched_label}'...")
            target_card.click()
            clicked = True
        except WebDriverException as e:
            self._logger.warning(f"Direct click failed: {e}. Trying tap fallback...")
            try:
                self.driver.execute_script("mobile: tap", {"elementId": target_card.id})
                clicked = True
            except Exception as tap_err:
                if _tap_card_coords():
                    clicked = True
                else:
                    self._logger.error(f"Tap fallback failed: {tap_err}")
                    return False

        if clicked and not _left_home_settings(wait_s=1.5):
            self._logger.warning(
                f"Clicked '{matched_label}' but still on Home Settings page; retrying coordinate tap..."
            )
            if _tap_card_coords():
                if not _left_home_settings(wait_s=2.0):
                    self._logger.error(
                        f"Still on Home Settings page after tapping '{matched_label}'."
                    )
                    return False
        return True

    def has_devices_groups_rooms_page(self) -> bool:
        """Check if 'Devices, groups & rooms' section exists on the Settings page."""
        try:
            elems = GHASettingsPage._dispatch_find_elements(self,
                                                            *GHASettingsPage.DEVICES_SECTION_LOCATOR)
            return any(e.is_displayed() for e in elems)
        except Exception:
            return False

    def enter_devices_groups_rooms_page(self) -> bool:
        """Click on 'Devices, groups & rooms' row to open the full devices/rooms list."""
        self._logger.info("Entering 'Devices, groups & rooms' page...")
        try:
            elems = GHASettingsPage._find_elements(self, *self.DEVICES_SECTION_LOCATOR, timeout=2.0)
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
            (AppiumBy.IOS_CLASS_CHAIN,
             '**/XCUIElementTypeNavigationBar[`name == "Settings"`]/**/XCUIElementTypeButton[1]'),
            (AppiumBy.ACCESSIBILITY_ID, "close"),
            (AppiumBy.ACCESSIBILITY_ID, "Close"),
            (AppiumBy.IOS_PREDICATE, 'label == "Close" OR name == "close"'),
        ]
        for by, value in close_locators:
            try:
                elems = GHASettingsPage._find_elements(self, by, value, timeout=1.5)
                if elems and elems[0].is_displayed():
                    elems[0].click()
                    time.sleep(1.5)
                    return True
            except Exception:
                pass
        self._logger.warning("Close button not found in Settings navigation bar.")
        return False
