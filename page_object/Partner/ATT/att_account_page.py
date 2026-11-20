"""Page object for AT&T Connected Life Account page & GHP Google Account sign-in verification."""

import re
import time
from typing import Any, List, Optional, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException

from common.base_page import BasePage
from page_object.Partner.ATT.att_common import (
    ATTBasePage,
    IOS_PREDICATE_BY,
)
from utils import logging_utils

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_BOILERPLATE_TOKENS = {
    "google account",
    "sign out",
    "sign out of google account",
    "sign in",
    "disconnect",
    "unlink",
    "manage",
    "remove",
    "loading",
    "loading...",
}
_NEGATIVE_SUBSTRINGS = (
    "not signed in",
    "disconnected",
    "not connected",
    "not linked",
    "unlinked",
)


class ATTAccountPage(ATTBasePage):
    """Verifies that the GHP Google Account row on the AT&T `Account` sheet remains signed in."""

    ACCOUNT_NAVBAR_PREDICATE: str = (
        'type == "XCUIElementTypeNavigationBar" AND ('
        'name IN {"Account", "Google account settings"} '
        'OR label IN {"Account", "Google account settings"})'
    )

    SETTINGS_MODAL_STACK_PREDICATE: str = (
        'name IN {"Account", "Google account settings", "Home settings", '
        '"Disconnect Google account", "Sign out of Google account", '
        '"System settings", "Smart home integrations"} '
        'OR label IN {"Account", "Google account settings", "Home settings", '
        '"Disconnect Google account", "Sign out of Google account", '
        '"System settings", "Smart home integrations"} '
        'OR name BEGINSWITH "Account " OR label BEGINSWITH "Account "'
    )

    GOOGLE_SETTINGS_MARKER_PREDICATE: str = (
        'name IN {"Google account settings", "Disconnect Google account", "Sign out of Google account"} '
        'OR label IN {"Google account settings", "Disconnect Google account", "Sign out of Google account"}'
    )

    GOOGLE_ACCOUNT_ROW_PREDICATE: str = (
        'type IN {"XCUIElementTypeButton", "XCUIElementTypeCell"} AND ('
        'name CONTAINS[c] "Google account" OR label CONTAINS[c] "Google account" '
        'OR value CONTAINS[c] "Google account")'
    )

    GOOGLE_ACCOUNT_TEXT_PREDICATE: str = (
        'type == "XCUIElementTypeStaticText" AND ('
        'name CONTAINS[c] "Google account" OR label CONTAINS[c] "Google account" '
        'OR value CONTAINS[c] "Google account")'
    )

    def __init__(self, driver: WebDriver, timeout: float = 10.0) -> None:
        super().__init__(driver, timeout=timeout)
        self._logger = logging_utils.get_logger(__name__, "att_account_page")

    @classmethod
    def _resolve_page(cls, ctx: Any) -> "ATTAccountPage":
        if isinstance(ctx, cls):
            return ctx
        existing = getattr(ctx, "attaccountpage", None)
        if isinstance(existing, cls):
            return existing
        session = getattr(ctx, "session", None)
        if session is not None and isinstance(getattr(session, "attaccountpage", None), cls):
            return session.attaccountpage
        page = cls(ctx.driver)
        if session is not None:
            page.session = session
        return page

    def is_on_account_page(self) -> bool:
        """Return True if the AT&T `Account` modal sheet is currently displayed."""
        with self._att_fast_probe():
            try:
                for nav in self.driver.find_elements(IOS_PREDICATE_BY,
                                                     self.ACCOUNT_NAVBAR_PREDICATE):
                    if self._att_is_element_on_screen(nav):
                        return True
                for row in self.driver.find_elements(
                        IOS_PREDICATE_BY, self.GOOGLE_ACCOUNT_ROW_PREDICATE
                ):
                    if self._att_is_element_on_screen(row):
                        return True
            except WebDriverException:
                pass
        return False

    def _is_on_google_account_settings_page(self) -> bool:
        """Return True when inside `Google account settings` (Screenshot C)."""
        with self._att_fast_probe():
            try:
                for el in self.driver.find_elements(
                        IOS_PREDICATE_BY, self.GOOGLE_SETTINGS_MARKER_PREDICATE
                ):
                    if self._att_is_element_on_screen(el):
                        return True
            except WebDriverException:
                pass
        return False

    def _is_in_settings_modal_stack(self) -> bool:
        """Return True when on any settings modal (`Home settings` / `Account` / `Google account settings`)."""
        with self._att_fast_probe():
            try:
                for el in self.driver.find_elements(
                        IOS_PREDICATE_BY, self.SETTINGS_MODAL_STACK_PREDICATE
                ):
                    if self._att_is_element_on_screen(el):
                        return True
            except WebDriverException:
                pass
        return self.is_on_account_page()

    def _find_google_account_container(self) -> Optional[WebElement]:
        """Locate the Google Account button/cell on the Account sheet (excluding Disconnect/Sign out)."""
        with self._att_fast_probe():
            try:
                buttons = self.driver.find_elements(
                    IOS_PREDICATE_BY,
                    'type == "XCUIElementTypeButton" AND ('
                    'name CONTAINS[c] "Google account" OR label CONTAINS[c] "Google account")',
                )
                for b in buttons:
                    if not self._att_is_element_on_screen(b):
                        continue
                    b_txt = self._att_read_attr(b, ("label", "name", "value")).lower()
                    if b_txt.startswith(("sign out", "disconnect")):
                        continue
                    return b
            except WebDriverException:
                pass

            cell = self._find_google_account_cell()
            if cell is not None:
                return cell

            try:
                texts = self.driver.find_elements(IOS_PREDICATE_BY,
                                                  self.GOOGLE_ACCOUNT_TEXT_PREDICATE)
                for t in texts:
                    if self._att_is_element_on_screen(t):
                        return t
            except WebDriverException:
                pass
        return None

    def _find_google_account_cell(self) -> Optional[WebElement]:
        """Locate the `XCUIElementTypeCell` enclosing the `'Google account'` row."""
        with self._att_fast_probe():
            try:
                cells = self.driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeCell")
                for cell in cells:
                    if not self._att_is_element_on_screen(cell):
                        continue
                    try:
                        sts = cell.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText")
                        for st in sts:
                            txt = self._att_read_attr(st, ("value", "label", "name"))
                            low = txt.lower()
                            if "google account" in low and not low.startswith("sign out"):
                                return cell
                    except WebDriverException:
                        continue
            except WebDriverException:
                pass
        return None

    def _read_nearby_google_account_card_texts(self, anchor: WebElement) -> List[str]:
        """Fallback: collect StaticTexts vertically adjacent within the Google account card bounds."""
        try:
            anchor_rect = anchor.rect or {}
        except WebDriverException:
            return []
        if not anchor_rect or anchor_rect.get("height", 0) <= 0:
            return []
        anchor_y = anchor_rect.get("y", 0)
        card_top = anchor_y - 12
        card_bottom = anchor_y + max(75, anchor_rect.get("height", 44) + 25)
        found: List[str] = []
        with self._att_fast_probe():
            try:
                for st in self.driver.find_elements(AppiumBy.CLASS_NAME,
                                                    "XCUIElementTypeStaticText"):
                    if not self._att_is_element_on_screen(st):
                        continue
                    r = getattr(st, "rect", None) or {}
                    sy = r.get("y", -1)
                    if card_top <= sy <= card_bottom:
                        val = self._att_read_attr(st, ("value", "label", "name"))
                        if val and val not in found and val.lower() != "location services":
                            found.append(val)
            except WebDriverException:
                pass
        return found

    def _read_google_account_row_parts(self, container: WebElement) -> Tuple[str, List[str]]:
        """Return `(combined_text, unique_parts)` from the Google Account container and its children."""
        parts: List[str] = []

        def _add_raw(raw_text: str) -> None:
            if not raw_text:
                return
            for chunk in re.split(r"[\r\n]+", raw_text):
                chunk = chunk.strip()
                if not chunk:
                    continue
                if "," in chunk:
                    for sub in chunk.split(","):
                        sub = sub.strip()
                        if sub and sub not in parts:
                            parts.append(sub)
                elif chunk not in parts:
                    parts.append(chunk)

        for attr in ("label", "name", "value"):
            try:
                val = container.get_attribute(attr)
                if val and str(val).strip():
                    _add_raw(str(val).strip())
            except WebDriverException:
                continue

        with self._att_fast_probe():
            try:
                for st in container.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText"):
                    val = self._att_read_attr(st, ("value", "label", "name"))
                    if val:
                        _add_raw(val)
            except WebDriverException:
                pass

        return ", ".join(parts), parts

    @classmethod
    def evaluate_google_account_parts(
            cls, combined_text: str, parts: List[str]
    ) -> Tuple[bool, str, str]:
        """Classify Google Account row state.

        Returns `(is_signed_in, status_kind, detail_or_account)`:
        - `status_kind`: `'SIGNED_IN'`, `'SIGNED_OUT'`, or `'PENDING'` (transient loading / incomplete)
        """
        low = (combined_text or "").strip().lower()
        norm_parts = [p.strip().lower() for p in parts if p.strip()]
        # Compact line-wrapped whitespace around email fragments if any
        compact_text = re.sub(r"\s+", " ", combined_text or "").strip()
        unwrapped_text = re.sub(r"[\r\n]+", "", combined_text or "")
        email_match = _EMAIL_RE.search(compact_text) or _EMAIL_RE.search(unwrapped_text)

        # Screenshot 7: `"Google account, Not signed in, Sign in"`
        has_explicit_sign_in_prompt = (
                any(neg in low for neg in _NEGATIVE_SUBSTRINGS)
                or any(p == "sign in" or p == "not signed in" for p in norm_parts)
                or bool(re.search(r"\bsign\s+in\b", low))
        )
        if has_explicit_sign_in_prompt:
            return False, "SIGNED_OUT", combined_text

        if email_match:
            return True, "SIGNED_IN", email_match.group(0)

        meaningful = [
            p
            for p in parts
            if p.strip()
               and p.strip().lower() not in _BOILERPLATE_TOKENS
               and not any(neg in p.strip().lower() for neg in _NEGATIVE_SUBSTRINGS)
        ]
        if meaningful:
            return True, "SIGNED_IN", meaningful[0]

        return False, "PENDING", combined_text or "<empty>"

    def verify_google_account_signed_in(self, timeout: float = 8.0) -> str:
        """Step 6: Verify GHP Google Account on Account page still displays a signed-in account."""
        page = ATTAccountPage._resolve_page(self)

        # Wait for Account page & locate Google Account row (scroll slightly if needed)
        container: Optional[WebElement] = None
        find_deadline = time.time() + timeout
        scrolled_down = False
        while time.time() < find_deadline:
            container = page._find_google_account_container()
            if container is not None:
                break
            if page.is_on_account_page() and not scrolled_down and (
                    time.time() + timeout * 0.5) > find_deadline:
                page._att_scroll_vertical("down")
                scrolled_down = True
            time.sleep(0.4)

        if container is None:
            msg = "GHP 'Google account' row was NOT found on AT&T Account page."
            page._logger.error(msg)
            BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
            raise AssertionError(msg)

        # Poll briefly in case account status finishes loading asynchronously after Account opens
        settle_deadline = time.time() + 4.0
        last_kind = "PENDING"
        last_detail = ""
        last_combined = ""
        while True:
            refreshed = page._find_google_account_container() or container
            combined, parts = page._read_google_account_row_parts(refreshed)
            signed_in, kind, detail = page.evaluate_google_account_parts(combined, parts)

            # Fallback if Button only exposed 'Google account' while email lives in parent Cell or adjacent StaticText
            if kind == "PENDING":
                cell = page._find_google_account_cell()
                if cell is not None and cell is not refreshed:
                    c_combined, c_parts = page._read_google_account_row_parts(cell)
                    s2, k2, d2 = page.evaluate_google_account_parts(c_combined, c_parts)
                    if k2 != "PENDING":
                        combined, parts = c_combined, c_parts
                        signed_in, kind, detail = s2, k2, d2

            if kind == "PENDING":
                nearby = page._read_nearby_google_account_card_texts(refreshed)
                if nearby:
                    merged_parts = list(dict.fromkeys(parts + nearby))
                    merged_combined = ", ".join(merged_parts)
                    s3, k3, d3 = page.evaluate_google_account_parts(merged_combined, merged_parts)
                    if k3 != "PENDING":
                        combined, parts = merged_combined, merged_parts
                        signed_in, kind, detail = s3, k3, d3

            last_kind, last_detail, last_combined = kind, detail, combined
            if signed_in:
                page._logger.info(
                    f"[ATT Account] GHP Google Account verified SIGNED IN: '{detail}' "
                    f"(row='{combined}')"
                )
                page._verify_linked_google_account_settings(refreshed, detail)
                sess = getattr(page, "session", None)
                if sess is not None:
                    sess.last_google_account = detail
                try:
                    setattr(page.driver, "_att_google_account", detail)
                except Exception:
                    pass
                return detail
            if kind == "SIGNED_OUT" or time.time() >= settle_deadline:
                break
            time.sleep(0.5)

        msg = (
            f"GHP Google Account is NOT showing a signed-in account on AT&T Account page "
            f"(state={last_kind}, detail='{last_combined or last_detail}')."
        )
        page._logger.error(msg)
        BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
        raise AssertionError(msg)

    def _verify_linked_google_account_settings(
            self, google_account_row: WebElement, expected_account: str
    ) -> None:
        """Click `Google account, <email>` -> enter `Google account settings` and verify link status."""
        if self._is_on_google_account_settings_page():
            entered = True
        else:
            entered = False
            target_row: Optional[WebElement] = google_account_row
            for attempt in range(1, 3):
                if target_row is None:
                    target_row = self._find_google_account_container()
                if target_row is None:
                    break
                self._logger.info(
                    f"[ATT Account] Clicking Google account row ('{expected_account}', attempt {attempt}/2) "
                    "to check `Google account settings`..."
                )
                self._att_tap_element_or_coords(
                    target_row,
                    desc=f"Google account ({expected_account})",
                    prefer_coords=(attempt > 1),
                )
                deadline = time.time() + 5.0
                while time.time() < deadline:
                    if self._is_on_google_account_settings_page():
                        entered = True
                        break
                    time.sleep(0.4)
                if entered:
                    break
                target_row = self._find_google_account_container()

        if not entered:
            self._logger.warning(
                "[ATT Account Settings] `Google account settings` subpage did not open on tap; "
                "relying on signed-in email verified on `Account` page."
            )
            return

        # Inspect `Google account`, `Google home`, and `Disconnect Google account` inside Screenshot C
        found_texts: List[str] = []
        has_disconnect = False
        with self._att_fast_probe():
            try:
                for b in self.driver.find_elements(
                        IOS_PREDICATE_BY,
                        'type == "XCUIElementTypeButton" AND ('
                        'name CONTAINS[c] "Disconnect Google account" OR '
                        'label CONTAINS[c] "Disconnect Google account")',
                ):
                    if self._att_is_element_on_screen(b):
                        has_disconnect = True
                        break
            except WebDriverException:
                pass
            try:
                for st in self.driver.find_elements(AppiumBy.CLASS_NAME,
                                                    "XCUIElementTypeStaticText"):
                    if not self._att_is_element_on_screen(st):
                        continue
                    val = self._att_read_attr(st, ("value", "label", "name"))
                    if val:
                        found_texts.append(val)
            except WebDriverException:
                pass

        joined_compact = re.sub(r"[\r\n]+", "", " | ".join(found_texts))
        if "not signed in" in joined_compact.lower():
            msg = (
                "GHP Google Account showed 'Not signed in' inside `Google account settings`: "
                f"{joined_compact[:200]}"
            )
            self._logger.error(msg)
            BasePage.capture_failure_screenshot(self.driver, reason=msg, force=True, lock=True)
            raise AssertionError(msg)

        email_match = _EMAIL_RE.search(joined_compact)
        linked_home = ""
        for idx, txt in enumerate(found_texts[:-1]):
            if txt.strip().lower() == "google home":
                linked_home = found_texts[idx + 1].strip()
                break

        if not email_match and not has_disconnect:
            msg = (
                "Inside `Google account settings`, neither signed-in email nor "
                "`Disconnect Google account` was present — GHP account may be unlinked."
            )
            self._logger.error(msg)
            BasePage.capture_failure_screenshot(self.driver, reason=msg, force=True, lock=True)
            raise AssertionError(msg)

        self._logger.info(
            f"[ATT Account Settings] Verified linked GHP Google Account='{email_match.group(0) if email_match else expected_account}'"
            f"{f' | Google home={linked_home!r}' if linked_home else ''}"
            f" | Disconnect button={has_disconnect}"
        )

    def close_account_page(self, timeout: float = 8.0) -> bool:
        """Unwind `Google account settings` (<) -> `Account` (<) -> `Home settings` (X) back to Devices."""
        page = ATTAccountPage._resolve_page(self)
        win_w, win_h = page._att_window_size()

        for step in range(1, 5):
            if not page._is_in_settings_modal_stack():
                if step > 1:
                    page._logger.info("[ATT Account] Closed settings/account sheets cleanly.")
                return True

            clicked = False
            for attempt in range(1, 3):
                page._wait_until_top_notification_disappears(force=True)
                back_btn: Optional[WebElement] = None
                with page._att_fast_probe():
                    try:
                        btns = page.driver.find_elements(
                            AppiumBy.XPATH,
                            '//XCUIElementTypeNavigationBar//XCUIElementTypeButton',
                        )
                        for b in btns:
                            rect = getattr(b, "rect", None) or {}
                            if (
                                    page._att_is_element_on_screen(b)
                                    and rect.get("y", 0) < 140
                                    and rect.get("x", 0) < int(win_w * 0.35)
                            ):
                                back_btn = b
                                break
                    except WebDriverException:
                        back_btn = None

                    if back_btn is None:
                        try:
                            all_btns = page.driver.find_elements(
                                AppiumBy.CLASS_NAME, "XCUIElementTypeButton"
                            )
                            for b in all_btns:
                                rect = getattr(b, "rect", None) or {}
                                if (
                                        page._att_is_element_on_screen(b)
                                        and rect.get("y", 0) < 140
                                        and rect.get("x", 0) < int(win_w * 0.30)
                                        and rect.get("width", 0) <= 90
                                        and rect.get("height", 0) <= 70
                                ):
                                    back_btn = b
                                    break
                        except WebDriverException:
                            pass

                if back_btn is not None:
                    page._logger.info(
                        f"[ATT Account] Closing modal sheet (step {step}, attempt {attempt}/2)..."
                    )
                    clicked = page._att_tap_element_or_coords(
                        back_btn,
                        desc=f"Settings modal back/close (step {step})",
                        prefer_coords=(attempt > 1),
                    )
                elif attempt == 1:
                    page._logger.info(
                        f"[ATT Account] Tapping top-left modal close coordinate fallback (step {step})..."
                    )
                    try:
                        page.driver.execute_script("mobile: tap", {"x": 28, "y": 75})
                        clicked = True
                    except WebDriverException:
                        pass
                else:
                    page._logger.info("[ATT Account] Swiping down modal sheet fallback...")
                    page._att_drag(win_w // 2, int(win_h * 0.16), win_w // 2, int(win_h * 0.88))
                    clicked = True

                time.sleep(0.8)
                if not page._is_in_settings_modal_stack() or clicked:
                    break

        if not page._is_in_settings_modal_stack():
            page._logger.info("[ATT Account] Returned cleanly from settings/account sheets.")
            return True

        page._logger.warning(
            "[ATT Account] Settings sheet still open after unwind; next step will recover.")
        return False
