"""Page object for continuously verifying camera live stream stability and opening Settings in iGHP."""

import contextlib
from dataclasses import dataclass
from datetime import datetime
import re
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException

from common import constants
from common.base_page import BasePage
from page_object.iGHP.ghp_device_page import get_ghp_bundle_id
from utils import logging_utils

IOS_PREDICATE_BY = getattr(AppiumBy, "IOS_PREDICATE", "-ios predicate string")
IOS_CLASS_CHAIN_BY = getattr(AppiumBy, "IOS_CLASS_CHAIN", "-ios class chain")
_CLOCK_TEXT_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}(\s*[APap][Mm])?$")


class _LiveState:
    """Classification of a single live-view observation."""

    LIVE = "LIVE"
    RETRY = "RETRY"
    ERROR = "ERROR"
    NOT_LIVE = "NOT_LIVE"
    NO_PLAYER = "NO_PLAYER"
    APP_NOT_FOREGROUND = "APP_NOT_FOREGROUND"
    PROBE_ERROR = "PROBE_ERROR"


class _LiveFailure:
    """Stable failure categories matching GHACameraLivePage for unified dashboard grouping."""

    NEVER_LIVE = "NEVER_LIVE"
    NOT_LIVE_AT_END = "NOT_LIVE_AT_END"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"


@dataclass
class _LiveSample:
    t: float
    wall: float
    state: str
    detail: str = ""

    def describe(self) -> str:
        return f"{self.state}({self.detail})" if self.detail else self.state


@dataclass
class _LiveRetry:
    t: float
    wall: float
    index: int


@dataclass
class _LiveDrop:
    last_live: _LiveSample
    first_bad: _LiveSample
    states: List[str]
    recovered_at: Optional[float] = None
    retries: int = 0


def _clock(wall: float) -> str:
    return datetime.fromtimestamp(wall).strftime("%H:%M:%S")


class _LiveTimeline:
    """Records live-view samples / Retry clicks and renders a detailed failure report."""

    LINE_SEPARATOR = "\n"
    MAX_TIMELINE_EVENTS = 16
    MAX_DROPS_LISTED = 5
    MAX_BREAKDOWN_ITEMS = 3

    def __init__(self, duration: float, max_retries: int) -> None:
        self.duration = duration
        self.max_retries = max_retries
        self.start = time.time()
        self.samples: List[_LiveSample] = []
        self.retries: List[_LiveRetry] = []

    def elapsed(self) -> float:
        return time.time() - self.start

    def add_sample(
            self, state: str, detail: str, observed_at: float
    ) -> Tuple[_LiveSample, Optional[_LiveSample]]:
        prev = self.samples[-1] if self.samples else None
        sample = _LiveSample(t=observed_at - self.start, wall=observed_at, state=state,
                             detail=detail)
        self.samples.append(sample)
        return sample, prev

    def add_retry(self, index: int) -> None:
        now = time.time()
        self.retries.append(_LiveRetry(t=now - self.start, wall=now, index=index))

    @property
    def has_streamed_live(self) -> bool:
        return any(s.state == _LiveState.LIVE for s in self.samples)

    def _first_live(self) -> Optional[_LiveSample]:
        return next((s for s in self.samples if s.state == _LiveState.LIVE), None)

    def _last_live(self) -> Optional[_LiveSample]:
        return next((s for s in reversed(self.samples) if s.state == _LiveState.LIVE), None)

    def _time_by_state(self) -> Dict[str, float]:
        totals: Dict[str, float] = {}
        for prev, cur in zip(self.samples, self.samples[1:]):
            key = prev.describe()
            totals[key] = totals.get(key, 0.0) + (cur.t - prev.t)
        return totals

    def _drops(self) -> List[_LiveDrop]:
        drops: List[_LiveDrop] = []
        current: Optional[_LiveDrop] = None
        prev: Optional[_LiveSample] = None
        for s in self.samples:
            if s.state == _LiveState.LIVE:
                if current is not None:
                    current.recovered_at = s.t
                    drops.append(current)
                    current = None
            else:
                if current is None and prev is not None and prev.state == _LiveState.LIVE:
                    current = _LiveDrop(last_live=prev, first_bad=s, states=[])
                if current is not None and s.describe() not in current.states:
                    current.states.append(s.describe())
            prev = s
        if current is not None:
            drops.append(current)
        for d in drops:
            end = d.recovered_at if d.recovered_at is not None else float("inf")
            d.retries = sum(1 for r in self.retries if d.first_bad.t <= r.t <= end)
        return drops

    def summary(self) -> str:
        end_t = self.samples[-1].t if self.samples else self.elapsed()
        live_s = self._time_by_state().get(_LiveState.LIVE, 0.0)
        pct = 100.0 * live_s / end_t if end_t > 0 else 0.0
        return (
            f"live={live_s:.1f}s/{end_t:.1f}s ({pct:.0f}%), "
            f"drops={len(self._drops())}, retries={len(self.retries)}/{self.max_retries}"
        )

    def build_failure_message(self, category: str) -> str:
        headline_map = {
            _LiveFailure.NEVER_LIVE: (
                f"[{_LiveFailure.NEVER_LIVE}] GHP Camera never reached LIVE state within {int(self.duration)}s."
            ),
            _LiveFailure.NOT_LIVE_AT_END: (
                f"[{_LiveFailure.NOT_LIVE_AT_END}] GHP Camera dropped out of LIVE state and was not live at {int(self.duration)}s."
            ),
            _LiveFailure.RETRY_EXHAUSTED: (
                f"[{_LiveFailure.RETRY_EXHAUSTED}] GHP Camera live stream exceeded max retries ({self.max_retries})."
            ),
        }
        lines: List[str] = [
            headline_map.get(category, f"[{category}] GHP Camera live stream verification failed."),
            f"Summary: {self.summary()}",
        ]
        if self.samples:
            last = self.samples[-1]
            lines.append(f"Final state at {last.t:.1f}s ({_clock(last.wall)}): {last.describe()}")
        first_live = self._first_live()
        last_live = self._last_live()
        if first_live and last_live:
            lines.append(
                f"Live window: first={first_live.t:.1f}s ({_clock(first_live.wall)}), "
                f"last={last_live.t:.1f}s ({_clock(last_live.wall)})"
            )
        drops = self._drops()
        if drops:
            drop_parts: List[str] = []
            for d in drops[: self.MAX_DROPS_LISTED]:
                rec = f"recovered@{d.recovered_at:.1f}s" if d.recovered_at is not None else "unrecovered"
                drop_parts.append(
                    f"@{d.first_bad.t:.1f}s[{'->'.join(d.states[:3])}, retries={d.retries}, {rec}]"
                )
            lines.append("Drops: " + "; ".join(drop_parts))
        transitions: List[str] = []
        prev_desc: Optional[str] = None
        for s in self.samples:
            desc = s.describe()
            if desc != prev_desc:
                transitions.append(f"{s.t:.1f}s:{desc}")
                prev_desc = desc
        if transitions:
            lines.append("Timeline: " + " -> ".join(transitions[: self.MAX_TIMELINE_EVENTS]))
        return self.LINE_SEPARATOR.join(lines)


class GHPCameraLivePage(BasePage):
    """Continuously verifies GHP Camera Live View streaming and opens Camera Settings."""

    LIVE_RECONNECT_WAIT: float = 4.0
    LIVE_HEARTBEAT_INTERVAL: float = 5.0

    RETRY_BTN_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND ('
        'name IN {"Retry Connection", "Retry", "Turn Camera ON"} '
        'OR label IN {"Retry Connection", "Retry", "Turn Camera ON"} '
        'OR name CONTAINS[c] "Retry" OR label CONTAINS[c] "Retry")'
    )

    ERROR_TEXT_PREDICATE: str = (
        'type IN {"XCUIElementTypeStaticText", "XCUIElementTypeAlert"} AND ('
        'label CONTAINS[c] "Unable to play video" '
        'OR label CONTAINS[c] "device is offline" '
        'OR label CONTAINS[c] "stream has disconnected" '
        'OR label CONTAINS[c] "Error fetching camera state" '
        'OR label CONTAINS[c] "Stream removed" '
        'OR label CONTAINS[c] "Socket is not connected")'
    )

    NOT_LIVE_TEXT_PREDICATE: str = (
        'type == "XCUIElementTypeStaticText" AND ('
        'label IN {"Snapshot", "Loading...", "Connecting..."} '
        'OR value IN {"Snapshot", "Loading...", "Connecting..."})'
    )

    POSITIVE_LIVE_PREDICATE: str = (
        '(type == "XCUIElementTypeButton" AND ('
        'name IN {"mic.slash.fill", "mic.fill", "google_symbols/mic_off_symbol", '
        '"google_symbols/mic_symbol", "Turn Camera OFF"} '
        'OR label IN {"Microphone Off", "Microphone On", "Turn Camera OFF"})) '
        'OR (type == "XCUIElementTypeStaticText" AND (label == "Live" OR value == "Live"))'
    )

    PAGE_PRESENCE_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND ('
        'name IN {"BackButton", "xmark", "Settings", "Today", "google_symbols/menu_symbol"} '
        'OR label IN {"Home", "Close", "Settings", "Today"})'
    )

    SETTINGS_PAGE_MARKER_PREDICATE: str = (
        '(type == "XCUIElementTypeStaticText" AND ('
        'label IN {"Vendor Name", "Model Name", "Product Name", "Software Version", '
        '"Device Information", "Diagnostics Settings", "Microphone Settings"} '
        'OR value IN {"Vendor Name", "Model Name", "Product Name", "Software Version"})) '
        'OR (type == "XCUIElementTypeButton" AND ('
        'name IN {"Decommission", "Delete Device History"} '
        'OR label IN {"Decommission", "Delete Device History"}))'
    )

    INLINE_SETTINGS_BTN_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND (name == "Settings" OR label == "Settings")'
    )

    MENU_SYMBOL_BTN_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND '
        '(name == "google_symbols/menu_symbol" OR name CONTAINS "menu_symbol" OR name == "ellipsis.circle")'
    )

    def __init__(self, driver: WebDriver, timeout: float = 10.0) -> None:
        self.APP_BUNDLE_ID = get_ghp_bundle_id()
        super().__init__(driver, timeout=timeout)
        self._logger = logging_utils.get_logger(__name__, "ghp_camera_live")

    @classmethod
    def _resolve_page(cls, ctx: Any) -> "GHPCameraLivePage":
        if isinstance(ctx, cls):
            return ctx
        existing = getattr(ctx, "ghpcameralivepage", None)
        if isinstance(existing, cls):
            return existing
        session = getattr(ctx, "session", None)
        if session is not None and isinstance(getattr(session, "ghpcameralivepage", None), cls):
            return session.ghpcameralivepage
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

    def _read_text(self, elem: WebElement) -> str:
        for attr in ("label", "name", "value"):
            try:
                val = elem.get_attribute(attr)
                if val and str(val).strip():
                    return str(val).strip()
            except (StaleElementReferenceException, WebDriverException):
                continue
        try:
            return (elem.text or "").strip()
        except (StaleElementReferenceException, WebDriverException):
            return ""

    def _is_player_loading_spinner_visible(self) -> bool:
        """Return True if an ActivityIndicator spinner is displayed in the camera player area."""
        try:
            spinners = self.driver.find_elements(
                AppiumBy.CLASS_NAME, "XCUIElementTypeActivityIndicator"
            )
        except WebDriverException:
            return False
        for sp in spinners:
            try:
                if not sp.is_displayed():
                    continue
                rect = sp.rect
                if rect.get("y", 0) < 460:
                    return True
            except WebDriverException:
                continue
        return False

    def _has_live_timestamp_text(self) -> bool:
        """Check for live player timestamp text such as '3:10:04 PM' shown under the video player."""
        try:
            texts = self.driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText")
        except WebDriverException:
            return False
        for t in texts:
            try:
                if not t.is_displayed():
                    continue
                val = self._read_text(t)
                if val and _CLOCK_TEXT_RE.match(val):
                    return True
            except WebDriverException:
                continue
        return False

    def _live_classify(self) -> Tuple[str, str, Optional[WebElement]]:
        """Classify current GHP Camera Live screen into (_LiveState, detail, optional_retry_btn)."""
        bundle_id = get_ghp_bundle_id()
        try:
            if hasattr(self.driver, "query_app_state"):
                app_state = self.driver.query_app_state(bundle_id)
                if app_state != 4:
                    return _LiveState.APP_NOT_FOREGROUND, f"app_state={app_state}", None
        except WebDriverException as err:
            return _LiveState.PROBE_ERROR, str(err)[:80], None

        with self._fast_probe():
            try:
                # 1. Check Retry / Turn Camera ON actionable buttons first
                for btn in self.driver.find_elements(IOS_PREDICATE_BY, self.RETRY_BTN_PREDICATE):
                    try:
                        if btn.is_displayed():
                            txt = self._read_text(btn) or "Retry"
                            return _LiveState.RETRY, txt, btn
                    except WebDriverException:
                        continue

                # 2. Check non-retry error texts / alerts
                for err_el in self.driver.find_elements(IOS_PREDICATE_BY,
                                                        self.ERROR_TEXT_PREDICATE):
                    try:
                        if err_el.is_displayed():
                            return _LiveState.ERROR, self._read_text(err_el)[:80], None
                    except WebDriverException:
                        continue

                # 3. Check player loading spinner or Snapshot/Loading indicators
                if self._is_player_loading_spinner_visible():
                    return _LiveState.NOT_LIVE, "loading spinner", None

                for nl_el in self.driver.find_elements(IOS_PREDICATE_BY,
                                                       self.NOT_LIVE_TEXT_PREDICATE):
                    try:
                        if nl_el.is_displayed():
                            return _LiveState.NOT_LIVE, self._read_text(nl_el), None
                    except WebDriverException:
                        continue

                # 4. Check positive LIVE streaming indicators
                for live_el in self.driver.find_elements(IOS_PREDICATE_BY,
                                                         self.POSITIVE_LIVE_PREDICATE):
                    try:
                        if live_el.is_displayed():
                            return _LiveState.LIVE, "", None
                    except WebDriverException:
                        continue

                if self._has_live_timestamp_text():
                    return _LiveState.LIVE, "", None

                # 5. Distinguish waiting on live page vs completely left the live page
                for marker in self.driver.find_elements(IOS_PREDICATE_BY,
                                                        self.PAGE_PRESENCE_PREDICATE):
                    try:
                        if marker.is_displayed():
                            return _LiveState.NOT_LIVE, "waiting for live stream", None
                    except WebDriverException:
                        continue
                return _LiveState.NO_PLAYER, "camera live view not present", None
            except WebDriverException as err:
                return _LiveState.PROBE_ERROR, str(err)[:80], None

    def _live_take_sample(
            self, timeline: _LiveTimeline
    ) -> Tuple[_LiveSample, Optional[WebElement]]:
        state, detail, retry_btn = self._live_classify()
        sample, _ = timeline.add_sample(state, detail, time.time())
        return sample, retry_btn

    def _live_click_retry(self, retry_btn: Optional[WebElement]) -> bool:
        if retry_btn is None:
            return False
        rect = None
        try:
            rect = retry_btn.rect
        except WebDriverException:
            rect = None
        try:
            retry_btn.click()
            return True
        except WebDriverException:
            if rect:
                cx = int(rect["x"] + rect["width"] / 2)
                cy = int(rect["y"] + rect["height"] / 2)
                try:
                    self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                    return True
                except WebDriverException:
                    pass
        return False

    def _is_settings_page_open(self) -> bool:
        with self._fast_probe():
            try:
                elems = self.driver.find_elements(IOS_PREDICATE_BY,
                                                  self.SETTINGS_PAGE_MARKER_PREDICATE)
                return any(e.is_displayed() for e in elems)
            except WebDriverException:
                return False

    def click_setting_btn(self, max_attempts: int = 3) -> bool:
        """Open Camera Settings from GHP Camera Live View (supports inline 'Settings' button & action menu)."""
        page = GHPCameraLivePage._resolve_page(self)
        if page._is_settings_page_open():
            page._logger.info("Already on GHP Camera Settings page.")
            return True

        for attempt in range(1, max_attempts + 1):
            page._logger.info(f"Opening GHP Camera Settings (attempt {attempt}/{max_attempts})...")
            clicked = False
            with page._fast_probe():
                # Layout 1: Direct 'Settings' button on Camera Live View (e.g. x=165, y=776)
                try:
                    settings_btns = [
                        b
                        for b in page.driver.find_elements(
                            IOS_PREDICATE_BY, page.INLINE_SETTINGS_BTN_PREDICATE
                        )
                        if b.is_displayed()
                    ]
                except WebDriverException:
                    settings_btns = []

                if settings_btns:
                    target_btn = settings_btns[0]
                    try:
                        rect = target_btn.rect
                    except WebDriverException:
                        rect = None
                    try:
                        target_btn.click()
                        clicked = True
                    except WebDriverException:
                        if rect:
                            page.driver.execute_script(
                                "mobile: tap",
                                {
                                    "x": int(rect["x"] + rect["width"] / 2),
                                    "y": int(rect["y"] + rect["height"] / 2),
                                },
                            )
                            clicked = True
                else:
                    # Layout 2: Bottom-right menu button ('google_symbols/menu_symbol') -> 'Settings'
                    try:
                        menu_btns = [
                            b
                            for b in page.driver.find_elements(
                                IOS_PREDICATE_BY, page.MENU_SYMBOL_BTN_PREDICATE
                            )
                            if b.is_displayed()
                        ]
                    except WebDriverException:
                        menu_btns = []
                    if menu_btns:
                        try:
                            menu_btns[0].click()
                        except WebDriverException:
                            r = menu_btns[0].rect
                            page.driver.execute_script(
                                "mobile: tap",
                                {
                                    "x": int(r["x"] + r["width"] / 2),
                                    "y": int(r["y"] + r["height"] / 2),
                                },
                            )
                        time.sleep(0.8)
                        try:
                            popover_settings = [
                                b
                                for b in page.driver.find_elements(
                                    IOS_PREDICATE_BY, page.INLINE_SETTINGS_BTN_PREDICATE
                                )
                                if b.is_displayed()
                            ]
                            if popover_settings:
                                popover_settings[0].click()
                                clicked = True
                        except WebDriverException:
                            pass

            if clicked:
                deadline = time.time() + 5.0
                while time.time() < deadline:
                    if page._is_settings_page_open():
                        page._logger.info("Successfully opened GHP Camera Settings page.")
                        return True
                    time.sleep(0.4)
            time.sleep(0.6)

        page._logger.warning("Could not confirm GHP Camera Settings page opened after attempts.")
        return False

    click_settings_btn = click_setting_btn

    def _trigger_emergency_device_removal(self) -> None:
        """Capture immediate locked failure screenshot on Live View, then restart GHP and decommission camera."""
        page = GHPCameraLivePage._resolve_page(self)
        BasePage.capture_failure_screenshot(
            page.driver,
            reason="GHP Camera live stream verification failed",
            force=True,
            lock=True,
        )
        page._logger.warning(
            "[Live Verification FAILED] Initiating emergency teardown to decommission paired camera..."
        )
        session = (
            self
            if hasattr(self, "_emergency_recover_and_remove_device") and not hasattr(self,
                                                                                     "session")
            else getattr(self, "session", None) or getattr(page, "session", None)
        )
        if session and hasattr(session, "_emergency_recover_and_remove_device"):
            try:
                session._emergency_recover_and_remove_device()
                page._logger.info(
                    "[Live Verification FAILED] Successfully decommissioned device via emergency cleanup."
                )
            except Exception as clean_err:
                page._logger.error(
                    f"[Live Verification FAILED] Error during emergency device removal: {clean_err}"
                )

    def verify_camera_live_stream(
            self,
            duration_seconds: float = 30.0,
            max_retries: int = 20,
            check_interval: float = 1.0,
            exit_on_pass: bool = True,
    ) -> bool:
        """Continuously observe GHP camera live stream for `duration_seconds`, auto-clicking Retry if needed."""
        page = GHPCameraLivePage._resolve_page(self)
        page._logger.info(
            f"Starting GHP Camera Live stream verification (Target: {int(duration_seconds)}s, Max Retries: {max_retries})..."
        )
        timeline = _LiveTimeline(duration_seconds, max_retries)
        retry_count = 0
        last_heartbeat_log = 0.0

        while timeline.elapsed() < duration_seconds:
            sample, retry_btn = page._live_take_sample(timeline)
            if sample.state == _LiveState.RETRY:
                if retry_count >= max_retries:
                    message = timeline.build_failure_message(_LiveFailure.RETRY_EXHAUSTED)
                    page._logger.error(message)
                    GHPCameraLivePage._trigger_emergency_device_removal(self)
                    raise AssertionError(message)
                retry_count += 1
                timeline.add_retry(retry_count)
                page._logger.warning(
                    f"GHP Camera not streaming at {sample.t:.1f}s: {sample.describe()}. "
                    f"Clicking action/retry (#{retry_count}/{max_retries})..."
                )
                page._live_click_retry(retry_btn)
                time.sleep(page.LIVE_RECONNECT_WAIT)
                after, _ = page._live_take_sample(timeline)
                if after.state == _LiveState.LIVE:
                    page._logger.info(
                        f"GHP Camera live stream active after retry (#{retry_count}) at {after.t:.1f}s!"
                    )
                continue

            if sample.state == _LiveState.LIVE:
                if sample.t - last_heartbeat_log >= page.LIVE_HEARTBEAT_INTERVAL:
                    page._logger.info(
                        f"GHP Camera is LIVE streaming smoothly... ({int(sample.t)}s / {int(duration_seconds)}s elapsed)"
                    )
                    last_heartbeat_log = sample.t
            else:
                page._logger.info(
                    f"GHP Camera not live yet: {sample.describe()} ({int(sample.t)}s / {int(duration_seconds)}s elapsed)"
                )
            time.sleep(check_interval)

        had_live = timeline.has_streamed_live
        final, _ = page._live_take_sample(timeline)
        if not had_live or final.state != _LiveState.LIVE:
            category = _LiveFailure.NOT_LIVE_AT_END if had_live else _LiveFailure.NEVER_LIVE
            message = timeline.build_failure_message(category)
            page._logger.error(message)
            GHPCameraLivePage._trigger_emergency_device_removal(self)
            raise AssertionError(message)

        page._logger.info(
            f"SUCCESS: GHP Camera live stream verified for {int(timeline.elapsed())}s! "
            f"(Total retries clicked: {retry_count}) | {timeline.summary()}"
        )
        if exit_on_pass:
            GHPCameraLivePage.click_setting_btn(self)
        return True
