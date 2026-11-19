"""Page object for AT&T Connected Life Camera Live Stream verification and navigation back."""
from dataclasses import dataclass
import time
from typing import Any, List, Optional, Tuple
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException
from common import constants
from common.base_page import BasePage
from page_object.Partner.ATT.att_common import (
    ATTBasePage,
    IOS_PREDICATE_BY,
)
from utils import logging_utils


@dataclass
class _ATTLiveSample:
    t: float
    is_live: bool
    detail: str = ""


class ATTCameraLivePage(ATTBasePage):
    """Waits for top-left `'Live'` indicator, verifies stability for 5~10s, and navigates back."""
    DEFAULT_WAIT_LIVE_TIMEOUT_S: float = 60.0
    DEFAULT_VERIFY_DURATION_S: float = 8.0  # within 5~10s window requested
    DEFAULT_CHECK_INTERVAL_S: float = 1.0
    TOP_LEFT_LIVE_PREDICATE: str = (
        'type == "XCUIElementTypeStaticText" AND '
        '(name == "Live" OR label == "Live" OR value == "Live")'
    )
    PLAYER_ERROR_PREDICATE: str = (
        'type IN {"XCUIElementTypeStaticText", "XCUIElementTypeAlert"} AND ('
        'label CONTAINS[c] "Unable to play" '
        'OR label CONTAINS[c] "camera is offline" '
        'OR label CONTAINS[c] "device is offline" '
        'OR label CONTAINS[c] "connection failed" '
        'OR label CONTAINS[c] "failed to load")'
    )
    BACK_TO_ROOM_BTN_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND name == "BackButton"'
    )
    ROOM_SETTINGS_BTN_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND ('
        'name == "group_settings_navbar_button" OR label == "Room Settings")'
    )

    def __init__(self, driver: WebDriver, timeout: float = 10.0) -> None:
        super().__init__(driver, timeout=timeout)
        self._logger = logging_utils.get_logger(__name__, "att_camera_live")

    @classmethod
    def _resolve_page(cls, ctx: Any) -> "ATTCameraLivePage":
        if isinstance(ctx, cls):
            return ctx
        existing = getattr(ctx, "attcameralivepage", None)
        if isinstance(existing, cls):
            return existing
        session = getattr(ctx, "session", None)
        if session is not None and isinstance(getattr(session, "attcameralivepage", None), cls):
            return session.attcameralivepage
        page = cls(ctx.driver)
        if session is not None:
            page.session = session
        return page

    def _is_app_in_foreground(self) -> bool:
        bundle_id = self._att_bundle_id()
        fg_state = getattr(constants, "APP_STATE_FOREGROUND", 4)
        try:
            if hasattr(self.driver, "query_app_state"):
                return self.driver.query_app_state(bundle_id) == fg_state
        except WebDriverException:
            return False
        return True

    def _has_top_left_live_indicator(self) -> Tuple[bool, str]:
        """Detect top-left player badge `Live` (`x=68, y=119` in Screenshot 4, distinct from timeline `'LIVE'`)."""
        win_w, win_h = self._att_window_size()
        max_y = int(win_h * 0.38)
        max_x = int(win_w * 0.60)
        with self._att_fast_probe():
            try:
                candidates = self.driver.find_elements(IOS_PREDICATE_BY,
                                                       self.TOP_LEFT_LIVE_PREDICATE)
            except WebDriverException as err:
                return False, f"probe_error:{str(err)[:60]}"
            for el in candidates:
                if not self._att_is_element_on_screen(el, require_visible_attr=True):
                    continue
                txt = self._att_read_attr(el, ("value", "label", "name"))
                # Strict Title Case check avoids lower timeline header `"LIVE"`
                if txt != "Live":
                    continue
                try:
                    rect = el.rect or {}
                except WebDriverException:
                    continue
                if rect.get("y", win_h) <= max_y and rect.get("x", win_w) <= max_x:
                    return True, f"Live@({rect.get('x')},{rect.get('y')})"
            try:
                for err_el in self.driver.find_elements(IOS_PREDICATE_BY,
                                                        self.PLAYER_ERROR_PREDICATE):
                    if self._att_is_element_on_screen(err_el, require_visible_attr=True):
                        return False, f"error:{self._att_read_attr(err_el)[:60]}"
            except WebDriverException:
                pass
        return False, "waiting_for_live"

    def wait_and_verify_live_stream(
            self,
            device_name: Optional[str] = None,
            wait_live_timeout_s: Optional[float] = None,
            verify_duration_s: Optional[float] = None,
            check_interval_s: Optional[float] = None,
    ) -> bool:
        """Step 3b: Wait for top-left `'Live'` text, then verify stream stays Live for 5~10s."""
        page = ATTCameraLivePage._resolve_page(self)
        target_dev = str(device_name or getattr(self, "device_name", "") or "").strip()
        wait_timeout = float(
            wait_live_timeout_s
            if wait_live_timeout_s is not None
            else getattr(constants, "ATT_LIVE_WAIT_TIMEOUT_S", page.DEFAULT_WAIT_LIVE_TIMEOUT_S)
        )
        duration = float(
            verify_duration_s
            if verify_duration_s is not None
            else getattr(constants, "ATT_LIVE_VERIFY_SECONDS", page.DEFAULT_VERIFY_DURATION_S)
        )
        interval = float(
            check_interval_s
            if check_interval_s is not None
            else getattr(constants, "ATT_LIVE_CHECK_INTERVAL_S", page.DEFAULT_CHECK_INTERVAL_S)
        )
        dev_status = getattr(getattr(page, "session", None), "last_device_status", None) or getattr(
            page.driver, "_att_device_status", "Unknown"
        )
        # Phase A: Wait up to wait_timeout for top-left 'Live' badge to appear
        page._logger.info(
            f"[ATT Live] Waiting up to {wait_timeout:.0f}s for top-left 'Live' indicator "
            f"(device='{target_dev}', room_status='{dev_status}')..."
        )
        wait_start = time.time()
        last_wait_detail = ""
        reached_live = False
        while (time.time() - wait_start) < wait_timeout:
            if not page._is_app_in_foreground():
                last_wait_detail = "app_not_foreground"
                break
            is_live, detail = page._has_top_left_live_indicator()
            last_wait_detail = detail
            if is_live:
                reached_live = True
                page._logger.info(
                    f"[ATT Live] Top-left 'Live' appeared after {time.time() - wait_start:.1f}s ({detail}). "
                    f"Starting {duration:.0f}s live verification..."
                )
                break
            time.sleep(0.5)
        if not reached_live:
            msg = (
                f"[NEVER_LIVE] AT&T Camera '{target_dev}' (device_status='{dev_status}') "
                f"did not show top-left 'Live' within {wait_timeout:.0f}s (last_state={last_wait_detail})."
            )
            page._logger.error(msg)
            BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
            raise AssertionError(msg)
        # Phase B: Verify top-left 'Live' remains active for 5~10s
        samples: List[_ATTLiveSample] = []
        verify_start = time.time()
        while (time.time() - verify_start) < duration:
            elapsed = time.time() - verify_start
            if not page._is_app_in_foreground():
                samples.append(_ATTLiveSample(elapsed, False, "app_not_foreground"))
                break
            is_live, detail = page._has_top_left_live_indicator()
            samples.append(_ATTLiveSample(elapsed, is_live, detail))
            if is_live:
                page._logger.info(
                    f"[ATT Live] Streaming smoothly ({elapsed:.1f}s / {duration:.0f}s | {detail})"
                )
            else:
                page._logger.warning(
                    f"[ATT Live] Top-left 'Live' missing at {elapsed:.1f}s ({detail})"
                )
            remaining = duration - (time.time() - verify_start)
            if remaining > 0:
                time.sleep(min(interval, remaining))
        final_live, final_detail = (
            page._has_top_left_live_indicator()
            if page._is_app_in_foreground()
            else (False, "app_not_foreground")
        )
        samples.append(_ATTLiveSample(time.time() - verify_start, final_live, final_detail))
        non_live_count = sum(1 for s in samples if not s.is_live)
        live_count = sum(1 for s in samples if s.is_live)
        if not final_live or live_count == 0:
            timeline_str = " -> ".join(
                f"{s.t:.1f}s:{'LIVE' if s.is_live else s.detail}" for s in samples[:10]
            )
            msg = (
                f"[NOT_LIVE_AT_END] AT&T Camera '{target_dev}' dropped top-left 'Live' during "
                f"{duration:.0f}s check (live_samples={live_count}/{len(samples)}, "
                f"final={final_detail}). Timeline: {timeline_str}"
            )
            page._logger.error(msg)
            BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
            raise AssertionError(msg)
        page._logger.info(
            f"[ATT Live] SUCCESS: Top-left 'Live' verified for {time.time() - verify_start:.1f}s "
            f"(live_samples={live_count}/{len(samples)}, non_live={non_live_count})."
        )
        return True

    def click_back_to_room(
            self, room_name: Optional[str] = None, timeout: float = 8.0
    ) -> bool:
        """Step 4 (1st Back): Click top-left BackButton (`label='<room_name>'`) -> return to Room page."""
        page = ATTCameraLivePage._resolve_page(self)
        target_room = str(room_name or getattr(self, "room_name", "Attic") or "Attic").strip()
        win_w, _ = page._att_window_size()
        for attempt in range(1, 3):
            back_btn: Optional[WebElement] = None
            with page._att_fast_probe():
                try:
                    for b in page.driver.find_elements(IOS_PREDICATE_BY,
                                                       page.BACK_TO_ROOM_BTN_PREDICATE):
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
                    f"[ATT Live] Clicking BackButton (label='{target_room}', attempt {attempt}/2) "
                    "to return to Room page..."
                )
                page._att_tap_element_or_coords(
                    back_btn,
                    desc=f"Live BackButton -> {target_room}",
                    prefer_coords=(attempt > 1),
                )
            else:
                page._logger.info(
                    f"[ATT Live] BackButton not found via query; tapping top-left nav fallback (attempt {attempt}/2)..."
                )
                try:
                    page.driver.execute_script("mobile: tap", {"x": 38, "y": 69})
                except WebDriverException:
                    pass
            deadline = time.time() + min(timeout, 5.0)
            while time.time() < deadline:
                with page._att_fast_probe():
                    try:
                        in_room = any(
                            page._att_is_element_on_screen(e)
                            for e in page.driver.find_elements(
                                IOS_PREDICATE_BY,
                                'name == "group_settings_navbar_button" OR '
                                '(name == "BackButton" AND label == "Devices")',
                            )
                        )
                    except WebDriverException:
                        in_room = False
                if in_room:
                    page._logger.info(f"[ATT Live] Returned to Room page '{target_room}'.")
                    return True
                time.sleep(0.4)
        msg = f"Failed to navigate back from Live Stream to Room page '{target_room}'."
        page._logger.error(msg)
        BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
        raise AssertionError(msg)
