"""Page object for AT&T Connected Life Devices tab (tab switching, Rooms lookup, top-left Settings)."""

import time
from typing import Any, List, Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException

from common.base_page import BasePage
from page_object.Partner.ATT.att_common import (
    ATTBasePage,
    IOS_CLASS_CHAIN_BY,
    IOS_PREDICATE_BY,
)
from utils import logging_utils

logger = logging_utils.get_logger(__name__, "att_devices_page")


class ATTDevicesPage(ATTBasePage):
    """Handles AT&T Connected Life Home/Devices tab navigation, room entry, and top-left Settings."""

    DEVICES_TAB_LOCATORS = (
        (AppiumBy.ACCESSIBILITY_ID, "devices_tab_button"),
        (
            IOS_PREDICATE_BY,
            'type == "XCUIElementTypeButton" AND (name == "devices_tab_button" OR label == "Devices")',
        ),
    )

    DEVICES_NAVBAR_PREDICATE: str = (
        'type == "XCUIElementTypeNavigationBar" AND (name == "Devices" OR label == "Devices")'
    )

    NON_DEVICES_TAB_NAVBAR_PREDICATE: str = (
        'type == "XCUIElementTypeNavigationBar" AND ('
        'name IN {"Dashboard", "Activity", "Automations", "Alarms"} '
        'OR label IN {"Dashboard", "Activity", "Automations", "Alarms"})'
    )

    DEVICES_PAGE_MARKER_PREDICATE: str = (
        '(type IN {"XCUIElementTypeOther", "XCUIElementTypeStaticText"} AND '
        'name IN {"Device filters", "Rooms", "In your home"}) '
        'OR (type == "XCUIElementTypeCell" AND name == "cameras_button") '
        'OR (type == "XCUIElementTypeButton" AND name == "devices_tab_button" AND value == "1")'
    )

    SETTINGS_NAVBAR_BTN_LOCATORS = (
        (AppiumBy.ACCESSIBILITY_ID, "app_settings_navbar_button"),
        (
            IOS_PREDICATE_BY,
            'type == "XCUIElementTypeButton" AND ('
            'name == "app_settings_navbar_button" OR label == "Settings")',
        ),
    )

    ROOMS_HEADER_PREDICATE: str = (
        '(type IN {"XCUIElementTypeOther", "XCUIElementTypeStaticText"}) AND ('
        'name == "Rooms" OR label == "Rooms")'
    )

    ROOM_CARD_PREDICATE: str = (
        'name BEGINSWITH "group_" AND name ENDSWITH "_item"'
    )

    ACCOUNT_DRAWER_BTN_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND ('
        'name == "Account" OR name BEGINSWITH "Account " '
        'OR label == "Account" OR label BEGINSWITH "Account ")'
    )

    HOME_SETTINGS_MARKER_PREDICATE: str = (
        'name IN {"Home settings", "System settings", "Smart home integrations", "Switch accounts"} '
        'OR label IN {"Home settings", "System settings", "Smart home integrations", "Switch accounts"} '
        'OR name BEGINSWITH "Account " OR label BEGINSWITH "Account "'
    )

    SUBPAGE_OR_MODAL_PREDICATE: str = (
        '(type == "XCUIElementTypeButton" AND name IN {"BackButton", "group_settings_navbar_button"}) '
        'OR (type == "XCUIElementTypeNavigationBar" AND name IN {'
        '"Dashboard", "Activity", "Automations", "Alarms", "Account", "Google account settings"}) '
        'OR name IN {"Home settings", "System settings", "Smart home integrations", '
        '"Google account settings", "Disconnect Google account", "Sign out of Google account"} '
        'OR label IN {"Home settings", "System settings", "Smart home integrations", '
        '"Google account settings", "Disconnect Google account", "Sign out of Google account"}'
    )

    def __init__(self, driver: WebDriver, timeout: float = 10.0) -> None:
        super().__init__(driver, timeout=timeout)
        self._logger = logging_utils.get_logger(__name__, "att_devices_page")

    @classmethod
    def _resolve_page(cls, ctx: Any) -> "ATTDevicesPage":
        if isinstance(ctx, cls):
            return ctx
        existing = getattr(ctx, "attdevicespage", None)
        if isinstance(existing, cls):
            return existing
        session = getattr(ctx, "session", None)
        if session is not None and isinstance(getattr(session, "attdevicespage", None), cls):
            return session.attdevicespage
        page = cls(ctx.driver)
        if session is not None:
            page.session = session
        return page

    def _is_subpage_or_modal_open(self) -> bool:
        """Return True when a pushed child page (Room / Live) or modal sheet (`Home settings` / `Account`) is open."""
        win_w, _ = self._att_window_size()
        with self._att_fast_probe():
            try:
                for el in self.driver.find_elements(
                        IOS_PREDICATE_BY, self.SUBPAGE_OR_MODAL_PREDICATE
                ):
                    if self._att_is_element_on_screen(el, require_visible_attr=True):
                        return True
                for btn in self.driver.find_elements(
                        IOS_PREDICATE_BY,
                        'type == "XCUIElementTypeButton" AND (name == "Settings" OR label == "Settings")',
                ):
                    rect = getattr(btn, "rect", None) or {}
                    if (
                            self._att_is_element_on_screen(btn, require_visible_attr=True)
                            and rect.get("y", 0) < 140
                            and rect.get("x", 0) >= int(win_w * 0.60)
                    ):
                        return True
            except WebDriverException:
                pass
        return False

    def is_on_devices_page(self) -> bool:
        """Return True only when the AT&T `Devices` tab (NOT Dashboard, Room, Live, or modal) is active."""
        win_w, _ = self._att_window_size()
        with self._att_fast_probe():
            try:
                # Reject pushed sub-pages (Room / Live), modal sheets (Home settings / Account),
                # and other tabs (Dashboard / Activity / Automations / Alarms) first.
                if self._is_subpage_or_modal_open():
                    return False
                for dash_btn in self.driver.find_elements(
                        IOS_PREDICATE_BY,
                        'type == "XCUIElementTypeButton" AND name == "dashboard_tab_button" AND value == "1"',
                ):
                    if self._att_is_element_on_screen(dash_btn, require_visible_attr=True):
                        return False

                for nav in self.driver.find_elements(IOS_PREDICATE_BY,
                                                     self.DEVICES_NAVBAR_PREDICATE):
                    if self._att_is_element_on_screen(nav, require_visible_attr=True):
                        return True
                for title_el in self.driver.find_elements(
                        IOS_PREDICATE_BY,
                        'type == "XCUIElementTypeStaticText" AND (name == "Devices" OR label == "Devices")',
                ):
                    rect = getattr(title_el, "rect", None) or {}
                    if (
                            self._att_is_element_on_screen(title_el, require_visible_attr=True)
                            and rect.get("y", 999) < 140
                            and 40 <= rect.get("x", 0) <= int(win_w * 0.75)
                    ):
                        return True
                for marker in self.driver.find_elements(
                        IOS_PREDICATE_BY, self.DEVICES_PAGE_MARKER_PREDICATE
                ):
                    if self._att_is_element_on_screen(marker, require_visible_attr=True):
                        return True
            except WebDriverException:
                pass
        return False

    def _is_tab_bar_visible(self) -> bool:
        with self._att_fast_probe():
            try:
                bars = self.driver.find_elements(IOS_CLASS_CHAIN_BY, "**/XCUIElementTypeTabBar")
                return any(
                    self._att_is_element_on_screen(bar, require_visible_attr=True) for bar in bars)
            except WebDriverException:
                pass
        return False

    def _find_devices_tab_button(self) -> Optional[WebElement]:
        win_w, win_h = self._att_window_size()
        with self._att_fast_probe():
            for by, loc in self.DEVICES_TAB_LOCATORS:
                try:
                    for elem in self.driver.find_elements(by, loc):
                        rect = getattr(elem, "rect", None) or {}
                        # Bottom tab bar sits near the bottom of screen (e.g. y >= win_h * 0.72)
                        if rect.get("width", 0) > 0 and rect.get("y", 0) >= int(win_h * 0.70):
                            return elem
                except WebDriverException:
                    continue
        return None

    def _dismiss_transient_overlays_to_tabs(self, max_steps: int = 8) -> None:
        """Step back out of Google account settings / Account / Home settings / Room / Live until Tabs appear."""
        win_w, win_h = self._att_window_size()
        for step in range(1, max_steps + 1):
            if self.is_on_devices_page():
                return
            subpage_or_modal = self._is_subpage_or_modal_open()
            if not subpage_or_modal and self._is_tab_bar_visible():
                return
            self._att_dismiss_system_alert_if_present()
            self._wait_until_top_notification_disappears(force=True)
            clicked = False
            use_coords = step % 2 == 0
            with self._att_fast_probe():
                # 0. Explicit BackButton (Room -> Devices, Live -> Room)
                try:
                    for btn in self.driver.find_elements(
                            IOS_PREDICATE_BY,
                            'type == "XCUIElementTypeButton" AND name == "BackButton"',
                    ):
                        rect = getattr(btn, "rect", None) or {}
                        if (
                                self._att_is_element_on_screen(btn, require_visible_attr=True)
                                and rect.get("y", 0) < 140
                                and rect.get("x", 0) < int(win_w * 0.40)
                        ):
                            if self._att_tap_element_or_coords(
                                    btn, desc="BackButton", prefer_coords=use_coords
                            ):
                                clicked = True
                                break
                except WebDriverException:
                    pass

                # 1. Sheet / NavBar back or close buttons (e.g. Google account settings '<', Account '<', Home settings 'X')
                if not clicked:
                    try:
                        nav_btns = self.driver.find_elements(
                            AppiumBy.XPATH,
                            '//XCUIElementTypeNavigationBar//XCUIElementTypeButton',
                        )
                        for btn in nav_btns:
                            rect = getattr(btn, "rect", None) or {}
                            b_name = self._att_read_attr(btn, ("name",))
                            if b_name == "app_settings_navbar_button":
                                continue
                            if (
                                    self._att_is_element_on_screen(btn, require_visible_attr=True)
                                    and rect.get("y", 0) < 140
                                    and rect.get("x", 0) < int(win_w * 0.35)
                            ):
                                if self._att_tap_element_or_coords(
                                        btn, desc="NavBar Back/Close", prefer_coords=use_coords
                                ):
                                    clicked = True
                                    break
                    except WebDriverException:
                        pass

                # 2. Standalone top-left Back/Close button outside NavigationBar (e.g. modal 'X' / '<' circle)
                if not clicked:
                    try:
                        btns = self.driver.find_elements(
                            AppiumBy.CLASS_NAME, "XCUIElementTypeButton"
                        )
                        for btn in btns:
                            rect = getattr(btn, "rect", None) or {}
                            b_name = self._att_read_attr(btn, ("name",))
                            if b_name == "app_settings_navbar_button":
                                continue
                            if (
                                    self._att_is_element_on_screen(btn, require_visible_attr=True)
                                    and rect.get("y", 0) < 140
                                    and rect.get("x", 0) < int(win_w * 0.30)
                                    and rect.get("width", 0) <= 90
                                    and rect.get("height", 0) <= 70
                            ):
                                if self._att_tap_element_or_coords(
                                        btn, desc="Top-left Back/Close", prefer_coords=use_coords
                                ):
                                    clicked = True
                                    break
                    except WebDriverException:
                        pass

            if clicked:
                time.sleep(0.8)
            still_in_modal = (
                    self._is_home_settings_page_open_probe() or self._is_account_page_open_probe()
            )
            if not clicked or (still_in_modal and step >= 2):
                if still_in_modal:
                    self._wait_until_top_notification_disappears(force=True)
                    self._logger.info(
                        "[ATT Devices] Settings modal still open; swiping down to dismiss..."
                    )
                    self._att_drag(
                        win_w // 2, int(win_h * 0.28), win_w // 2, int(win_h * 0.88)
                    )
                    time.sleep(0.8)
                    continue
                if not clicked:
                    break

    def go_to_devices_tab(self, timeout: float = 12.0) -> bool:
        """Ensure AT&T Connected Life is on the `Devices` main tab (Screenshot 1 -> Screenshot 2)."""
        page = ATTDevicesPage._resolve_page(self)
        page._wait_until_top_notification_disappears()
        page._dismiss_transient_overlays_to_tabs()
        if page.is_on_devices_page():
            page._logger.info("[ATT Devices] Already on Devices page.")
            return True

        deadline = time.time() + timeout
        while time.time() < deadline:
            page._att_dismiss_system_alert_if_present()
            if page.is_on_devices_page():
                page._logger.info("[ATT Devices] Devices page became visible.")
                return True
            tab_btn = page._find_devices_tab_button()
            if tab_btn is not None:
                page._logger.info(
                    "[ATT Devices] Clicking bottom 'Devices' tab (`devices_tab_button`)...")
                page._att_tap_element_or_coords(tab_btn, desc="Devices Tab")
                wait_end = min(deadline, time.time() + 4.0)
                while time.time() < wait_end:
                    if page.is_on_devices_page():
                        page._logger.info("[ATT Devices] Entered Devices page successfully.")
                        return True
                    time.sleep(0.4)
            time.sleep(0.5)

        msg = "Failed to navigate to AT&T `Devices` tab."
        page._logger.error(msg)
        BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
        raise AssertionError(msg)

    def _find_visible_room_element(self, room_name: str) -> Optional[WebElement]:
        """Locate the Room card (e.g. `group_attic_item` / `Attic`) in the Devices tab viewport."""
        if self._is_subpage_or_modal_open():
            return None
        target_norm = self._att_norm(room_name)
        target_slug = self._att_slug(room_name)
        expected_item_name = f"group_{target_slug}_item"
        escaped_name = self._att_escape_predicate(room_name.strip())
        _, win_h = self._att_window_size()

        with self._att_fast_probe():
            # Layer 1: Exact AT&T group card container (`group_<room>_item`)
            try:
                for elem in self.driver.find_elements(AppiumBy.ACCESSIBILITY_ID,
                                                      expected_item_name):
                    if self._att_is_element_on_screen(
                            elem, require_visible_attr=True, min_y=90, max_y_margin=85
                    ):
                        return elem
            except WebDriverException:
                pass

            # Layer 2: Any `group_*_item` element whose label/name matches `room_name`
            try:
                for elem in self.driver.find_elements(IOS_PREDICATE_BY, self.ROOM_CARD_PREDICATE):
                    if not self._att_is_element_on_screen(
                            elem, require_visible_attr=True, min_y=90, max_y_margin=85
                    ):
                        continue
                    el_name = self._att_read_attr(elem, ("name",))
                    el_label = self._att_read_attr(elem, ("label", "value"))
                    if (
                            self._att_norm(el_label) == target_norm
                            or self._att_norm(el_name) == self._att_norm(expected_item_name)
                    ):
                        return elem
            except WebDriverException:
                pass

            # Layer 3: Fallback matching text/cell in content body (`Attic` StaticText or Other)
            try:
                candidates = self.driver.find_elements(
                    IOS_PREDICATE_BY,
                    'type IN {"XCUIElementTypeOther", "XCUIElementTypeCell", '
                    '"XCUIElementTypeStaticText", "XCUIElementTypeButton"} AND ('
                    f'name ==[c] "{escaped_name}" OR label ==[c] "{escaped_name}" OR '
                    f'value ==[c] "{escaped_name}")',
                )
                for elem in candidates:
                    rect = getattr(elem, "rect", None) or {}
                    if not self._att_is_element_on_screen(elem, min_y=95, max_y_margin=90):
                        continue
                    # Avoid NavigationBar headers (y < 95) or TabBar (y > win_h - 90)
                    if rect.get("y", 0) >= win_h - 90:
                        continue
                    return elem
            except WebDriverException:
                pass
        return None

    def _rooms_carousel_y(self) -> Optional[int]:
        """Estimate the vertical center Y of the horizontal `Rooms` carousel row if visible."""
        _, win_h = self._att_window_size()
        with self._att_fast_probe():
            try:
                for hdr in self.driver.find_elements(IOS_PREDICATE_BY, self.ROOMS_HEADER_PREDICATE):
                    if self._att_is_element_on_screen(hdr):
                        r = hdr.rect
                        cy = int(r.get("y", 250) + r.get("height", 24) + 55)
                        if 140 <= cy <= win_h - 110:
                            return cy
            except WebDriverException:
                pass
        return None

    def _locate_room_with_scroll(self, room_name: str, max_scrolls: int = 4) -> Optional[
        WebElement]:
        hit = self._find_visible_room_element(room_name)
        if hit is not None:
            return hit

        # Check horizontal Rooms carousel if multiple rooms exist horizontally
        win_w, _ = self._att_window_size()
        row_y = self._rooms_carousel_y()
        if row_y is not None:
            for _ in range(3):
                self._att_drag(int(win_w * 0.82), row_y, int(win_w * 0.18), row_y, duration=0.25)
                time.sleep(0.6)
                hit = self._find_visible_room_element(room_name)
                if hit is not None:
                    return hit

        # Vertical scroll fallback (top then down)
        for _ in range(2):
            self._att_scroll_vertical("up")
            hit = self._find_visible_room_element(room_name)
            if hit is not None:
                return hit

        for _ in range(max_scrolls):
            self._att_scroll_vertical("down")
            hit = self._find_visible_room_element(room_name)
            if hit is not None:
                return hit
        return None

    def _is_room_opened(self, room_name: str) -> bool:
        """Check whether the Room page (`<room_name>` header or `group_settings_navbar_button`) opened."""
        escaped_room = self._att_escape_predicate(room_name.strip())
        with self._att_fast_probe():
            try:
                for btn in self.driver.find_elements(
                        IOS_PREDICATE_BY, 'name == "group_settings_navbar_button"'
                ):
                    if self._att_is_element_on_screen(btn):
                        return True
                for nav in self.driver.find_elements(
                        IOS_PREDICATE_BY,
                        f'type == "XCUIElementTypeNavigationBar" AND name ==[c] "{escaped_room}"',
                ):
                    if self._att_is_element_on_screen(nav):
                        return True
            except WebDriverException:
                pass
        return False

    def open_room(self, room_name: Optional[str] = None, timeout: float = 10.0) -> bool:
        """Step 1: On `Devices` tab, click `room_name` (e.g. `Attic`) and verify Room page opens."""
        page = ATTDevicesPage._resolve_page(self)
        target_room = str(room_name or getattr(self, "room_name", "Attic") or "Attic").strip()
        page._wait_until_top_notification_disappears()
        page.go_to_devices_tab()

        if page._is_room_opened(target_room):
            page._logger.info(f"[ATT Room] Already inside room '{target_room}'.")
            return True

        room_elem = page._locate_room_with_scroll(target_room)
        if room_elem is None:
            msg = f"Room '{target_room}' was NOT found on AT&T Devices page."
            page._logger.error(msg)
            BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
            raise AssertionError(msg)

        for attempt in range(1, 3):
            page._logger.info(f"[ATT Room] Clicking room '{target_room}' (attempt {attempt}/2)...")
            page._att_tap_element_or_coords(
                room_elem,
                desc=f"Room '{target_room}'",
                prefer_coords=(attempt > 1),
            )
            deadline = time.time() + min(timeout, 6.0)
            while time.time() < deadline:
                if page._is_room_opened(target_room):
                    page._logger.info(f"[ATT Room] Successfully entered room '{target_room}'.")
                    return True
                time.sleep(0.4)
            page._wait_until_top_notification_disappears(force=True)
            if not page.is_on_devices_page():
                page._logger.warning(
                    f"[ATT Room] No longer on Devices page after clicking room '{target_room}'; "
                    "unwinding back to Devices tab before retry..."
                )
                page.go_to_devices_tab()
            refreshed = page._find_visible_room_element(target_room)
            if refreshed is not None:
                room_elem = refreshed

        msg = f"Clicked room '{target_room}' on Devices page, but Room page did not open."
        page._logger.error(msg)
        BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
        raise AssertionError(msg)

    def _find_top_left_setting_button(self) -> Optional[WebElement]:
        win_w, _ = self._att_window_size()
        with self._att_fast_probe():
            fallback_btn: Optional[WebElement] = None
            for by, loc in self.SETTINGS_NAVBAR_BTN_LOCATORS:
                try:
                    for btn in self.driver.find_elements(by, loc):
                        rect = getattr(btn, "rect", None) or {}
                        if rect.get("y", 0) >= 150 or rect.get("x", 0) >= int(win_w * 0.40):
                            continue
                        if self._att_is_element_on_screen(btn, require_visible_attr=True):
                            return btn
                        if fallback_btn is None and self._att_is_element_on_screen(btn):
                            fallback_btn = btn
                except WebDriverException:
                    continue
        return fallback_btn

    def _is_home_settings_page_open_probe(self) -> bool:
        """Return True when the `Home settings` sheet (Screenshot A) is visible."""
        if self._is_account_page_open_probe():
            return False
        with self._att_fast_probe():
            try:
                for marker in self.driver.find_elements(
                        IOS_PREDICATE_BY, self.HOME_SETTINGS_MARKER_PREDICATE
                ):
                    if self._att_is_element_on_screen(marker):
                        return True
            except WebDriverException:
                pass
        return False

    def _find_home_settings_account_button(self) -> Optional[WebElement]:
        """Locate the profile/account button (`Account Ios Test, ...`) inside `Home settings`."""
        with self._att_fast_probe():
            # 1. Button whose name/label starts with 'Account ' (Screenshot A: 'Account Ios Test, test19@...')
            try:
                for btn in self.driver.find_elements(
                        IOS_PREDICATE_BY, self.ACCOUNT_DRAWER_BTN_PREDICATE
                ):
                    if self._att_is_element_on_screen(btn, min_y=95):
                        return btn
            except WebDriverException:
                pass

            # 2. Button containing generic avatar icon `icon48X48GenericAvatar`
            try:
                for btn in self.driver.find_elements(
                        AppiumBy.XPATH,
                        '//XCUIElementTypeButton[.//XCUIElementTypeImage[@name="icon48X48GenericAvatar"]]',
                ):
                    if self._att_is_element_on_screen(btn, min_y=95):
                        return btn
            except WebDriverException:
                pass

            # 3. Fallback: button showing AT&T email (`@`) on Home settings body
            try:
                for btn in self.driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeButton"):
                    if not self._att_is_element_on_screen(btn, min_y=95):
                        continue
                    txt = self._att_read_attr(btn, ("name", "label", "value"))
                    low = txt.lower()
                    if "@" in txt and not low.startswith(("switch", "sign")):
                        return btn
            except WebDriverException:
                pass
        return None

    def _is_account_page_open_probe(self) -> bool:
        with self._att_fast_probe():
            try:
                navs = self.driver.find_elements(
                    IOS_PREDICATE_BY,
                    'type == "XCUIElementTypeNavigationBar" AND ('
                    'name IN {"Account", "Google account settings"} '
                    'OR label IN {"Account", "Google account settings"})',
                )
                if any(self._att_is_element_on_screen(n) for n in navs):
                    return True
                titles = self.driver.find_elements(
                    IOS_PREDICATE_BY,
                    'type == "XCUIElementTypeStaticText" AND ('
                    'name IN {"Account", "Google account settings"} '
                    'OR label IN {"Account", "Google account settings"})',
                )
                for t in titles:
                    rect = getattr(t, "rect", None) or {}
                    if self._att_is_element_on_screen(t) and rect.get("y", 999) < 140:
                        return True
                google_rows = self.driver.find_elements(
                    IOS_PREDICATE_BY,
                    'name CONTAINS[c] "Google account" OR label CONTAINS[c] "Google account"',
                )
                if any(self._att_is_element_on_screen(g) for g in google_rows):
                    return True
            except WebDriverException:
                pass
        return False

    def click_top_left_setting_button(self, timeout: float = 12.0) -> bool:
        """Step 5: Click `app_settings_navbar_button` -> enter `Home settings` -> click `Account ...` -> `Account` page."""
        page = ATTDevicesPage._resolve_page(self)
        page._wait_until_top_notification_disappears(force=True)
        if page._is_account_page_open_probe():
            page._logger.info("[ATT Settings] Already on Account page.")
            return True

        # Phase 1: Open `Home settings` if not already open
        home_settings_opened = page._is_home_settings_page_open_probe()
        if not home_settings_opened:
            page.go_to_devices_tab()
            for attempt in range(1, 3):
                page._wait_until_top_notification_disappears(force=True)
                if page._is_account_page_open_probe():
                    page._logger.info("[ATT Settings] Account page already open.")
                    return True
                if page._is_home_settings_page_open_probe():
                    home_settings_opened = True
                    page._logger.info("[ATT Settings] `Home settings` page is already open.")
                    break
                btn = page._find_top_left_setting_button()
                if btn is None:
                    break
                page._logger.info(
                    f"[ATT Settings] Clicking top-left Settings (`app_settings_navbar_button`, attempt {attempt}/2)..."
                )
                page._att_tap_element_or_coords(
                    btn,
                    desc="app_settings_navbar_button",
                    prefer_coords=(attempt > 1),
                )
                deadline = time.time() + min(timeout, 6.0)
                while time.time() < deadline:
                    if page._is_account_page_open_probe():
                        page._logger.info("[ATT Settings] Account page opened directly.")
                        return True
                    if page._is_home_settings_page_open_probe():
                        home_settings_opened = True
                        page._logger.info("[ATT Settings] Opened `Home settings` page.")
                        break
                    _cleared, notif_waited = page._wait_until_top_notification_disappears_timed()
                    if notif_waited > 0:
                        deadline += notif_waited
                        continue
                    time.sleep(0.4)
                if home_settings_opened:
                    break

        if page._is_account_page_open_probe():
            return True

        # Phase 2: Inside `Home settings`, click the Account button (`Account Ios Test, ...`)
        if home_settings_opened or page._is_home_settings_page_open_probe():
            for attempt in range(1, 3):
                page._wait_until_top_notification_disappears(force=True)
                acct_btn: Optional[WebElement] = None
                find_deadline = time.time() + min(timeout, 6.0)
                while time.time() < find_deadline:
                    if page._is_account_page_open_probe():
                        page._logger.info("[ATT Settings] Account page opened.")
                        return True
                    _cleared, notif_waited = page._wait_until_top_notification_disappears_timed()
                    if notif_waited > 0:
                        find_deadline += notif_waited
                    acct_btn = page._find_home_settings_account_button()
                    if acct_btn is not None:
                        break
                    time.sleep(0.5)
                if acct_btn is None:
                    break
                acct_label = page._att_read_attr(acct_btn, ("name", "label"))
                page._logger.info(
                    f"[ATT Settings] Clicking Account row in Home settings ('{acct_label}', attempt {attempt}/2)..."
                )
                page._att_tap_element_or_coords(
                    acct_btn,
                    desc=f"Home settings Account ('{acct_label}')",
                    prefer_coords=(attempt > 1),
                )
                deadline = time.time() + min(timeout, 6.0)
                while time.time() < deadline:
                    if page._is_account_page_open_probe():
                        page._logger.info("[ATT Settings] Entered `Account` page successfully.")
                        return True
                    time.sleep(0.4)

        msg = "Clicked top-left Settings (`app_settings_navbar_button`), but could not reach `Account` page."
        page._logger.error(msg)
        BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
        raise AssertionError(msg)
