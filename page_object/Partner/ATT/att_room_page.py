"""Page object for AT&T Connected Life Room page (refresh, device verification, status, entry)."""

import time
from typing import Any, List, Optional, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from common.base_page import BasePage
from page_object.Partner.ATT.att_common import (
    ATTBasePage,
    IOS_CLASS_CHAIN_BY,
    IOS_PREDICATE_BY,
)
from utils import logging_utils


class ATTRoomPage(ATTBasePage):
    """Handles AT&T Room screen: pull-to-refresh, camera check, Online/Offline check, Live entry."""

    ROOM_SETTINGS_BTN_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND ('
        'name == "group_settings_navbar_button" OR label == "Room Settings")'
    )

    ROOM_BACK_TO_DEVICES_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND ('
        'name == "BackButton" AND label == "Devices")'
    )

    GOOGLE_SIGN_IN_BANNER_PREDICATE: str = (
        'type IN {"XCUIElementTypeButton", "XCUIElementTypeStaticText", "XCUIElementTypeCell", "XCUIElementTypeOther"} '
        'AND (name CONTAINS[c] "Sign in to your Google account" '
        'OR label CONTAINS[c] "Sign in to your Google account" '
        'OR value CONTAINS[c] "Sign in to your Google account" '
        'OR name CONTAINS[c] "Google devices and room settings are unavailable" '
        'OR label CONTAINS[c] "Google devices and room settings are unavailable" '
        'OR value CONTAINS[c] "Google devices and room settings are unavailable")'
    )

    SIGNED_OUT_BANNER_PHRASES: Tuple[str, ...] = (
        "sign in to your google account",
        "google devices and room settings are unavailable",
    )

    OFFLINE_STATUS_KEYWORDS: Tuple[str, ...] = (
        "offline",
        "disconnected",
        "unavailable",
        "unreachable",
        "not connected",
    )

    ONLINE_STATUS_KEYWORDS: Tuple[str, ...] = (
        "online",
        "live",
        "connected",
        "ready",
    )

    def __init__(self, driver: WebDriver, timeout: float = 10.0) -> None:
        super().__init__(driver, timeout=timeout)
        self._logger = logging_utils.get_logger(__name__, "att_room_page")

    @classmethod
    def _resolve_page(cls, ctx: Any) -> "ATTRoomPage":
        if isinstance(ctx, cls):
            return ctx
        existing = getattr(ctx, "attroompage", None)
        if isinstance(existing, cls):
            return existing
        session = getattr(ctx, "session", None)
        if session is not None and isinstance(getattr(session, "attroompage", None), cls):
            return session.attroompage
        page = cls(ctx.driver)
        if session is not None:
            page.session = session
        return page

    def is_on_room_page(self, room_name: str = "") -> bool:
        """Return True if the Room page (`Attic`, etc.) is currently active."""
        with self._att_fast_probe():
            try:
                for btn in self.driver.find_elements(
                        IOS_PREDICATE_BY, self.ROOM_SETTINGS_BTN_PREDICATE
                ):
                    if self._att_is_element_on_screen(btn):
                        return True
                for btn in self.driver.find_elements(
                        IOS_PREDICATE_BY, self.ROOM_BACK_TO_DEVICES_PREDICATE
                ):
                    if self._att_is_element_on_screen(btn):
                        return True
                if room_name:
                    esc = self._att_escape_predicate(room_name.strip())
                    for nav in self.driver.find_elements(
                            IOS_PREDICATE_BY,
                            f'type == "XCUIElementTypeNavigationBar" AND name ==[c] "{esc}"',
                    ):
                        if self._att_is_element_on_screen(nav):
                            return True
            except WebDriverException:
                pass
        return False

    def refresh_room_page(self, spinner_timeout: float = 5.0) -> None:
        """Step 1b: Pull down to refresh the AT&T room page and wait for any loading spinner."""
        page = ATTRoomPage._resolve_page(self)
        page._logger.info("[ATT Room] Pulling down to refresh room page...")
        try:
            page._att_pull_down_to_refresh()
            time.sleep(0.5)
            spinner_locator = (IOS_CLASS_CHAIN_BY, "**/XCUIElementTypeActivityIndicator")
            with page._att_fast_probe():
                try:
                    WebDriverWait(page.driver, spinner_timeout).until(
                        EC.invisibility_of_element_located(spinner_locator)
                    )
                except Exception:
                    pass
            time.sleep(1.0)
            page._logger.info("[ATT Room] Room page refreshed.")
        except Exception as err:
            page._logger.warning(f"[ATT Room] Room refresh encountered non-fatal error: {err}")

    def _collect_cell_texts(self, cell: WebElement) -> List[str]:
        """Collect StaticText values inside a room device cell cleanly."""
        texts: List[str] = []
        with self._att_fast_probe():
            try:
                for st in cell.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText"):
                    val = self._att_read_attr(st, ("value", "label", "name"))
                    if val and val not in texts:
                        texts.append(val)
            except WebDriverException:
                pass
        return texts

    def _find_visible_device_cell(self, device_name: str) -> Optional[Tuple[WebElement, str, str]]:
        """Find visible `XCUIElementTypeCell` matching `device_name` -> `(cell, title, raw_status)`."""
        target_norm = self._att_norm(device_name)
        target_slug = self._att_slug(device_name)
        expected_item_name = f"{target_slug}_item"
        if not target_norm:
            return None

        with self._att_fast_probe():
            try:
                cells = self.driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeCell")
            except WebDriverException:
                cells = []

            for cell in cells:
                if not self._att_is_element_on_screen(cell, min_y=85):
                    continue
                c_label = self._att_read_attr(cell, ("label",))
                c_name = self._att_read_attr(cell, ("name",))
                c_value = self._att_read_attr(cell, ("value",))
                child_texts = self._collect_cell_texts(cell)

                matched = (
                        self._att_norm(c_label) == target_norm
                        or (target_slug and self._att_norm(c_name) == self._att_norm(
                    expected_item_name))
                        or any(self._att_norm(t) == target_norm for t in child_texts)
                )
                if not matched:
                    continue

                title = c_label or device_name
                raw_status = c_value
                if not raw_status:
                    for t in child_texts:
                        if self._att_norm(t) != target_norm and self._att_norm(t) != self._att_norm(
                                title):
                            raw_status = t
                            break
                return cell, title, raw_status
        return None

    def _locate_device_cell_with_scroll(
            self, device_name: str, max_scrolls: int = 5
    ) -> Optional[Tuple[WebElement, str, str]]:
        hit = self._find_visible_device_cell(device_name)
        if hit is not None:
            return hit

        for _ in range(2):
            self._att_scroll_vertical("up")
            hit = self._find_visible_device_cell(device_name)
            if hit is not None:
                return hit

        for step in range(max_scrolls):
            self._att_scroll_vertical("down")
            hit = self._find_visible_device_cell(device_name)
            if hit is not None:
                return hit
        return None

    @classmethod
    def classify_device_status(cls, raw_status: str) -> str:
        """Normalize cell value / status text into 'Online', 'Offline', or raw string."""
        low = (raw_status or "").strip().lower()
        if any(kw in low for kw in cls.OFFLINE_STATUS_KEYWORDS):
            return "Offline"
        if any(kw in low for kw in cls.ONLINE_STATUS_KEYWORDS):
            return "Online"
        return raw_status.strip() if raw_status and raw_status.strip() else "Unknown"

    def _find_google_sign_in_banner(self) -> Optional[str]:
        """Detect the Google account signed-out banner inside AT&T Room page, if visible."""
        with self._att_fast_probe():
            try:
                elems = self.driver.find_elements(
                    IOS_PREDICATE_BY, self.GOOGLE_SIGN_IN_BANNER_PREDICATE
                )
            except WebDriverException:
                elems = []
            for elem in elems:
                if not self._att_is_element_on_screen(elem, min_y=60):
                    continue
                banner_text = self._att_read_attr(elem, ("label", "name", "value"))
                low = banner_text.lower()
                if any(phrase in low for phrase in self.SIGNED_OUT_BANNER_PHRASES):
                    return banner_text
        return None

    def verify_room_google_account_signed_in(self, room_name: str = "") -> None:
        """Fail immediately when AT&T Room page displays 'Sign in to your Google account' banner."""
        page = ATTRoomPage._resolve_page(self)
        target_room = str(room_name or getattr(self, "room_name", "Attic") or "Attic").strip()
        banner_text = page._find_google_sign_in_banner()
        if banner_text:
            msg = (
                f"GHP Google Account is NOT signed in (logged out) on AT&T room '{target_room}' page "
                f"(state=SIGNED_OUT, banner='{banner_text}')."
            )
            page._logger.error(msg)
            BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
            raise AssertionError(msg)

    def check_device_presence_and_status(
            self, device_name: Optional[str] = None, room_name: Optional[str] = None
    ) -> str:
        """Steps 1c & 2: Confirm Google account is still signed in, confirm camera exists, and log status.

        Note: Fails immediately if the Room page displays the 'Sign in to your Google account'
        signed-out banner. Logs Online/Offline status and stores it on session/driver without
        failing on Offline, because Step 3 requires opening Live Stream regardless of status.
        """
        page = ATTRoomPage._resolve_page(self)
        target_dev = str(device_name or getattr(self, "device_name", "") or "").strip()
        target_room = str(room_name or getattr(self, "room_name", "Attic") or "Attic").strip()

        page.verify_room_google_account_signed_in(target_room)

        hit = page._locate_device_cell_with_scroll(target_dev)
        if hit is None:
            page.verify_room_google_account_signed_in(target_room)
            msg = (
                f"Camera device '{target_dev}' was NOT found in AT&T room '{target_room}' "
                "after refreshing room page."
            )
            page._logger.error(msg)
            BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
            raise AssertionError(msg)

        _cell, title, raw_status = hit
        status = page.classify_device_status(raw_status)
        page._logger.info(
            f"[ATT Room] Found camera '{title}' in room '{target_room}' | "
            f"Status: {status} (raw='{raw_status}') — proceeding to Live Stream check."
        )
        sess = getattr(page, "session", None)
        if sess is not None:
            sess.last_device_status = status
        try:
            setattr(page.driver, "_att_device_status", status)
        except Exception:
            pass
        return status

    def _is_live_stream_page_open(self, device_name: str, room_name: str = "") -> bool:
        """Return True when the screen has transitioned from Room page into Camera Live Stream."""
        if self.is_on_room_page("") and any(
                self._att_is_element_on_screen(e)
                for e in
                self._safe_find_elements(IOS_PREDICATE_BY, self.ROOM_SETTINGS_BTN_PREDICATE)
        ):
            return False

        escaped_dev = self._att_escape_predicate(device_name.strip())
        with self._att_fast_probe():
            try:
                # Top-right NavigationBar 'Settings' gear icon on Camera Live View (Screenshot 4)
                for btn in self.driver.find_elements(
                        IOS_PREDICATE_BY,
                        'type == "XCUIElementTypeButton" AND (name == "Settings" OR label == "Settings")',
                ):
                    rect = getattr(btn, "rect", None) or {}
                    if self._att_is_element_on_screen(btn) and rect.get("y", 0) < 140:
                        return True
                if escaped_dev:
                    for nav in self.driver.find_elements(
                            IOS_PREDICATE_BY,
                            f'type == "XCUIElementTypeNavigationBar" AND name ==[c] "{escaped_dev}"',
                    ):
                        if self._att_is_element_on_screen(nav):
                            return True
                # Live player UI controls (Live pill / Talk button / diagonal fullscreen arrow)
                for marker in self.driver.find_elements(
                        IOS_PREDICATE_BY,
                        'name IN {"Live", "Talk", "ico16SolidArrowDiagonalLeftRight"} OR '
                        'label IN {"Live", "Talk"}',
                ):
                    if self._att_is_element_on_screen(marker):
                        return True
            except WebDriverException:
                pass
        return False

    def _safe_find_elements(self, by: str, query: str) -> List[WebElement]:
        with self._att_fast_probe():
            try:
                return self.driver.find_elements(by, query)
            except WebDriverException:
                return []

    def enter_camera_live_stream(
            self,
            device_name: Optional[str] = None,
            room_name: Optional[str] = None,
            timeout: float = 10.0,
    ) -> bool:
        """Step 3a: Regardless of Online/Offline status, tap `device_name` cell to open Live Stream."""
        page = ATTRoomPage._resolve_page(self)
        target_dev = str(device_name or getattr(self, "device_name", "") or "").strip()
        target_room = str(room_name or getattr(self, "room_name", "Attic") or "Attic").strip()

        if page._is_live_stream_page_open(target_dev, target_room):
            page._logger.info(f"[ATT Room] Already on Live Stream page for '{target_dev}'.")
            return True

        hit = page._locate_device_cell_with_scroll(target_dev)
        if hit is None:
            msg = f"Cannot enter Live Stream: camera '{target_dev}' not found in room '{target_room}'."
            page._logger.error(msg)
            BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
            raise AssertionError(msg)

        cell, title, raw_status = hit
        for attempt in range(1, 3):
            page._logger.info(
                f"[ATT Room] Clicking camera '{title}' (status='{raw_status or 'Unknown'}', "
                f"attempt {attempt}/2) to enter Live Stream..."
            )
            # Tap upper-left/title region on fallback so we never accidentally hit bottom-right gear icon
            page._att_tap_element_or_coords(
                cell,
                desc=f"Camera tile '{title}'",
                prefer_coords=(attempt > 1),
                x_ratio=0.35,
                y_ratio=0.35,
            )
            deadline = time.time() + min(timeout, 6.0)
            while time.time() < deadline:
                if page._is_live_stream_page_open(title, target_room):
                    page._logger.info(f"[ATT Room] Entered Live Stream page for '{title}'.")
                    return True
                time.sleep(0.4)
            fresh = page._find_visible_device_cell(target_dev)
            if fresh is not None:
                cell = fresh[0]

        msg = f"Clicked camera '{title}' in room '{target_room}', but Live Stream page did not open."
        page._logger.error(msg)
        BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
        raise AssertionError(msg)

    def click_back_to_devices(self, timeout: float = 8.0) -> bool:
        """Step 4 (2nd Back): Click top-left BackButton (`label='Devices'`) on Room page -> Devices Home."""
        page = ATTRoomPage._resolve_page(self)
        win_w, _ = page._att_window_size()

        for attempt in range(1, 3):
            with page._att_fast_probe():
                back_btn: Optional[WebElement] = None
                try:
                    candidates = page.driver.find_elements(
                        IOS_PREDICATE_BY,
                        'type == "XCUIElementTypeButton" AND (name == "BackButton" OR label == "Devices")',
                    )
                    for b in candidates:
                        rect = getattr(b, "rect", None) or {}
                        if (
                                page._att_is_element_on_screen(b)
                                and rect.get("y", 0) < 140
                                and rect.get("x", 0) < int(win_w * 0.40)
                        ):
                            back_btn = b
                            break
                except WebDriverException:
                    back_btn = None

            if back_btn is not None:
                page._logger.info(
                    f"[ATT Room] Clicking BackButton to return to Devices page (attempt {attempt}/2)..."
                )
                page._att_tap_element_or_coords(
                    back_btn,
                    desc="Room BackButton -> Devices",
                    prefer_coords=(attempt > 1),
                )
            else:
                page._logger.info(
                    f"[ATT Room] BackButton not found via query; tapping top-left nav fallback (attempt {attempt}/2)..."
                )
                try:
                    page.driver.execute_script("mobile: tap", {"x": 38, "y": 69})
                except WebDriverException:
                    pass

            deadline = time.time() + min(timeout, 5.0)
            while time.time() < deadline:
                with page._att_fast_probe():
                    try:
                        on_devices = any(
                            page._att_is_element_on_screen(e)
                            for e in page.driver.find_elements(
                                IOS_PREDICATE_BY,
                                '(type == "XCUIElementTypeNavigationBar" AND name == "Devices") '
                                'OR (type == "XCUIElementTypeOther" AND name IN {"Device filters", "Rooms"}) '
                                'OR (type == "XCUIElementTypeButton" AND name == "devices_tab_button" AND value == "1")',
                            )
                        )
                    except WebDriverException:
                        on_devices = False
                if on_devices:
                    page._logger.info("[ATT Room] Returned to AT&T Devices Home page.")
                    return True
                time.sleep(0.4)

        msg = "Failed to navigate back from AT&T Room page to Devices Home page."
        page._logger.error(msg)
        BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
        raise AssertionError(msg)
