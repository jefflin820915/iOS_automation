"""Shared AT&T Connected Life (`Connected Life`) bundle resolution and UI interaction helpers."""

import contextlib
import re
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput

from common import constants
from common.base_page import BasePage

IOS_PREDICATE_BY = getattr(AppiumBy, "IOS_PREDICATE", "-ios predicate string")
IOS_CLASS_CHAIN_BY = getattr(AppiumBy, "IOS_CLASS_CHAIN", "-ios class chain")

DEFAULT_ATT_BUNDLE_ID = "com.att.connectedlife"
ATT_CANDIDATE_BUNDLE_IDS: Tuple[str, ...] = (
    "com.att.connectedlife",
    "com.goabode.att",
    "com.goabode.att.preprod",
)
DEFAULT_ATT_RELAUNCH_INTERVAL = 10


def _configured_att_bundle_candidates() -> List[str]:
    """Return ordered list of configured + known AT&T Connected Life bundle IDs."""
    candidates: List[str] = []
    explicit = getattr(constants, "ATT_BUNDLE_ID", None) or getattr(
        constants, "ATT_CONNECTED_LIFE_BUNDLE_ID", None
    )
    if explicit and str(explicit).strip():
        candidates.append(str(explicit).strip())
    extra = getattr(constants, "ATT_CANDIDATE_BUNDLE_IDS", None)
    if isinstance(extra, (list, tuple)):
        for bid in extra:
            if bid and str(bid).strip() not in candidates:
                candidates.append(str(bid).strip())
    for bid in ATT_CANDIDATE_BUNDLE_IDS:
        if bid not in candidates:
            candidates.append(bid)
    return candidates


def resolve_att_bundle_id(driver: Optional[WebDriver] = None, force: bool = False) -> str:
    """Resolve the installed iOS bundle ID for AT&T Connected Life (`Connected Life`).

    Caches the discovered bundle ID on `driver._att_bundle_id` so subsequent calls
    do not repeatedly query `mobile: listApps`.
    """
    if driver is not None and not force:
        cached = getattr(driver, "_att_bundle_id", None)
        if cached and str(cached).strip():
            return str(cached).strip()

    candidates = _configured_att_bundle_candidates()
    resolved: Optional[str] = None

    if driver is not None:
        # 1. Inspect installed User apps via `mobile: listApps`
        try:
            apps = driver.execute_script("mobile: listApps", {"applicationType": "User"})
            app_map: Dict[str, Dict[str, Any]] = {}
            if isinstance(apps, dict):
                for bid, meta in apps.items():
                    if isinstance(bid, str):
                        app_map[bid] = meta if isinstance(meta, dict) else {}
            elif isinstance(apps, list):
                for item in apps:
                    if isinstance(item, dict) and item.get("CFBundleIdentifier"):
                        app_map[str(item["CFBundleIdentifier"])] = item

            for cand in candidates:
                if cand in app_map:
                    resolved = cand
                    break

            if resolved is None:
                for bid, meta in app_map.items():
                    display_name = str(
                        meta.get("CFBundleDisplayName") or meta.get("CFBundleName") or ""
                    ).lower()
                    bid_low = bid.lower()
                    if "connected life" in display_name or (
                            "connectedlife" in bid_low or "goabode.att" in bid_low
                    ):
                        resolved = bid
                        break
        except Exception:
            pass

        # 2. Fallback: probe known candidate bundle IDs via `query_app_state` (> 0 means installed)
        if resolved is None and hasattr(driver, "query_app_state"):
            for cand in candidates:
                try:
                    state = driver.query_app_state(cand)
                    if isinstance(state, int) and state > 0:
                        resolved = cand
                        break
                except Exception:
                    continue

    final_bundle = resolved or (candidates[0] if candidates else DEFAULT_ATT_BUNDLE_ID)
    if driver is not None:
        try:
            setattr(driver, "_att_bundle_id", final_bundle)
        except Exception:
            pass
    return final_bundle


class ATTBasePage(BasePage):
    """Shared BasePage subclass for AT&T Connected Life screens (avoids helper duplication)."""

    TOP_NOTIFICATION_BANNER_PREDICATE: str = (
        'name == "NotificationShortLookView" '
        'OR name == "NCNotificationShortLookView" '
        'OR name == "BannerNotificationView" '
        'OR name CONTAINS "NotificationShortLook" '
        'OR name CONTAINS[c] "NotificationBanner" '
        'OR name CONTAINS[c] "NotificationCell" '
        'OR name CONTAINS[c] "NotificationView" '
        'OR name CONTAINS[c] "PLPlatterView" '
        'OR name CONTAINS[c] "snackbar" '
        'OR name CONTAINS[c] "toast" '
        'OR label BEGINSWITH[c] "NOTIFICATION," '
        'OR label BEGINSWITH[c] "NOTIFICATION:"'
    )
    SPRINGBOARD_FALLBACK_BANNER_PREDICATE: str = (
        'type IN {"XCUIElementTypeOther", "XCUIElementTypeCell", '
        '"XCUIElementTypeButton", "XCUIElementTypeAlert"}'
    )
    SPRINGBOARD_IGNORED_PREFIXES: Tuple[str, ...] = (
        "sb",
        "status bar",
        "statusbar",
        "dynamic island",
        "_ui",
        "control center",
        "home indicator",
    )
    DEFAULT_NOTIFICATION_WAIT_TIMEOUT_S: float = 15.0
    NOTIFICATION_CHECK_THROTTLE_S: float = 0.5

    def __init__(self, driver: WebDriver, timeout: float = 10.0) -> None:
        self.APP_BUNDLE_ID = resolve_att_bundle_id(driver)
        super().__init__(driver, timeout=timeout)

    def _resume_if_suspended(self) -> None:
        """Skip pre-launch auto-resume during initial `ATTSession` construction before `start_att()`."""
        if self.driver is not None and not getattr(self.driver, "_att_started", False):
            return
        super()._resume_if_suspended()

    def _att_bundle_id(self) -> str:
        bundle_id = resolve_att_bundle_id(self.driver)
        self.APP_BUNDLE_ID = bundle_id
        return bundle_id

    @contextlib.contextmanager
    def _att_fast_probe(self) -> Iterator[None]:
        """Temporarily set implicit wait to 0s and reliably restore it."""
        default_wait = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
        try:
            if hasattr(self.driver, "implicitly_wait"):
                self.driver.implicitly_wait(0)
        except Exception:
            pass
        try:
            yield
        finally:
            try:
                if hasattr(self.driver, "implicitly_wait"):
                    self.driver.implicitly_wait(default_wait)
            except Exception:
                pass

    @staticmethod
    def _att_norm(text: Optional[str]) -> str:
        return " ".join((text or "").strip().lower().split())

    @staticmethod
    def _att_slug(text: Optional[str]) -> str:
        return re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")

    def _att_window_size(self) -> Tuple[int, int]:
        try:
            win = self.driver.get_window_size() or {}
            return int(win.get("width", 390)), int(win.get("height", 844))
        except Exception:
            return 390, 844

    @staticmethod
    def _att_escape_predicate(value: str) -> str:
        return (value or "").replace("\\", "\\\\").replace('"', '\\"')

    def _att_read_attr(
            self, elem: WebElement, attrs: Tuple[str, ...] = ("label", "name", "value")
    ) -> str:
        for attr in attrs:
            try:
                val = elem.get_attribute(attr)
                if val and str(val).strip():
                    return str(val).strip()
            except (StaleElementReferenceException, WebDriverException):
                continue
        try:
            txt = elem.text
            return str(txt).strip() if txt else ""
        except (StaleElementReferenceException, WebDriverException):
            return ""

    def _att_is_element_on_screen(
            self,
            elem: WebElement,
            require_visible_attr: bool = False,
            min_y: int = 0,
            max_y_margin: int = 0,
    ) -> bool:
        """Check whether an element has valid on-screen geometry.

        AT&T Connected Life has some accessible container children (e.g. Room card StaticTexts)
        whose `visible` XCUITest flag is false even while rendered inside the viewport.
        """
        if require_visible_attr:
            try:
                if not elem.is_displayed():
                    return False
            except WebDriverException:
                return False
        try:
            rect = elem.rect
        except WebDriverException:
            return False
        if not rect:
            return False
        width = rect.get("width", 0)
        height = rect.get("height", 0)
        if width <= 0 or height <= 0:
            return False
        win_w, win_h = self._att_window_size()
        cx = rect.get("x", 0) + width / 2.0
        cy = rect.get("y", 0) + height / 2.0
        max_y = win_h - max_y_margin if max_y_margin else win_h
        return 0 <= cx <= win_w and min_y <= cy <= max_y

    def _att_tap_element_or_coords(
            self,
            elem: WebElement,
            desc: str = "element",
            prefer_coords: bool = False,
            x_ratio: float = 0.5,
            y_ratio: float = 0.5,
    ) -> bool:
        rect = None
        try:
            rect = elem.rect
        except WebDriverException:
            rect = None
        is_top_ui = bool(rect and rect.get("y", 999) < 160)
        self._wait_until_top_notification_disappears(force=is_top_ui)

        if not prefer_coords:
            try:
                elem.click()
                return True
            except WebDriverException as err:
                self._logger.debug(
                    f"[ATT Tap] Direct click failed on {desc} ({err}); trying tap...")

        if rect and rect.get("width", 0) > 0 and rect.get("height", 0) > 0:
            cx = int(rect["x"] + rect["width"] * x_ratio)
            cy = int(rect["y"] + rect["height"] * y_ratio)
            try:
                self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                return True
            except WebDriverException as tap_err:
                self._logger.warning(
                    f"[ATT Tap] Coordinate tap failed on {desc} at ({cx}, {cy}): {tap_err}")

        if prefer_coords:
            try:
                elem.click()
                return True
            except WebDriverException:
                pass
        return False

    def _att_drag(self, from_x: int, from_y: int, to_x: int, to_y: int,
                  duration: float = 0.28) -> None:
        try:
            self.driver.execute_script(
                "mobile: dragFromToForDuration",
                {
                    "duration": duration,
                    "fromX": int(from_x),
                    "fromY": int(from_y),
                    "toX": int(to_x),
                    "toY": int(to_y),
                },
            )
            return
        except WebDriverException:
            pass

        actions = ActionChains(self.driver)
        actions.w3c_actions = ActionBuilder(
            self.driver, mouse=PointerInput(interaction.POINTER_TOUCH, "touch")
        )
        pointer = actions.w3c_actions.pointer_action
        pointer.move_to_location(int(from_x), int(from_y))
        pointer.pointer_down()
        pointer.pause(0.15)
        pointer.move_to_location(int(to_x), int(to_y))
        pointer.pause(0.15)
        pointer.pointer_up()
        actions.perform()

    def _att_pull_down_to_refresh(self) -> None:
        self._wait_until_top_notification_disappears()
        win_w, win_h = self._att_window_size()
        cx = win_w // 2
        from_y = max(130, int(win_h * 0.24))
        to_y = int(win_h * 0.72)
        self._att_drag(cx, from_y, cx, to_y, duration=0.3)

    def _att_scroll_vertical(self, direction: str = "down") -> None:
        self._wait_until_top_notification_disappears()
        win_w, win_h = self._att_window_size()
        cx = win_w // 2
        if direction == "down":
            from_y, to_y = int(win_h * 0.68), int(win_h * 0.30)
        else:
            from_y, to_y = int(win_h * 0.30), int(win_h * 0.68)
        self._att_drag(cx, from_y, cx, to_y, duration=0.25)
        time.sleep(0.8)

    def _match_top_notification_in_active_context(self, in_springboard: bool = False) -> Optional[
        str]:
        """Inspect currently active Appium UI context for a visible iOS top notification banner."""
        win_w, win_h = self._att_window_size()
        max_y = int(win_h * 0.28)
        max_h = int(win_h * 0.35)
        min_w = int(win_w * 0.45)

        def _extract_matching_banner(
                elements: List[WebElement],
                *,
                strict_banner: bool,
        ) -> Optional[str]:
            for el in elements:
                try:
                    if hasattr(el, "is_displayed"):
                        displayed = el.is_displayed()
                        if strict_banner:
                            if displayed is not True:
                                continue
                        elif displayed is False:
                            continue
                    rect = el.rect or {}
                except WebDriverException:
                    continue
                rw = float(rect.get("width", 0) or 0)
                rh = float(rect.get("height", 0) or 0)
                rx = float(rect.get("x", 0) or 0)
                ry = float(rect.get("y", -999) or -999)
                cx = rx + rw / 2.0
                min_y = 4 if strict_banner else -10
                top_limit = int(win_h * 0.22) if strict_banner else max_y
                min_h = 48 if strict_banner else 32
                height_limit = int(win_h * 0.30) if strict_banner else max_h
                width_limit = int(win_w * 0.60) if strict_banner else min_w
                if not (
                        rw >= width_limit
                        and min_h <= rh <= height_limit
                        and min_y <= ry <= top_limit
                        and (ry + rh) > 20
                        and 0 <= cx <= win_w
                ):
                    continue
                if strict_banner and (ry + rh) > int(win_h * 0.38):
                    continue
                txt = self._att_read_attr(el, ("label", "name", "value"))
                if strict_banner:
                    low_txt = txt.lower()
                    if len(txt) < 3 or low_txt.startswith(self.SPRINGBOARD_IGNORED_PREFIXES):
                        continue
                return (txt or "NotificationShortLookView")[:80]
            return None

        try:
            candidates = self.driver.find_elements(
                IOS_PREDICATE_BY, self.TOP_NOTIFICATION_BANNER_PREDICATE
            )
            hit = _extract_matching_banner(candidates, strict_banner=False)
            if hit is not None:
                return hit
        except WebDriverException:
            pass

        # iOS 17/18/26 SpringBoard fallback: catch floating top notification platters even when
        # AccessibilityIdentifier differs from 'NotificationShortLookView'.
        if in_springboard:
            try:
                sb_candidates = self.driver.find_elements(
                    IOS_PREDICATE_BY, self.SPRINGBOARD_FALLBACK_BANNER_PREDICATE
                )
                return _extract_matching_banner(sb_candidates, strict_banner=True)
            except WebDriverException:
                pass
        return None

    def _find_top_notification_banner(self) -> Optional[str]:
        """Detect a top notification banner either in AT&T's UI tree or in iOS SpringBoard."""
        if self.driver is None:
            return None

        banner: Optional[str] = None
        with self._att_fast_probe():
            banner = self._match_top_notification_in_active_context(in_springboard=False)
            if banner is None and callable(getattr(self.driver, "update_settings", None)):
                orig_depth = getattr(self.driver, "_att_orig_snapshot_max_depth", None)
                if orig_depth is None:
                    orig_depth = 50
                    if callable(getattr(self.driver, "get_settings", None)):
                        try:
                            cur_settings = self.driver.get_settings() or {}
                            if isinstance(cur_settings, dict) and cur_settings.get(
                                    "snapshotMaxDepth"):
                                orig_depth = int(cur_settings["snapshotMaxDepth"])
                        except Exception:
                            pass
                    try:
                        setattr(self.driver, "_att_orig_snapshot_max_depth", orig_depth)
                    except Exception:
                        pass
                try:
                    self.driver.update_settings(
                        {
                            "defaultActiveApplication": "com.apple.springboard",
                            "snapshotMaxDepth": 12,
                        }
                    )
                    banner = self._match_top_notification_in_active_context(in_springboard=True)
                except Exception:
                    pass
                finally:
                    try:
                        self.driver.update_settings(
                            {
                                "defaultActiveApplication": "auto",
                                "snapshotMaxDepth": orig_depth,
                            }
                        )
                    except Exception:
                        pass

        try:
            setattr(self.driver, "_last_att_notif_check_ts", time.time())
        except Exception:
            pass
        return banner

    def _wait_until_top_notification_disappears_timed(
            self,
            timeout: Optional[float] = None,
            poll_interval: float = 0.5,
            force: bool = False,
    ) -> Tuple[bool, float]:
        """Wait until any iOS top notification banner blocking the UI disappears.

        Returns:
            (cleared, waited_seconds)
        """
        if self.driver is None:
            return True, 0.0

        wait_timeout = float(
            timeout
            if timeout is not None
            else getattr(
                constants, "ATT_NOTIFICATION_WAIT_TIMEOUT_S",
                self.DEFAULT_NOTIFICATION_WAIT_TIMEOUT_S
            )
        )
        if not force and not getattr(self.driver, "_att_notif_active", False):
            last_ts = getattr(self.driver, "_last_att_notif_check_ts", 0.0)
            if (time.time() - last_ts) < self.NOTIFICATION_CHECK_THROTTLE_S:
                return True, 0.0

        banner = self._find_top_notification_banner()
        if banner is None:
            try:
                setattr(self.driver, "_att_notif_active", False)
            except Exception:
                pass
            return True, 0.0

        try:
            setattr(self.driver, "_att_notif_active", True)
        except Exception:
            pass
        start = time.time()
        self._logger.info(
            f"[ATT Notification] Top notification banner detected ('{banner}'); "
            f"waiting up to {wait_timeout:.0f}s for it to disappear before continuing..."
        )
        while (time.time() - start) < wait_timeout:
            time.sleep(poll_interval)
            banner = self._find_top_notification_banner()
            if banner is None:
                waited = time.time() - start
                try:
                    setattr(self.driver, "_att_notif_active", False)
                except Exception:
                    pass
                self._logger.info(
                    f"[ATT Notification] Top notification banner disappeared after {waited:.1f}s; "
                    "continuing test."
                )
                return True, waited

        waited = time.time() - start
        self._logger.warning(
            f"[ATT Notification] Top notification banner ('{banner}') still visible after "
            f"{wait_timeout:.0f}s; continuing anyway."
        )
        return False, waited

    def _wait_until_top_notification_disappears(
            self,
            timeout: Optional[float] = None,
            poll_interval: float = 0.5,
            force: bool = False,
    ) -> bool:
        """Wait until any iOS top notification banner disappears before performing UI actions."""
        cleared, _waited = self._wait_until_top_notification_disappears_timed(
            timeout=timeout, poll_interval=poll_interval, force=force
        )
        return cleared

    def _ensure_att_foreground(self, wait_after_activate: float = 0.8) -> bool:
        """Ensure AT&T Connected Life is in the foreground (recovers if a 3rd-party notification switched apps)."""
        if self.driver is None or not hasattr(self.driver, "query_app_state"):
            return True
        bundle_id = self._att_bundle_id()
        fg_state = getattr(constants, "APP_STATE_FOREGROUND", 4)
        try:
            state = self.driver.query_app_state(bundle_id)
            if state == fg_state:
                return True
            self._logger.warning(
                f"[ATT Lifecycle] AT&T app ('{bundle_id}') left foreground (state={state}); "
                "reactivating AT&T Connected Life..."
            )
            self.driver.activate_app(bundle_id)
            time.sleep(wait_after_activate)
            return self.driver.query_app_state(bundle_id) == fg_state
        except WebDriverException as err:
            self._logger.warning(
                f"[ATT Lifecycle] Failed checking/reactivating AT&T foreground: {err}")
            return False

    def _att_dismiss_system_alert_if_present(self) -> bool:
        """Best-effort dismissal of iOS permission alerts if one appears after cold launch."""
        with self._att_fast_probe():
            try:
                alerts = self.driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeAlert")
                if not any(a.is_displayed() for a in alerts):
                    return False
                btns = self.driver.find_elements(
                    IOS_PREDICATE_BY,
                    'type == "XCUIElementTypeButton" AND ('
                    'name IN {"Allow", "Allow While Using App", "OK", "Continue", "Not Now"} '
                    'OR label IN {"Allow", "Allow While Using App", "OK", "Continue", "Not Now"})',
                )
                for b in btns:
                    if b.is_displayed():
                        b.click()
                        time.sleep(0.8)
                        return True
            except WebDriverException:
                pass
        return False
