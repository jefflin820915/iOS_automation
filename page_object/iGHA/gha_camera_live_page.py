"""Page object for continuously verifying camera live stream stability and handling auto-retries on iOS."""
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterator, List, Optional, Sequence, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException
from common import constants
from common.base_page import BasePage
Locator = Tuple[str, str]


class _LiveState:
    """Classification of a single live-view observation."""
    LIVE = "LIVE"
    RETRY = "RETRY"                            # Retry button shown (stream disconnected).
    ERROR = "ERROR"                            # Error overlay shown without a Retry button.
    NOT_LIVE = "NOT_LIVE"                      # Player present but not streaming (connecting / buffering).
    NO_PLAYER = "NO_PLAYER"                    # Live player view not found (left the live page?).
    APP_NOT_FOREGROUND = "APP_NOT_FOREGROUND"  # GHA crashed or went to background.
    PROBE_ERROR = "PROBE_ERROR"                # WebDriver error while sampling.


class _LiveFailure:
    """Stable failure categories. The first line of the error message depends only on these
    (and the configured window), so dashboards can group by it."""
    NEVER_LIVE = "NEVER_LIVE"
    NOT_LIVE_AT_END = "NOT_LIVE_AT_END"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"


@dataclass
class _LiveSample:
    t: float        # Seconds since verification start.
    wall: float     # Epoch seconds, to correlate with syslog / camera.log / screen recording.
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
    """Records live-view samples / Retry clicks and renders a detailed failure report.
    Pure Python (no driver access), so the report format can be unit-tested offline.
    """
    LINE_SEPARATOR = "\n"  # Use " | " if the CSV / Sheet writer cannot handle multi-line cells.
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

    def add_sample(self, state: str, detail: str, observed_at: float) -> Tuple[_LiveSample, Optional[_LiveSample]]:
        prev = self.samples[-1] if self.samples else None
        sample = _LiveSample(t=observed_at - self.start, wall=observed_at, state=state, detail=detail)
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
        """Sample-and-hold: the gap between two samples is attributed to the earlier one."""
        totals: Dict[str, float] = {}
        for prev, cur in zip(self.samples, self.samples[1:]):
            key = prev.describe()
            totals[key] = totals.get(key, 0.0) + (cur.t - prev.t)
        return totals

    def _drops(self) -> List[_LiveDrop]:
        """Every LIVE -> not-LIVE transition, what was shown during the outage, and recovery."""
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
        first_live = self._first_live()
        n = len(self.samples)
        gap = (self.samples[-1].t - self.samples[0].t) / (n - 1) if n > 1 else 0.0
        return " | ".join([
            f"elapsed={end_t:.1f}s (target {self.duration:.0f}s)",
            f"first LIVE @{first_live.t:.1f}s" if first_live else "first LIVE: never",
            f"live={live_s:.1f}s ({pct:.0f}%)",
            f"drops={len(self._drops())}",
            f"retries={len(self.retries)}/{self.max_retries}",
            f"samples={n} (~{gap:.1f}s apart)",
        ])

    def _final_line(self) -> str:
        if not self.samples:
            return "Final state: no samples collected"
        final = self.samples[-1]
        last_live = self._last_live()
        live_part = f"last LIVE @{last_live.t:.1f}s ({_clock(last_live.wall)})" if last_live else "never LIVE"
        return f"Final state @{final.t:.1f}s ({_clock(final.wall)}): {final.describe()} | {live_part}"

    def _breakdown_line(self) -> str:
        items = sorted(
            ((k, v) for k, v in self._time_by_state().items() if k != _LiveState.LIVE),
            key=lambda kv: kv[1],
            reverse=True,
        )[: self.MAX_BREAKDOWN_ITEMS]
        text = ", ".join(f"{k} {v:.1f}s" for k, v in items) if items else "none"
        return f"Not-live time by state: {text}"

    def _drop_lines(self) -> List[str]:
        drops = self._drops()
        if not drops:
            return []
        end_t = self.samples[-1].t
        first_idx = max(0, len(drops) - self.MAX_DROPS_LISTED)
        lines = [f"Drops: showing last {self.MAX_DROPS_LISTED} of {len(drops)}"] if first_idx else []
        for idx, d in enumerate(drops[first_idx:], start=first_idx + 1):
            if d.recovered_at is not None:
                outcome = f"recovered @{d.recovered_at:.1f}s after {d.recovered_at - d.first_bad.t:.1f}s"
            elif d.first_bad is self.samples[-1]:
                outcome = "NOT recovered (only the final sample was not LIVE)"
            else:
                outcome = f"NOT recovered (down {end_t - d.first_bad.t:.1f}s until end)"
            lines.append(
                f"Drop #{idx} @{d.first_bad.t:.1f}s ({_clock(d.first_bad.wall)}, last LIVE @{d.last_live.t:.1f}s): "
                f"LIVE -> {' -> '.join(d.states)} | {outcome} | retries={d.retries}"
            )
        return lines

    def _timeline_line(self) -> str:
        events: List[Tuple[float, str]] = []
        last_key = None
        for s in self.samples:
            key = s.describe()
            if key != last_key:
                events.append((s.t, f"{s.t:.1f}s {key}"))
                last_key = key
        events.extend((r.t, f"{r.t:.1f}s [Retry#{r.index}]") for r in self.retries)
        events.sort(key=lambda e: e[0])
        texts = [text for _, text in events]
        if len(texts) > self.MAX_TIMELINE_EVENTS:
            hidden = len(texts) - self.MAX_TIMELINE_EVENTS
            texts = [f"...(+{hidden} earlier)"] + texts[-self.MAX_TIMELINE_EVENTS:]
        return "Timeline: " + " -> ".join(texts)

    def build_failure_message(self, category: str) -> str:
        window = f"{self.duration:.0f}s"
        headline = {
            _LiveFailure.NEVER_LIVE: f"stream never reached LIVE within the {window} window.",
            _LiveFailure.NOT_LIVE_AT_END: f"stream was LIVE earlier but NOT LIVE at the end of the {window} window.",
            _LiveFailure.RETRY_EXHAUSTED: f"Retry clicked {self.max_retries} times but stream is still not LIVE.",
        }[category]
        lines = [
            f"Camera live stream verification FAILED [{category}]: {headline}",
            f"Summary: {self.summary()}",
            self._final_line(),
            self._breakdown_line(),
            *self._drop_lines(),
            self._timeline_line(),
        ]
        return self.LINE_SEPARATOR.join(lines)


class GHACameraLivePage(BasePage):
    """Class for monitoring camera live video stream and handling connection retries.
    NOTE: Private helpers / constants use the `_live_` / `LIVE_` prefix to avoid MRO name collisions
          in GHASession. Final AssertionErrors are raised directly in verify_camera_live_stream so the
          reported Failure Stage stays VERIFY_CAMERA_LIVE_STREAM.
    """
    LIVE_RETRY_LOCATORS: List[Locator] = [
        (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "Retry"`]'),
        (AppiumBy.IOS_PREDICATE, 'name == "Retry" OR label == "Retry"'),
        (AppiumBy.XPATH, '//XCUIElementTypeButton[@name="Retry" or @label="Retry"]'),
        (AppiumBy.XPATH, '//XCUIElementTypeOther[@name="CameraStateInfoView"]//XCUIElementTypeButton'),
        (AppiumBy.ACCESSIBILITY_ID, "Retry"),
    ]
    LIVE_ERROR_OVERLAY_LOCATORS: List[Locator] = [
        (AppiumBy.ACCESSIBILITY_ID, "CameraStateInfoView"),
        (AppiumBy.ACCESSIBILITY_ID, "cameraStateTitleLabel"),
        (AppiumBy.IOS_PREDICATE, 'label CONTAINS "Live view unavailable" OR label CONTAINS "unreachable"'),
    ]
    LIVE_OVERLAY_TEXT_CHAIN = (
        '**/XCUIElementTypeOther[`name == "CameraStateInfoView"`]/**/XCUIElementTypeStaticText'
    )
    LIVE_OVERLAY_TEXT_FALLBACKS: List[Locator] = [
        (AppiumBy.ACCESSIBILITY_ID, "cameraStateTitleLabel"),
        (AppiumBy.IOS_PREDICATE, 'label CONTAINS "Live view unavailable" OR label CONTAINS "unreachable"'),
    ]
    LIVE_PLAYER_LOCATORS: List[Locator] = [
        (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "CamerazillaPlayerView"`]'),
        (AppiumBy.ACCESSIBILITY_ID, "CamerazillaPlayerView"),
    ]
    LIVE_OVERFLOW_MENU_LOCATORS: List[Locator] = [
        (AppiumBy.ACCESSIBILITY_ID, "overflowMenuButton"),
        (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "overflowMenuButton"`]'),
        (AppiumBy.IOS_PREDICATE, 'name == "overflowMenuButton"'),
        (AppiumBy.XPATH, '//XCUIElementTypeButton[@name="overflowMenuButton"]'),
    ]
    LIVE_SETTINGS_MENU_ITEM_LOCATORS: List[Locator] = [
        (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeCell/**/XCUIElementTypeButton[`name == "Settings" OR label == "Settings"`]'),
        (AppiumBy.XPATH, '//XCUIElementTypeCell//XCUIElementTypeButton[@name="Settings" or @label="Settings"]'),
        (AppiumBy.ACCESSIBILITY_ID, "Settings"),
        (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "Settings"`]'),
        (AppiumBy.IOS_PREDICATE, 'type == "XCUIElementTypeButton" AND name == "Settings"'),
        (AppiumBy.XPATH, '//XCUIElementTypeButton[@name="Settings"]'),
    ]
    LIVE_PLAYER_KEYWORDS = ("live stream", "viewing live stream", "camera on")
    LIVE_BADGE_LOCATOR: Locator = (AppiumBy.IOS_PREDICATE, 'label CONTAINS "Live" OR name CONTAINS "Live"')
    LIVE_RECONNECT_WAIT = 5.0
    LIVE_HEARTBEAT_INTERVAL = 5.0
    LIVE_DETAIL_MAX_LEN = 80

    @contextmanager
    def _live_no_implicit_wait(self) -> Iterator[None]:
        """Temporarily disable implicit wait and always restore the previous value."""
        try:
            previous = self.driver.timeouts.implicit_wait
        except Exception:
            previous = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
        self.driver.implicitly_wait(0)
        try:
            yield
        finally:
            try:
                self.driver.implicitly_wait(previous)
            except WebDriverException:
                pass

    def _live_find_all(self, by: str, value: str) -> List[WebElement]:
        try:
            return self.driver.find_elements(by, value)
        except WebDriverException:
            return []

    def _live_first(self, locators: Sequence[Locator]) -> Optional[WebElement]:
        for by, value in locators:
            elements = self._live_find_all(by, value)
            if elements:
                return elements[0]
        return None

    def _live_clean(self, text: str) -> str:
        """Single-line, length-limited text for logs / error messages."""
        text = " ".join(str(text or "").split())
        limit = self.LIVE_DETAIL_MAX_LEN
        return text if len(text) <= limit else text[: limit - 3] + "..."

    @staticmethod
    def _live_read_label(elem: WebElement) -> str:
        try:
            return (elem.get_attribute("label") or elem.get_attribute("value") or "").strip()
        except WebDriverException:
            return ""

    def _live_overlay_text(self) -> str:
        """On-screen reason from the camera state overlay, e.g. 'Live view unavailable / <subtitle>'."""
        texts: List[str] = []
        for elem in self._live_find_all(AppiumBy.IOS_CLASS_CHAIN, self.LIVE_OVERLAY_TEXT_CHAIN):
            text = self._live_read_label(elem)
            if text and text not in texts:
                texts.append(text)
        if not texts:
            elem = self._live_first(self.LIVE_OVERLAY_TEXT_FALLBACKS)
            text = self._live_read_label(elem) if elem is not None else ""
            if text:
                texts.append(text)
        return self._live_clean(" / ".join(texts))

    def _live_is_gha_foreground(self) -> bool:
        try:
            return self.driver.query_app_state(constants.GHA_BUNDLE_ID) == constants.APP_STATE_FOREGROUND
        except WebDriverException:
            return True

    def _live_probe(self) -> Tuple[str, str, Optional[WebElement]]:
        """Classify the live view in one pass. Returns (state, detail, retry_btn).
        LIVE semantics match the old is_camera_live(): no Retry button, no error overlay, and either
        the CamerazillaPlayerView label says live or a 'Live' badge is displayed.
        """
        with self._live_no_implicit_wait():
            try:
                retry_btn = self._live_first(self.LIVE_RETRY_LOCATORS)
                if retry_btn is not None:
                    reason = self._live_overlay_text()
                    return _LiveState.RETRY, (f"'{reason}'" if reason else ""), retry_btn
                for by, value in self.LIVE_ERROR_OVERLAY_LOCATORS:
                    if self._live_find_all(by, value):
                        reason = self._live_overlay_text()
                        return _LiveState.ERROR, (f"'{reason}'" if reason else f"via={value}"), None
                players: List[WebElement] = []
                for by, value in self.LIVE_PLAYER_LOCATORS:
                    players = self._live_find_all(by, value)
                    if players:
                        break
                player_label = ""
                for player in players:
                    try:
                        label = str(player.get_attribute("label") or "")
                    except WebDriverException:
                        continue
                    player_label = player_label or label
                    if any(k in label.lower() for k in self.LIVE_PLAYER_KEYWORDS):
                        return _LiveState.LIVE, "", None
                for badge in self._live_find_all(*self.LIVE_BADGE_LOCATOR):
                    try:
                        if badge.is_displayed():
                            return _LiveState.LIVE, "", None
                    except WebDriverException:
                        continue
                if players:
                    detail = f"player='{self._live_clean(player_label)}'" if player_label else ""
                    return _LiveState.NOT_LIVE, detail, None
                if not self._live_is_gha_foreground():
                    return _LiveState.APP_NOT_FOREGROUND, "", None
                return _LiveState.NO_PLAYER, "", None
            except Exception as e:  # Parity with the old is_camera_live(): any error means "not live".
                return _LiveState.PROBE_ERROR, self._live_clean(e.__class__.__name__), None

    def _live_take_sample(self, timeline: _LiveTimeline) -> Tuple[_LiveSample, Optional[WebElement]]:
        """Probe once, record into the timeline, and log state transitions with timestamps."""
        observed_at = time.time()
        state, detail, retry_btn = self._live_probe()
        sample, prev = timeline.add_sample(state, detail, observed_at)
        if prev is None or prev.describe() != sample.describe():
            is_drop = prev is not None and prev.state == _LiveState.LIVE
            log = self._logger.warning if is_drop else self._logger.info
            log(
                f"[LiveCheck] {sample.t:.1f}s ({_clock(sample.wall)}) "
                f"{prev.describe() if prev else 'START'} -> {sample.describe()}"
            )
        return sample, retry_btn

    def _live_click_retry(self, retry_btn: Optional[WebElement]) -> bool:
        """Click the Retry button using coordinates to bypass XCUITest 'visible: false' interaction block."""
        self._logger.info("Triggering interaction on Retry button...")
        if retry_btn:
            try:
                rect = retry_btn.rect
                cx = int(rect['x'] + rect['width'] / 2)
                cy = int(rect['y'] + rect['height'] / 2)
                self._logger.info(f"Tapping Retry at calculated center coordinates ({cx}, {cy})...")
                self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                return True
            except Exception as coord_err:
                self._logger.warning(f"Calculated coordinate tap failed: {coord_err}")
            try:
                self.driver.execute_script("mobile: tap", {"elementId": retry_btn.id})
                return True
            except Exception:
                pass
        self._logger.info("Fallback tapping at verified Inspector coordinates (187, 176)...")
        try:
            self.driver.execute_script("mobile: tap", {"x": 187, "y": 176})
            return True
        except Exception as tap_err:
            self._logger.error(f"Failed to tap Retry button: {tap_err}")
            return False

    def is_camera_live(self) -> bool:
        """Check if camera video stream is actively playing in Live state.
        Verified via official CamerazillaPlayerView label: 'Camera on, viewing live stream'.
        """
        return self._live_probe()[0] == _LiveState.LIVE

    def click_back_btn(self) -> bool:
        """Click the top-left back/close button to exit the Camera Live stream page."""
        self._logger.info("Exiting Camera Live screen: looking for back/close button...")
        back_locators = [
            (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "closeButton"`]'),
            (AppiumBy.ACCESSIBILITY_ID, "closeButton"),
            (AppiumBy.ACCESSIBILITY_ID, "close"),
            (AppiumBy.ACCESSIBILITY_ID, "Close"),
            (AppiumBy.ACCESSIBILITY_ID, "Back"),
            (AppiumBy.ACCESSIBILITY_ID, "back"),
            (AppiumBy.IOS_PREDICATE, 'label == "Back" OR name == "Back" OR label == "Close" OR name == "close"'),
        ]
        try:
            self.driver.execute_script("mobile: tap", {"x": 50, "y": 100})
            time.sleep(0.5)
            elems = self.driver.find_element(AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "closeButton"`]')
            elems.click()
            self._logger.info("Successfully clicked back button.")
            return True
        except Exception:
            pass
        self._logger.info("Navigation bar may be hidden. Tapping screen to reveal controls...")
        try:
            self.driver.execute_script("mobile: tap", {"x": 200, "y": 300})
            time.sleep(1.0)
            for by, val in back_locators:
                elems = self.driver.find_elements(by, val)
                if elems and elems[0].is_displayed():
                    elems[0].click()
                    time.sleep(1.5)
                    self._logger.info("Successfully clicked back button after revealing controls.")
                    return True
        except Exception as e:
            self._logger.warning(f"Error tapping screen to reveal controls: {e}")
        self._logger.warning("Fallback: Tapping top-left corner coordinates to exit live view...")
        try:
            self.driver.execute_script("mobile: tap", {"x": 25, "y": 55})
            time.sleep(1.5)
            return True
        except Exception as e:
            self._logger.error(f"Failed to click back: {e}")
            return False

    def _live_find_settings_menu_item(self) -> Optional[WebElement]:
        """Find the 'Settings' button inside the overflow popover menu if present."""
        with self._live_no_implicit_wait():
            for by, val in self.LIVE_SETTINGS_MENU_ITEM_LOCATORS:
                for elem in self._live_find_all(by, val):
                    try:
                        if elem.is_displayed():
                            return elem
                    except WebDriverException:
                        continue
        return None

    def _live_tap_element_or_coords(
            self, elem: Optional[WebElement], fallback_x: int, fallback_y: int, desc: str
    ) -> bool:
        """Click an element, falling back to coordinate tap on its rect or Inspector coordinates."""
        if elem is not None:
            try:
                elem.click()
                self._logger.info(f"Clicked {desc} via element.click().")
                return True
            except Exception as click_err:
                self._logger.warning(f"Standard click on {desc} failed ({click_err}); trying coordinate tap...")
            try:
                rect = elem.rect
                cx = int(rect["x"] + rect["width"] / 2)
                cy = int(rect["y"] + rect["height"] / 2)
                self._logger.info(f"Tapping {desc} at calculated center ({cx}, {cy})...")
                self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                return True
            except Exception as rect_err:
                self._logger.warning(f"Calculated coordinate tap on {desc} failed: {rect_err}")
        self._logger.info(f"Fallback tapping {desc} at Inspector coordinates ({fallback_x}, {fallback_y})...")
        try:
            self.driver.execute_script("mobile: tap", {"x": fallback_x, "y": fallback_y})
            return True
        except Exception as tap_err:
            self._logger.error(f"Failed to tap {desc}: {tap_err}")
            return False

    def click_setting_btn(self) -> bool:
        """Open Device Settings from the Camera Live page via overflowMenuButton -> Settings."""
        self._logger.info("Opening Settings from Camera Live screen: looking for 'overflowMenuButton'...")
        with self._live_no_implicit_wait():
            overflow_btn = self._live_first(self.LIVE_OVERFLOW_MENU_LOCATORS)
        if overflow_btn is None:
            self._logger.info("Top overlay may be auto-hidden. Tapping video player to reveal controls...")
            try:
                self.driver.execute_script("mobile: tap", {"x": 200, "y": 180})
                time.sleep(0.8)
            except Exception as e:
                self._logger.warning(f"Error tapping screen to reveal controls: {e}")
            with self._live_no_implicit_wait():
                overflow_btn = self._live_first(self.LIVE_OVERFLOW_MENU_LOCATORS)
        self._live_tap_element_or_coords(overflow_btn, fallback_x=362, fallback_y=79, desc="overflowMenuButton")
        time.sleep(1.0)

        settings_item = self._live_find_settings_menu_item()
        if settings_item is None:
            self._logger.info("Popover menu not yet visible; tapping overflowMenuButton coordinates directly...")
            cx, cy = 362, 79
            if overflow_btn is not None:
                try:
                    rect = overflow_btn.rect
                    cx = int(rect["x"] + rect["width"] / 2)
                    cy = int(rect["y"] + rect["height"] / 2)
                except Exception:
                    pass
            try:
                self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
            except Exception as e:
                self._logger.warning(f"Direct coordinate tap on overflowMenuButton failed: {e}")
            deadline = time.time() + 4.0
            while time.time() < deadline:
                settings_item = self._live_find_settings_menu_item()
                if settings_item is not None:
                    break
                time.sleep(0.4)
        if settings_item is not None:
            self._logger.info("Found 'Settings' item in popover menu. Clicking 'Settings'...")
            ok = self._live_tap_element_or_coords(
                settings_item, fallback_x=257, fallback_y=123, desc="Settings menu item"
            )
            time.sleep(1.5)
            return ok
        self._logger.warning(
            "Popover 'Settings' item not found via locators; tapping fallback coordinates (257, 123)..."
        )
        try:
            self.driver.execute_script("mobile: tap", {"x": 257, "y": 123})
            time.sleep(1.5)
            return True
        except Exception as e:
            self._logger.error(f"Failed to click Settings button: {e}")
            return False
    click_settings_btn = click_setting_btn
    
    def _trigger_emergency_device_removal(self) -> None:
        """Trigger GHA restart and device removal so the camera is factory reset for the next run."""
        self._logger.warning("[Live Verification FAILED] Initiating emergency teardown to remove paired camera...")
        session = (
            self
            if hasattr(self, "_emergency_recover_and_remove_device") and not hasattr(self, "session")
            else getattr(self, "session", None)
        )
        if session and hasattr(session, "_emergency_recover_and_remove_device"):
            try:
                session._emergency_recover_and_remove_device()
                self._logger.info("[Live Verification FAILED] Successfully removed device via emergency cleanup.")
            except Exception as clean_err:
                self._logger.error(f"[Live Verification FAILED] Error during emergency device removal: {clean_err}")
        else:
            self._logger.warning("[Live Verification FAILED] Session back-reference not found. Attempting Settings button and restart...")
            try:
                GHACameraLivePage.click_setting_btn(self)
            except Exception:
                pass
            try:
                self.driver.terminate_app(constants.GHA_BUNDLE_ID)
                time.sleep(2.0)
                self.driver.activate_app(constants.GHA_BUNDLE_ID)
            except Exception:
                pass

    def verify_camera_live_stream(
            self,
            duration_seconds: float = 30.0,
            max_retries: int = 20,
            check_interval: float = 1.0,
            exit_on_pass: bool = True
    ) -> bool:
        """Continuously observe camera live stream for duration_seconds, auto-clicking Retry if needed.
        Args:
            duration_seconds (float): Total seconds to continuously verify live stream (e.g. 30.0s).
            max_retries (int): Maximum allowable Retry clicks before failing. Defaults to 20.
            check_interval (float): Polling interval in seconds. Defaults to 1.0s.
            exit_on_pass (bool): Kept for backward compatibility; Settings is clicked upon pass.
        Returns:
            bool: True if camera streamed live successfully for duration_seconds.
        Raises:
            AssertionError: If retries are exhausted or stream cannot reach a steady Live state.
                The message contains a failure category, summary, final state, per-drop details
                and a state timeline (see _LiveTimeline.build_failure_message).
        """
        self._logger.info(
            f"Starting Camera Live stream verification (Target: {int(duration_seconds)}s, Max Retries: {max_retries})..."
        )
        timeline = _LiveTimeline(duration_seconds, max_retries)
        retry_count = 0
        last_heartbeat_log = 0.0
        while timeline.elapsed() < duration_seconds:
            sample, retry_btn = self._live_take_sample(timeline)
            if sample.state == _LiveState.RETRY:
                if retry_count >= max_retries:
                    message = timeline.build_failure_message(_LiveFailure.RETRY_EXHAUSTED)
                    self._logger.error(message)
                    GHACameraLivePage._trigger_emergency_device_removal(self)
                    raise AssertionError(message)
                retry_count += 1
                timeline.add_retry(retry_count)
                self._logger.warning(
                    f"Camera stream disconnected at {sample.t:.1f}s: {sample.describe()}. "
                    f"Clicking Retry (#{retry_count}/{max_retries})..."
                )
                self._live_click_retry(retry_btn)
                self._logger.info(
                    f"Clicked Retry (#{retry_count}). Waiting {self.LIVE_RECONNECT_WAIT:.0f}s for stream reconnection..."
                )
                time.sleep(self.LIVE_RECONNECT_WAIT)
                after, _ = self._live_take_sample(timeline)
                if after.state == _LiveState.LIVE:
                    self._logger.info(f"Camera live stream recovered after retry (#{retry_count}) at {after.t:.1f}s!")
                continue
            if sample.state == _LiveState.LIVE:
                if sample.t - last_heartbeat_log >= self.LIVE_HEARTBEAT_INTERVAL:
                    self._logger.info(
                        f"Camera is LIVE streaming smoothly... ({int(sample.t)}s / {int(duration_seconds)}s elapsed)"
                    )
                    last_heartbeat_log = sample.t
            else:
                self._logger.info(
                    f"Camera not live yet: {sample.describe()} ({int(sample.t)}s / {int(duration_seconds)}s elapsed)"
                )
            time.sleep(check_interval)
        had_live = timeline.has_streamed_live
        final, _ = self._live_take_sample(timeline)
        if not had_live or final.state != _LiveState.LIVE:
            category = _LiveFailure.NOT_LIVE_AT_END if had_live else _LiveFailure.NEVER_LIVE
            message = timeline.build_failure_message(category)
            self._logger.error(message)
            GHACameraLivePage._trigger_emergency_device_removal(self)
            raise AssertionError(message)
        self._logger.info(
            f"SUCCESS: Camera live stream verified for {int(timeline.elapsed())}s! "
            f"(Total retries clicked: {retry_count}) | {timeline.summary()}"
        )
        GHACameraLivePage.click_setting_btn(self)
        return True