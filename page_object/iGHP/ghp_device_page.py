"""Page object for handling the Devices tab, tab navigation, and opening device pages in iGHP."""

import contextlib
import time
from typing import Any, Iterator, List, Optional, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException

from common import constants
from common.base_page import BasePage
from utils import logging_utils

Locator = Tuple[str, str]
IOS_PREDICATE_BY = getattr(AppiumBy, "IOS_PREDICATE", "-ios predicate string")
IOS_CLASS_CHAIN_BY = getattr(AppiumBy, "IOS_CLASS_CHAIN", "-ios class chain")


def get_ghp_bundle_id() -> str:
    """Resolve the iOS Google Home Platform Sample App bundle ID from constants."""
    return str(
        getattr(constants, "iGHP_SAMPLE_APP_BUNDLE_ID", None)
        or getattr(constants, "GHP_SAMPLE_APP_BUNDLE_ID", None)
        or "com.google.homeplatform.sampleapp.gomezandres"
    )


class GHPDevicePage(BasePage):
    """Handles bottom Tab Bar navigation, device discovery, and opening Camera Live View in iGHP."""

    OFFLINE_STATUS_KEYWORDS: Tuple[str, ...] = (
        "offline",
        "not connected",
        "unavailable",
        "unreachable",
        "disconnected",
        "error fetching",
    )

    TAB_PREDICATES = {
        "devices": 'type == "XCUIElementTypeButton" AND (name == "Devices" OR label == "Devices")',
        "automations": 'type == "XCUIElementTypeButton" AND (name == "Automations" OR label == "Automations")',
        "history": (
            'type == "XCUIElementTypeButton" AND '
            '(label == "History" OR name == "History" OR name CONTAINS "clock.arrow")'
        ),
        "search": (
            'type == "XCUIElementTypeButton" AND '
            '(label == "Search" OR name == "Search" OR name == "magnifyingglass")'
        ),
        "settings": (
            'type == "XCUIElementTypeButton" AND '
            '(label == "Settings" OR name == "gearshape")'
        ),
    }

    SUBVIEW_BACK_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND ('
        'name == "BackButton" OR label == "Home" OR name == "Back" OR label == "Back" '
        'OR name == "xmark" OR label == "Close" OR name == "Close")'
    )

    CAMERA_LIVE_MARKERS_PREDICATE: str = (
        '(type == "XCUIElementTypeButton" AND ('
        'name IN {"mic.slash.fill", "mic.fill", "google_symbols/mic_off_symbol", '
        '"google_symbols/mic_symbol", "Turn Camera OFF", "Turn Camera ON", '
        '"Retry Connection", "Retry", "google_symbols/menu_symbol", "BackButton"} '
        'OR label IN {"Microphone Off", "Microphone On", "Turn Camera OFF", '
        '"Turn Camera ON", "Retry Connection", "Retry"})) '
        'OR (type == "XCUIElementTypeStaticText" AND ('
        'label IN {"Live", "Snapshot", "Camera is OFF", "Unable to play video."} '
        'OR label CONTAINS[c] "stream has disconnected" '
        'OR label CONTAINS[c] "device is offline"))'
    )

    def __init__(self, driver: WebDriver, timeout: float = 10.0) -> None:
        self.APP_BUNDLE_ID = get_ghp_bundle_id()
        super().__init__(driver, timeout=timeout)
        self._logger = logging_utils.get_logger(__name__, "ghp_device_page")

    @classmethod
    def _resolve_page(cls, ctx: Any) -> "GHPDevicePage":
        if isinstance(ctx, cls):
            return ctx
        existing = getattr(ctx, "ghpdevicepage", None)
        if isinstance(existing, cls):
            return existing
        session = getattr(ctx, "session", None)
        if session is not None and isinstance(getattr(session, "ghpdevicepage", None), cls):
            return session.ghpdevicepage
        page = cls(ctx.driver)
        if session is not None:
            page.session = session
        return page

    @contextlib.contextmanager
    def _fast_probe(self) -> Iterator[None]:
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

    @staticmethod
    def _norm(text: Optional[str]) -> str:
        return " ".join((text or "").strip().lower().split())

    def _read_attr(self, elem: WebElement,
                   attrs: Tuple[str, ...] = ("label", "name", "value")) -> str:
        for attr in attrs:
            try:
                val = elem.get_attribute(attr)
                if val and val.strip():
                    return val.strip()
            except (StaleElementReferenceException, WebDriverException):
                continue
        try:
            txt = elem.text
            return txt.strip() if txt else ""
        except (StaleElementReferenceException, WebDriverException):
            return ""

    def _tap_element_or_coords(self, elem: WebElement, desc: str = "element") -> bool:
        rect = None
        try:
            rect = elem.rect
        except WebDriverException:
            rect = None
        try:
            elem.click()
            return True
        except WebDriverException as click_err:
            self._logger.debug(
                f"Direct click failed on {desc} ({click_err}); trying mobile: tap...")
        if rect:
            cx = int(rect["x"] + rect["width"] / 2)
            cy = int(rect["y"] + rect["height"] / 2)
            try:
                self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                return True
            except WebDriverException as tap_err:
                self._logger.warning(f"Coordinate tap failed on {desc} at ({cx}, {cy}): {tap_err}")
        return False

    def _is_tab_bar_visible(self) -> bool:
        with self._fast_probe():
            try:
                bars = self.driver.find_elements(IOS_CLASS_CHAIN_BY, "**/XCUIElementTypeTabBar")
                for bar in bars:
                    if bar.is_displayed():
                        return True
            except WebDriverException:
                pass
        return False

    def _exit_subview_to_tabs_if_needed(self, max_steps: int = 3) -> None:
        for _ in range(max_steps):
            if self._is_tab_bar_visible():
                return
            with self._fast_probe():
                try:
                    btns = self.driver.find_elements(IOS_PREDICATE_BY, self.SUBVIEW_BACK_PREDICATE)
                except WebDriverException:
                    btns = []
                clicked = False
                for btn in btns:
                    try:
                        if btn.is_displayed():
                            self._tap_element_or_coords(btn, desc="subview back/close")
                            clicked = True
                            break
                    except WebDriverException:
                        continue
            if not clicked:
                break
            time.sleep(1.0)

    def go_to_tab(self, tab_name: Any = "Devices") -> bool:
        """Switch to the requested bottom tab ('Devices', 'Automations', 'History', 'Search', 'Settings')."""
        page = GHPDevicePage._resolve_page(self)
        raw = getattr(tab_name, "value", None) or getattr(tab_name, "name", None) or str(
            tab_name or "Devices")
        key = str(raw).strip().lower()
        if "device" in key:
            key = "devices"
        predicate = page.TAB_PREDICATES.get(key, page.TAB_PREDICATES["devices"])

        page._exit_subview_to_tabs_if_needed()
        with page._fast_probe():
            try:
                candidates = page.driver.find_elements(IOS_PREDICATE_BY, predicate)
            except WebDriverException:
                candidates = []
            # Prefer button inside TabBar (y > 650) when multiple 'Settings' buttons exist
            chosen: Optional[WebElement] = None
            for btn in candidates:
                try:
                    if not btn.is_displayed():
                        continue
                    r = btn.rect
                    if r.get("y", 0) >= 620:
                        chosen = btn
                        break
                    if chosen is None:
                        chosen = btn
                except WebDriverException:
                    continue
            if chosen is not None:
                page._logger.info(f"Navigating to GHP tab: '{raw}'...")
                page._tap_element_or_coords(chosen, desc=f"Tab '{raw}'")
                time.sleep(1.0)
                return True
        page._logger.warning(f"Tab button '{raw}' was not located; continuing on current screen.")
        return False

    def _split_tile_name_and_status(self, tile: WebElement) -> Tuple[str, str]:
        """Extract (device_title, status_text) from a GHP StructureView device tile button."""
        raw = self._read_attr(tile, ("label", "name", "value"))
        if raw:
            if "," in raw:
                title_part, status_part = raw.rsplit(",", 1)
                return title_part.strip(), status_part.strip()
            if "\n" in raw:
                parts = [p.strip() for p in raw.splitlines() if p.strip()]
                if len(parts) >= 2:
                    return parts[0], parts[-1]
                if parts:
                    return parts[0], ""
        with self._fast_probe():
            try:
                texts = tile.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText")
            except WebDriverException:
                texts = []
            vals = [self._read_attr(t, ("value", "label", "name")) for t in texts]
            vals = [v for v in vals if v]
            if len(vals) >= 2:
                return vals[0], vals[-1]
            if len(vals) == 1:
                return vals[0], ""
        return raw.strip(), ""

    def _candidate_device_names(self, device_name: str) -> List[str]:
        """Return ordered candidate names to match for `device_name` on the Devices tab."""
        names: List[str] = []
        clean = (device_name or "").strip()
        if clean:
            names.append(clean)
        fallback_commissioned = getattr(self.driver, "_ghp_commissioned_tile_name", None)
        if fallback_commissioned and str(fallback_commissioned).strip():
            fb = str(fallback_commissioned).strip()
            if self._norm(fb) not in {self._norm(n) for n in names}:
                names.append(fb)
        return names

    def _find_visible_tile_for_name(self, target_name: str) -> Optional[
        Tuple[WebElement, str, str]]:
        """Search currently visible device tile buttons for `target_name` (0s implicit wait)."""
        target_norm = self._norm(target_name)
        if not target_norm:
            return None
        escaped = target_name.strip().replace('"', '\\"')
        predicate = (
            'type == "XCUIElementTypeButton" AND '
            f'(name CONTAINS[c] "{escaped}" OR label CONTAINS[c] "{escaped}")'
        )
        with self._fast_probe():
            try:
                buttons = self.driver.find_elements(IOS_PREDICATE_BY, predicate)
            except WebDriverException:
                buttons = []
            exact_match: Optional[Tuple[WebElement, str, str]] = None
            prefix_match: Optional[Tuple[WebElement, str, str]] = None
            for btn in buttons:
                try:
                    if not btn.is_displayed():
                        continue
                    rect = btn.rect
                    # Exclude bottom TabBar buttons and top NavigationBar buttons
                    if rect.get("y", 0) < 80 or rect.get("y", 0) >= 750:
                        continue
                    title, status = self._split_tile_name_and_status(btn)
                    title_norm = self._norm(title)
                    if title_norm == target_norm:
                        exact_match = (btn, title, status)
                        break
                    if prefix_match is None and title_norm.startswith(target_norm):
                        prefix_match = (btn, title, status)
                except WebDriverException:
                    continue
        return exact_match or prefix_match

    def _scroll_devices_list(self, direction: str = "down") -> None:
        """Scroll the Devices ScrollView up or down cleanly."""
        try:
            win = self.driver.get_window_size()
            w = int(win.get("width", 390))
            h = int(win.get("height", 844))
        except Exception:
            w, h = 390, 844
        cx = w // 2
        if direction == "down":
            from_y, to_y = int(h * 0.68), int(h * 0.28)
        else:
            from_y, to_y = int(h * 0.28), int(h * 0.68)
        try:
            self.driver.execute_script(
                "mobile: dragFromToForDuration",
                {
                    "duration": 0.25,
                    "fromX": cx,
                    "fromY": from_y,
                    "toX": cx,
                    "toY": to_y,
                },
            )
        except WebDriverException:
            try:
                self.driver.execute_script("mobile: scroll", {"direction": direction})
            except WebDriverException:
                pass
        time.sleep(1.0)

    def _ensure_tile_in_safe_tap_zone(self, tile: WebElement, target_name: str) -> WebElement:
        """Nudge scroll if tile sits underneath the floating bottom Tab Bar (y > screen_h - 110)."""
        try:
            win = self.driver.get_window_size()
            h = int(win.get("height", 844))
            rect = tile.rect
            cy = int(rect["y"] + rect["height"] / 2)
            if cy > h - 110:
                self._scroll_devices_list("down")
                refreshed = self._find_visible_tile_for_name(target_name)
                if refreshed is not None:
                    return refreshed[0]
            elif cy < 95:
                self._scroll_devices_list("up")
                refreshed = self._find_visible_tile_for_name(target_name)
                if refreshed is not None:
                    return refreshed[0]
        except Exception:
            pass
        return tile

    def _locate_device_tile_with_scroll(
            self, device_name: str, max_scrolls: int = 8
    ) -> Optional[Tuple[WebElement, str, str]]:
        """Locate `(tile, title, status)` for `device_name` on the Devices tab, scrolling if needed."""
        candidates = self._candidate_device_names(device_name)
        if not candidates:
            return None

        # First check current viewport, then scroll to top if needed, then scan down
        for cand in candidates:
            hit = self._find_visible_tile_for_name(cand)
            if hit is not None:
                return hit

        for _ in range(2):
            self._scroll_devices_list("up")
        for step in range(max_scrolls + 1):
            for cand in candidates:
                hit = self._find_visible_tile_for_name(cand)
                if hit is not None:
                    return hit
            if step < max_scrolls:
                self._scroll_devices_list("down")
        return None

    def check_device_online_status(self, device_name: str, max_scrolls: int = 6) -> str:
        """Return 'online', 'offline', or 'missing' for `device_name` on the Devices tab."""
        page = GHPDevicePage._resolve_page(self)
        page.go_to_tab("Devices")
        hit = page._locate_device_tile_with_scroll(device_name, max_scrolls=max_scrolls)
        if hit is None:
            return "missing"
        _tile, title, status = hit
        status_low = status.strip().lower()
        page._logger.info(f"[Device Status] Found tile '{title}' with status='{status}'")
        if any(kw in status_low for kw in page.OFFLINE_STATUS_KEYWORDS):
            return "offline"
        return "online"

    def _is_camera_live_page_open(self, device_name: str = "") -> bool:
        """Return True if GHP has navigated away from Devices tab into Camera Live View."""
        with self._fast_probe():
            try:
                markers = self.driver.find_elements(IOS_PREDICATE_BY,
                                                    self.CAMERA_LIVE_MARKERS_PREDICATE)
                for m in markers:
                    if m.is_displayed():
                        return True
            except WebDriverException:
                pass
            if device_name and not self._is_tab_bar_visible():
                escaped = device_name.strip().replace('"', '\\"')
                try:
                    titles = self.driver.find_elements(
                        IOS_PREDICATE_BY,
                        f'type == "XCUIElementTypeStaticText" AND (name == "{escaped}" OR label == "{escaped}")',
                    )
                    if any(t.is_displayed() for t in titles):
                        return True
                except WebDriverException:
                    pass
        return False

    def is_device_exist_device_page(self, device_name: Optional[str] = None,
                                    max_scrolls: int = 8) -> bool:
        """Verify that `device_name` exists on the GHP Devices tab."""
        page = GHPDevicePage._resolve_page(self)
        target = str(device_name or getattr(self, "device_name", "") or "").strip()
        page._logger.info(f"Checking if device '{target}' exists on GHP Devices tab...")
        page.go_to_tab("Devices")
        hit = page._locate_device_tile_with_scroll(target, max_scrolls=max_scrolls)
        if hit is None:
            msg = f"Device '{target}' was NOT found on GHP Devices tab after {max_scrolls} scrolls."
            page._logger.error(msg)
            BasePage.capture_failure_screenshot(page.driver, reason=msg, force=False, lock=True)
            raise AssertionError(msg)
        _tile, title, status = hit
        page._logger.info(
            f"Confirmed device '{title}' exists on GHP Devices tab (status='{status}').")
        return True

    def enter_device_page(self, device_name: Optional[str] = None, max_scrolls: int = 8) -> bool:
        """Tap the target camera tile on GHP Devices tab and verify Camera Live View opens."""
        page = GHPDevicePage._resolve_page(self)
        target = str(device_name or getattr(self, "device_name", "") or "").strip()
        page._logger.info(f"Entering GHP Camera Live page for '{target}'...")
        if page._is_camera_live_page_open(target):
            page._logger.info(f"Already on Camera Live page for '{target}'.")
            return True

        page.go_to_tab("Devices")
        hit = page._locate_device_tile_with_scroll(target, max_scrolls=max_scrolls)
        if hit is None:
            msg = f"Cannot enter device page: '{target}' not found on GHP Devices tab."
            page._logger.error(msg)
            BasePage.capture_failure_screenshot(page.driver, reason=msg, force=False, lock=True)
            raise AssertionError(msg)

        tile, title, status = hit
        tile = page._ensure_tile_in_safe_tap_zone(tile, title)
        for attempt in range(1, 3):
            page._logger.info(
                f"Tapping camera tile '{title}' (status='{status}', attempt {attempt}/2)..."
            )
            page._tap_element_or_coords(tile, desc=f"Camera tile '{title}'")
            deadline = time.time() + 6.0
            while time.time() < deadline:
                if page._is_camera_live_page_open(title):
                    page._logger.info(f"Successfully entered Camera Live page for '{title}'.")
                    return True
                time.sleep(0.5)
            fresh = page._find_visible_tile_for_name(title)
            if fresh is not None:
                tile = fresh[0]

        msg = f"Tapped camera tile '{title}' on GHP Devices tab, but Camera Live page did not open."
        page._logger.error(msg)
        BasePage.capture_failure_screenshot(page.driver, reason=msg, force=False, lock=True)
        raise AssertionError(msg)
