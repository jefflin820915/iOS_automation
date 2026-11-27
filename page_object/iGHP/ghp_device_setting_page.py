"""Page object for GHP Camera Settings / Device Details metadata extraction and Decommission."""

import contextlib
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


class GHPDeviceSettingPage(BasePage):
    """Extracts camera technical info (FW, SN, IP, OTA Status) and executes Decommission in iGHP."""

    FIELD_KEY_ALIASES: Dict[str, Tuple[str, ...]] = {
        "vendor_name": ("vendor name", "vendor"),
        "model_name": ("model name", "product name", "model"),
        "software_version": ("software version", "current version", "current version:",
                             "firmware version"),
        "serial_number": ("serial number", "serial no"),
        "device_ip": ("ip address", "device ip", "ip"),
        "device_id": ("device id", "id", "node id", "matter node id"),
        "ota_status": ("ota status", "status", "status:", "software update status"),
    }

    OTA_BAD_STATUS_KEYWORDS: Tuple[str, ...] = (
        "there may be a problem",
        "failed",
        "error",
        "rolling back",
        "rollback",
    )

    DECOMMISSION_BTN_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND ('
        'name == "Decommission" OR label == "Decommission" OR value == "Decommission" '
        'OR name CONTAINS[c] "Decommission" OR label CONTAINS[c] "Decommission" '
        'OR value CONTAINS[c] "Decommission")'
    )

    DECOMMISSION_ROW_PREDICATE: str = (
        'type IN {"XCUIElementTypeCell", "XCUIElementTypeStaticText", "XCUIElementTypeOther"} AND ('
        'name == "Decommission" OR label == "Decommission" OR value == "Decommission" '
        'OR name CONTAINS[c] "Decommission" OR label CONTAINS[c] "Decommission" '
        'OR value CONTAINS[c] "Decommission")'
    )

    REMOVE_BTN_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND ('
        'name IN {"Remove", "Remove Device", "Remove device", "Remove Camera", "Remove camera", '
        '"Remove Accessory", "Remove accessory", "Delete Device", "Delete device"} '
        'OR label IN {"Remove", "Remove Device", "Remove device", "Remove Camera", "Remove camera", '
        '"Remove Accessory", "Remove accessory", "Delete Device", "Delete device"} '
        'OR value IN {"Remove", "Remove Device", "Remove device", "Remove Camera", "Remove camera", '
        '"Remove Accessory", "Remove accessory", "Delete Device", "Delete device"})'
    )

    REMOVE_ROW_PREDICATE: str = (
        'type IN {"XCUIElementTypeCell", "XCUIElementTypeStaticText", "XCUIElementTypeOther"} AND ('
        'name IN {"Remove", "Remove Device", "Remove device", "Remove Camera", "Remove camera", '
        '"Remove Accessory", "Remove accessory", "Delete Device", "Delete device"} '
        'OR label IN {"Remove", "Remove Device", "Remove device", "Remove Camera", "Remove camera", '
        '"Remove Accessory", "Remove accessory", "Delete Device", "Delete device"} '
        'OR value IN {"Remove", "Remove Device", "Remove device", "Remove Camera", "Remove camera", '
        '"Remove Accessory", "Remove accessory", "Delete Device", "Delete device"})'
    )

    REMOVE_EXACT_LABELS: Tuple[str, ...] = (
        "remove",
        "remove device",
        "remove camera",
        "remove accessory",
        "delete device",
        "delete accessory",
    )

    REMOVE_EXCLUDED_KEYWORDS: Tuple[str, ...] = (
        "history",
        "cancel",
        "video",
        "recording",
        "event",
        "zone",
        "schedule",
        "favorite",
        "activity",
        "light",
        "chime",
    )

    DECOMMISSION_DESCENDANT_XPATH: str = (
        '//XCUIElementTypeButton[.//XCUIElementTypeStaticText['
        '@name="Decommission" or @label="Decommission" or @value="Decommission"]] | '
        '//XCUIElementTypeCell[.//XCUIElementTypeStaticText['
        '@name="Decommission" or @label="Decommission" or @value="Decommission"]]'
    )

    ALERT_CONTAINER_PREDICATE: str = (
        'type IN {"XCUIElementTypeAlert", "XCUIElementTypeSheet"} AND ('
        'name CONTAINS[c] "Decommission" OR label CONTAINS[c] "Decommission" '
        'OR name CONTAINS[c] "Remove" OR label CONTAINS[c] "Remove" '
        'OR name CONTAINS[c] "Are you sure" OR label CONTAINS[c] "Are you sure")'
    )

    WEB_SIGNIN_ALERT_PREDICATE: str = (
        'type == "XCUIElementTypeAlert" AND ('
        'name CONTAINS[c] "Wants to Use" OR label CONTAINS[c] "Wants to Use" '
        'OR name CONTAINS[c] "Sign In" OR label CONTAINS[c] "Sign In" '
        'OR name CONTAINS[c] "home.google.com" OR label CONTAINS[c] "home.google.com" '
        'OR name CONTAINS "想要使用" OR label CONTAINS "想要使用" '
        'OR name CONTAINS "登入" OR label CONTAINS "登入")'
    )

    WEB_SIGNIN_CONTINUE_BTN_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND ('
        'name IN {"Continue", "繼續", "继续", "Allow", "允許"} '
        'OR label IN {"Continue", "繼續", "继续", "Allow", "允許"})'
    )

    DECOMMISSION_WEBVIEW_PREDICATE: str = (
        'type == "XCUIElementTypeWebView" '
        'OR (type == "XCUIElementTypeOther" AND ('
        'name == "TopBrowserBar" OR label == "TopBrowserBar" '
        'OR name == "Google Home Platform" OR label == "Google Home Platform"))'
    )

    WEBVIEW_DELETE_EXACT_LABELS: Tuple[str, ...] = (
        "刪除",
        "删除",
        "移除",
        "刪除攝影機",
        "删除摄像机",
        "移除攝影機",
        "移除裝置",
        "Delete",
        "Remove",
        "Delete camera",
        "Remove camera",
        "Remove device",
        "Confirm",
        "確定",
        "确定",
        "確認",
        "确认",
    )

    WEBVIEW_POST_DELETE_CLOSE_LABELS: Tuple[str, ...] = (
        "完成",
        "關閉",
        "关闭",
        "好",
        "Done",
        "OK",
        "Close",
    )

    WEBVIEW_CANCEL_KEYWORDS: Tuple[str, ...] = (
        "取消",
        "cancel",
    )

    BACK_OR_CLOSE_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND ('
        'name == "BackButton" OR label == "Home" OR name == "Back" OR label == "Back" '
        'OR name == "xmark" OR label == "Close" OR name == "Done" OR label == "Done")'
    )

    def __init__(self, driver: WebDriver, timeout: float = 10.0) -> None:
        self.APP_BUNDLE_ID = get_ghp_bundle_id()
        super().__init__(driver, timeout=timeout)
        self._logger = logging_utils.get_logger(__name__, "ghp_device_setting")
        self.device_tech_info: Dict[str, str] = {}

    @classmethod
    def _resolve_page(cls, ctx: Any) -> "GHPDeviceSettingPage":
        if isinstance(ctx, cls):
            return ctx
        existing = getattr(ctx, "ghpdevicesettingpage", None)
        if isinstance(existing, cls):
            return existing
        session = getattr(ctx, "session", None)
        if session is not None and isinstance(getattr(session, "ghpdevicesettingpage", None), cls):
            return session.ghpdevicesettingpage
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
        for attr in ("value", "label", "name"):
            try:
                val = elem.get_attribute(attr)
                if val is not None and str(val).strip():
                    return str(val).strip()
            except (StaleElementReferenceException, WebDriverException):
                continue
        try:
            return (elem.text or "").strip()
        except (StaleElementReferenceException, WebDriverException):
            return ""

    def _read_kv_text(self, elem: WebElement) -> str:
        """Fast attribute read for Settings StaticTexts ('label' -> 'value') minimizing WDA RPCs."""
        for attr in ("label", "value"):
            try:
                val = elem.get_attribute(attr)
                if val is not None and str(val).strip():
                    return str(val).strip()
            except (StaleElementReferenceException, WebDriverException):
                continue
        return ""

    def _scroll_settings(
            self,
            direction: str = "down",
            x_ratio: float = 0.5,
            span: Tuple[float, float] = (0.74, 0.26),
    ) -> None:
        w, h = self._get_window_dimensions()
        # Clamp x strictly inside [90, w-40] so drags never enter iOS's left-edge back-pop zone
        cx = max(90, min(w - 40, int(w * x_ratio)))
        high_r, low_r = span
        if direction == "down":
            from_y, to_y = int(h * high_r), int(h * low_r)
        else:
            from_y, to_y = int(h * low_r), int(h * high_r)
        try:
            self.driver.execute_script(
                "mobile: dragFromToForDuration",
                {"duration": 0.30, "fromX": cx, "fromY": from_y, "toX": cx, "toY": to_y},
            )
        except WebDriverException:
            try:
                swipe_dir = "up" if direction == "down" else "down"
                self.driver.execute_script("mobile: swipe", {"direction": swipe_dir})
            except WebDriverException:
                pass
        time.sleep(0.6)

    def _get_settings_scroll_signature(self) -> Tuple[Tuple[str, int], ...]:
        """Capture a lightweight signature of bottom-most visible Settings items to detect scroll movement."""
        if self._is_on_camera_player_screen():
            return (("__PLAYER_SCREEN__", 0),)
        _win_w, win_h = self._get_window_dimensions()
        sig: List[Tuple[str, int]] = []
        with self._fast_probe():
            for cls_name in ("XCUIElementTypeStaticText", "XCUIElementTypeButton"):
                try:
                    elems = self.driver.find_elements(AppiumBy.CLASS_NAME, cls_name)
                except WebDriverException:
                    continue
                for el in elems[-6:]:
                    try:
                        r = el.rect
                        if not isinstance(r, dict):
                            continue
                        y = float(r.get("y", -1))
                        h = float(r.get("height", 0))
                        if h <= 0 or y < 0 or y > float(win_h):
                            continue
                        txt = self._read_kv_text(el) or self._read_text(el)
                        if txt:
                            sig.append((txt, int(round(y / 4.0))))
                    except (StaleElementReferenceException, WebDriverException, TypeError,
                            ValueError):
                        continue
                if sig:
                    break
        return tuple(sig[-6:])

    def _scroll_settings_down_checked(self) -> bool:
        """Scroll Settings down via pure vertical touch drags (avoiding mobile:scroll responder dismissal)."""
        if self._is_on_camera_player_screen():
            return False
        if self._find_settings_decommission_button() is not None:
            return False

        before_sig = self._get_settings_scroll_signature()
        self._scroll_settings("down", x_ratio=0.5)
        if self._is_on_camera_player_screen():
            return False
        if self._find_settings_decommission_button() is not None:
            return True

        after_sig = self._get_settings_scroll_signature()
        if not before_sig or after_sig != before_sig:
            return True

        # Primary center drag was absorbed (e.g. landed on an interactive Picker/Switch):
        # try ONE vertical drag on the left-middle label column (x ~ 124px, safe from left-edge pop).
        self._scroll_settings("down", x_ratio=0.32)
        if self._is_on_camera_player_screen():
            return False
        if self._find_settings_decommission_button() is not None:
            return True
        return self._get_settings_scroll_signature() != before_sig

    @classmethod
    def _match_canonical_key(cls, raw_label: str) -> Optional[str]:
        norm = " ".join(raw_label.strip().lower().rstrip(":").split())
        if not norm:
            return None
        for canonical, aliases in cls.FIELD_KEY_ALIASES.items():
            for alias in aliases:
                if norm == alias.rstrip(":"):
                    return canonical
        return None

    def _collect_visible_kv_pairs(self, collected: Dict[str, str]) -> None:
        """Scan visible StaticText pairs (and Cell rows when needed) for technical metadata."""
        if self._is_on_camera_player_screen():
            return
        with self._fast_probe():
            # 1. Fast single-query pass over StaticText elements with same-row HStack y-alignment
            try:
                all_texts = self.driver.find_elements(AppiumBy.CLASS_NAME,
                                                      "XCUIElementTypeStaticText")
            except WebDriverException:
                all_texts = []

            paired_items: List[Tuple[WebElement, str, Optional[str]]] = []
            for el in all_texts:
                txt = self._read_kv_text(el)
                if txt:
                    paired_items.append((el, txt, self._match_canonical_key(txt)))

            rect_cache: Dict[int, Optional[Dict[str, float]]] = {}

            def _get_rect(i: int) -> Optional[Dict[str, float]]:
                if i not in rect_cache:
                    try:
                        r = paired_items[i][0].rect
                        rect_cache[i] = r if isinstance(r, dict) else None
                    except (StaleElementReferenceException, WebDriverException):
                        rect_cache[i] = None
                return rect_cache[i]

            unmatched_key_seen = False
            for idx, (_el, _txt, key) in enumerate(paired_items):
                if not key:
                    continue
                if key in collected and collected[key] not in ("", "UNKNOWN", "?"):
                    continue

                chosen_val: Optional[str] = None
                kr = _get_rect(idx)
                k_cx = float(kr.get("x", 0)) + float(kr.get("width", 0)) / 2.0 if kr else 0.0
                k_cy = float(kr.get("y", 0)) + float(kr.get("height", 0)) / 2.0 if kr else 0.0
                has_distinct_geometry = False

                if kr and float(kr.get("height", 0)) > 0:
                    best_dy = 999.0
                    lo = max(0, idx - 2)
                    hi = min(len(paired_items), idx + 5)
                    for cand_idx in range(lo, hi):
                        if cand_idx == idx:
                            continue
                        _cel, ctxt, ckey = paired_items[cand_idx]
                        if ckey is not None or not ctxt.strip() or ctxt.strip() == "?":
                            continue
                        cr = _get_rect(cand_idx)
                        if not cr or float(cr.get("height", 0)) <= 0:
                            continue
                        c_cx = float(cr.get("x", 0)) + float(cr.get("width", 0)) / 2.0
                        c_cy = float(cr.get("y", 0)) + float(cr.get("height", 0)) / 2.0
                        if abs(c_cx - k_cx) > 1.0 or abs(c_cy - k_cy) > 1.0:
                            has_distinct_geometry = True
                        dy = abs(c_cy - k_cy)
                        if c_cx > k_cx and dy <= 28.0 and dy < best_dy:
                            best_dy = dy
                            chosen_val = ctxt.strip()

                if chosen_val is None and not has_distinct_geometry and (idx + 1) < len(
                        paired_items):
                    _nel, ntxt, nkey = paired_items[idx + 1]
                    if nkey is None and ntxt.strip() and ntxt.strip() != "?":
                        chosen_val = ntxt.strip()

                if chosen_val:
                    collected[key] = chosen_val
                else:
                    unmatched_key_seen = True

            # Only query per-Cell children when top-level StaticTexts were absent (unit-test cell mocks)
            # or a visible key label had no matched value.
            if paired_items and not unmatched_key_seen:
                return

            # 2. Fallback: inspect XCUIElementTypeCell rows
            try:
                cells = self.driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeCell")
            except WebDriverException:
                cells = []
            for cell in cells:
                try:
                    texts = cell.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText")
                except WebDriverException:
                    continue
                vals: List[str] = []
                for t in texts:
                    v = self._read_kv_text(t) or self._read_text(t)
                    if v and v not in vals:
                        vals.append(v)
                if len(vals) >= 2:
                    key = self._match_canonical_key(vals[0])
                    val = vals[1].strip()
                    if key and val and val != "?" and self._match_canonical_key(val) is None:
                        if key not in collected or collected[key] in ("", "UNKNOWN", "?"):
                            collected[key] = val

    def _store_tech_info(self, owner: Any, info: Dict[str, str]) -> None:
        """Persist extracted device technical metadata onto Page, Session, TestCase, and WebDriver."""
        merged = {
            "device_id": info.get("device_id", "UNKNOWN"),
            "serial_number": info.get("serial_number", "UNKNOWN"),
            "software_version": info.get("software_version", "UNKNOWN"),
            "device_ip": info.get("device_ip", "UNKNOWN"),
            "vendor_name": info.get("vendor_name", "UNKNOWN"),
            "model_name": info.get("model_name", "UNKNOWN"),
            "ota_status": info.get("ota_status", ""),
        }
        self.device_tech_info = dict(merged)
        for target in (owner, getattr(owner, "session", None), getattr(self, "session", None),
                       self.driver):
            if target is not None:
                try:
                    setattr(target, "device_tech_info", dict(merged))
                except Exception:
                    pass

    def get_device_information(
            self, max_scrolls: int = 8, verify_ota_status: bool = True
    ) -> Dict[str, str]:
        """Extract Software Version, Serial Number, IP Address, Device ID, and OTA Status from Camera Settings."""
        page = GHPDeviceSettingPage._resolve_page(self)
        page._logger.info("Extracting camera technical information from GHP Settings...")
        collected: Dict[str, str] = {}

        # Wait briefly for Settings rows to initialize (CameraSettingsView shows ProgressView while loading)
        deadline = time.time() + 8.0
        while time.time() < deadline:
            if page._is_on_camera_player_screen():
                page._reopen_settings_if_on_player_page()
            page._collect_visible_kv_pairs(collected)
            if collected:
                break
            with page._fast_probe():
                try:
                    any_text = page.driver.find_elements(
                        AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText"
                    )
                    if len(any_text) >= 3:
                        break
                except WebDriverException:
                    pass
            time.sleep(0.4)

        reopen_attempts = 0
        unchanged_scrolls = 0
        for _step in range(max_scrolls):
            if reopen_attempts < 2 and page._reopen_settings_if_on_player_page():
                reopen_attempts += 1
                unchanged_scrolls = 0
            elif page._is_on_camera_player_screen():
                break

            page._collect_visible_kv_pairs(collected)
            # 'Decommission' is the very last section of CameraSettingsView / DeviceDetailsView:
            # once visible, we have reached the bottom and collected all visible Device Information rows!
            if page._find_settings_decommission_button() is not None:
                break

            moved = page._scroll_settings_down_checked()
            if moved:
                unchanged_scrolls = 0
            else:
                unchanged_scrolls += 1
                if unchanged_scrolls >= 2:
                    break
        page._collect_visible_kv_pairs(collected)
        page._store_tech_info(self, collected)

        page._logger.info(
            "[GHP Device Info] "
            f"Vendor='{collected.get('vendor_name', 'UNKNOWN')}' | "
            f"Model='{collected.get('model_name', 'UNKNOWN')}' | "
            f"FW='{collected.get('software_version', 'UNKNOWN')}' | "
            f"SN='{collected.get('serial_number', 'UNKNOWN')}' | "
            f"IP='{collected.get('device_ip', 'UNKNOWN')}' | "
            f"ID='{collected.get('device_id', 'UNKNOWN')}' | "
            f"OTA='{collected.get('ota_status', 'N/A')}'"
        )

        ota_status = collected.get("ota_status", "").strip()
        if verify_ota_status and ota_status:
            if any(bad in ota_status.lower() for bad in page.OTA_BAD_STATUS_KEYWORDS):
                msg = f"Camera Settings reported abnormal OTA Status: '{ota_status}'"
                page._logger.error(msg)
                BasePage.capture_failure_screenshot(page.driver, reason=msg, force=True, lock=True)
                raise AssertionError(msg)
        return dict(page.device_tech_info)

    def _evaluate_decommission_candidate(
            self,
            elem: WebElement,
            win_w: int,
            win_h: int,
    ) -> Optional[Tuple[int, int, int, float]]:
        """Score a candidate element for Settings 'Decommission', returning sort key or None."""
        try:
            elem_type = str(elem.get_attribute("type") or "")
        except (StaleElementReferenceException, WebDriverException):
            elem_type = ""

        txt = self._read_text(elem)
        norm = " ".join(txt.split())
        low = norm.lower()
        if not low or len(low) > 35 or any(ex in low for ex in self.REMOVE_EXCLUDED_KEYWORDS):
            return None
        if "decommission" not in low and low not in self.REMOVE_EXACT_LABELS:
            return None

        try:
            displayed = bool(elem.is_displayed())
        except (StaleElementReferenceException, WebDriverException):
            displayed = False

        rect = None
        try:
            rect = elem.rect
        except (StaleElementReferenceException, WebDriverException):
            rect = None

        cy = 0.0
        in_viewport = False
        if isinstance(rect, dict):
            try:
                x = float(rect.get("x", 0))
                y = float(rect.get("y", 0))
                w = float(rect.get("width", 0))
                h = float(rect.get("height", 0))
            except (TypeError, ValueError):
                w, h, x, y = 0.0, 0.0, 0.0, 0.0
            if w > 0 or h > 0:
                if w < 10 or h < 8 or h > 180:
                    return None
                cx = x + w / 2.0
                cy = y + h / 2.0
                in_viewport = (
                        (0.0 <= cx <= float(win_w))
                        and (28.0 <= cy <= float(win_h + 6))
                        and (y < float(win_h - 8))
                )
                if not in_viewport:
                    return None

        if not displayed and not in_viewport:
            return None

        if elem_type == "XCUIElementTypeButton":
            type_rank = 0
        elif elem_type == "XCUIElementTypeCell":
            type_rank = 1
        elif elem_type == "XCUIElementTypeStaticText":
            type_rank = 2
        else:
            type_rank = 3

        if low == "decommission":
            exact_rank = 0
        elif low in self.REMOVE_EXACT_LABELS:
            exact_rank = 1
        else:
            exact_rank = 2
        return (0 if displayed else 1, type_rank, exact_rank, -cy)

    def _find_settings_decommission_button(self) -> Optional[WebElement]:
        """Locate the 'Decommission' / 'Remove' button/row in Camera Settings."""
        win_w, win_h = self._get_window_dimensions()
        locators: Tuple[Tuple[str, str], ...] = (
            (IOS_PREDICATE_BY, self.DECOMMISSION_BTN_PREDICATE),
            (AppiumBy.ACCESSIBILITY_ID, "Decommission"),
            (IOS_PREDICATE_BY, self.DECOMMISSION_ROW_PREDICATE),
            (AppiumBy.XPATH, self.DECOMMISSION_DESCENDANT_XPATH),
            (IOS_PREDICATE_BY, self.REMOVE_BTN_PREDICATE),
            (IOS_PREDICATE_BY, self.REMOVE_ROW_PREDICATE),
        )
        scored: List[Tuple[Tuple[int, int, int, float], WebElement]] = []
        with self._fast_probe():
            for idx, (by, query) in enumerate(locators):
                try:
                    elems = self.driver.find_elements(by, query)
                except WebDriverException:
                    continue
                for el in elems:
                    score = self._evaluate_decommission_candidate(el, win_w, win_h)
                    if score is None:
                        continue
                    # Fast return when the primary query finds a displayed exact Button
                    if idx == 0 and score[0] == 0 and score[1] == 0 and score[2] == 0:
                        return el
                    scored.append((score, el))

            if not scored:
                # Last-resort tail scan across Button / StaticText / Cell in case predicate matching missed
                for cls_name in (
                        "XCUIElementTypeButton",
                        "XCUIElementTypeCell",
                        "XCUIElementTypeStaticText",
                ):
                    try:
                        elems = self.driver.find_elements(AppiumBy.CLASS_NAME, cls_name)
                    except WebDriverException:
                        continue
                    for el in elems[-12:]:
                        txt = " ".join(self._read_text(el).split()).lower()
                        if "decommission" not in txt and txt not in self.REMOVE_EXACT_LABELS:
                            continue
                        score = self._evaluate_decommission_candidate(el, win_w, win_h)
                        if score is not None:
                            scored.append((score, el))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0])
        return scored[0][1]

    def _is_on_camera_player_screen(self) -> bool:
        """Return True if the app popped back from Camera Settings onto the Camera Live / Player screen."""
        player_pred = (
            'type == "XCUIElementTypeButton" AND ('
            'name IN {"Settings", "Turn Camera OFF", "Turn Camera ON", '
            '"Microphone Off", "Microphone On", "Go to live", "google_symbols/menu_symbol"} '
            'OR label IN {"Settings", "Turn Camera OFF", "Turn Camera ON", '
            '"Microphone Off", "Microphone On", "Go to live"})'
        )
        settings_pred = (
            'type == "XCUIElementTypeStaticText" AND ('
            'label IN {"Vendor Name", "Model Name", "Product Name", "Software Version", '
            '"Device Information", "Diagnostics Settings", "Microphone Settings", '
            '"Recording Settings", "Recording Mode", "Activity Zones", "Event Settings", '
            '"Event Triggers", "Doorbell Settings", "Audio Settings", "Status Light Brightness", '
            '"Device Settings", "Device Details", "Device Trait", "Basic Information Trait"} '
            'OR value IN {"Vendor Name", "Model Name", "Product Name", "Software Version"})'
        )
        with self._fast_probe():
            try:
                p_elems = self.driver.find_elements(IOS_PREDICATE_BY, player_pred)
                on_player = any(e.is_displayed() for e in p_elems)
            except WebDriverException:
                on_player = False
            if not on_player:
                return False
            try:
                s_elems = self.driver.find_elements(IOS_PREDICATE_BY, settings_pred)
                if any(e.is_displayed() for e in s_elems):
                    return False
            except WebDriverException:
                pass
            return True

    def _reopen_settings_if_on_player_page(self) -> bool:
        """If GHP popped back to Camera Live / Player screen, tap 'Settings' and wait for rows to initialize."""
        if not self._is_on_camera_player_screen():
            return False
        self._logger.warning(
            "[GHP Settings] Detected Camera Live / Player screen instead of Settings; "
            "re-opening Camera Settings..."
        )
        from page_object.iGHP.ghp_camera_live_page import GHPCameraLivePage

        reopened = bool(GHPCameraLivePage.click_setting_btn(self))
        if reopened:
            # Wait briefly if CameraSettingsView is still showing its initial ProgressView()
            wait_end = time.time() + 4.0
            while time.time() < wait_end:
                if not self._is_on_camera_player_screen():
                    with self._fast_probe():
                        try:
                            spinners = self.driver.find_elements(
                                AppiumBy.CLASS_NAME, "XCUIElementTypeActivityIndicator"
                            )
                            if not any(sp.is_displayed() for sp in spinners):
                                break
                        except WebDriverException:
                            break
                time.sleep(0.4)
        return reopened

    def _log_decommission_probe_diagnostics(self) -> None:
        """Log visible buttons/labels on Settings screen to aid diagnosing missed 'Decommission' elements."""
        samples: List[str] = []
        with self._fast_probe():
            for cls_name in (
                    "XCUIElementTypeButton",
                    "XCUIElementTypeStaticText",
                    "XCUIElementTypeCell",
            ):
                try:
                    elems = self.driver.find_elements(AppiumBy.CLASS_NAME, cls_name)
                except WebDriverException:
                    continue
                for el in elems[-12:]:
                    try:
                        txt = self._read_text(el)
                        if not txt:
                            continue
                        rect = el.rect if hasattr(el, "rect") else {}
                        disp = el.is_displayed()
                        y = int(float(rect.get("y", -1))) if isinstance(rect, dict) else -1
                        samples.append(
                            f"{cls_name.replace('XCUIElementType', '')}({txt!r},disp={disp},y={y})")
                    except (StaleElementReferenceException, WebDriverException, TypeError,
                            ValueError):
                        continue
        if samples:
            self._logger.info(
                f"[Decommission Probe] Visible tail elements: {', '.join(samples[-15:])}"
            )

    def _get_window_dimensions(self) -> Tuple[int, int]:
        try:
            win = self.driver.get_window_size()
            return int(win.get("width", 390)), int(win.get("height", 844))
        except Exception:
            return 390, 844

    def _is_web_signin_alert_open(self) -> bool:
        """Return True if iOS ASWebAuthenticationSession Sign-In prompt ('Wants to Use ... to Sign In') is open."""
        with self._fast_probe():
            try:
                alerts = self.driver.find_elements(IOS_PREDICATE_BY,
                                                   self.WEB_SIGNIN_ALERT_PREDICATE)
                if any(a.is_displayed() for a in alerts):
                    return True
            except WebDriverException:
                pass
            try:
                btns = self.driver.find_elements(
                    IOS_PREDICATE_BY, self.WEB_SIGNIN_CONTINUE_BTN_PREDICATE
                )
                if any(b.is_displayed() for b in btns):
                    return True
            except WebDriverException:
                pass
        return False

    def _is_decommission_webview_open(self) -> bool:
        """Return True if ASWebAuthenticationSession / SafariViewService WebView ('preview.home.google.com') is open."""
        with self._fast_probe():
            try:
                elems = self.driver.find_elements(IOS_PREDICATE_BY,
                                                  self.DECOMMISSION_WEBVIEW_PREDICATE)
            except WebDriverException:
                return False
            for el in elems:
                try:
                    if el.is_displayed():
                        return True
                    r = el.rect
                    if float(r.get("width", 0)) > 0 and float(r.get("height", 0)) > 0:
                        return True
                except (StaleElementReferenceException, WebDriverException):
                    continue
        return False

    def _has_any_decommission_prompt_open(self) -> bool:
        """Return True if native Decommission alert, Sign-In alert, or removal WebView is already visible."""
        if self._is_web_signin_alert_open() or self._is_decommission_webview_open():
            return True
        with self._fast_probe():
            try:
                alerts = self.driver.find_elements(IOS_PREDICATE_BY, self.ALERT_CONTAINER_PREDICATE)
                if any(a.is_displayed() for a in alerts):
                    return True
            except WebDriverException:
                pass
            try:
                btns = self.driver.execute_script("mobile: alert", {"action": "getButtons"})
                if isinstance(btns, (list, tuple)) and btns:
                    return True
            except Exception:
                pass
        return False

    def _find_webview_button_by_labels(
            self,
            exact_labels: Tuple[str, ...],
            substring_keywords: Tuple[str, ...] = (),
    ) -> Optional[WebElement]:
        """Locate a button inside the SafariViewService WebView content area (excluding browser chrome)."""
        _win_w, win_h = self._get_window_dimensions()
        exact_lower = {lbl.lower() for lbl in exact_labels}
        with self._fast_probe():
            try:
                btns = self.driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeButton")
            except WebDriverException:
                btns = []

            candidates: List[Tuple[int, WebElement]] = []
            for btn in btns:
                try:
                    r = btn.rect
                    y = float(r.get("y", 0))
                    w = float(r.get("width", 0))
                    h = float(r.get("height", 0))
                    if w <= 0 or h <= 0:
                        continue
                    # Exclude TopBrowserBar (y < 105) and bottom Safari toolbar (y > win_h - 55)
                    if y < 105 or y > (win_h - 55):
                        continue
                    txt = self._read_text(btn).strip()
                    if not txt:
                        continue
                    low = txt.lower()
                    if any(ck in low for ck in self.WEBVIEW_CANCEL_KEYWORDS):
                        continue
                    if low in exact_lower:
                        candidates.append((0, btn))
                    elif substring_keywords and any(kw.lower() in low for kw in substring_keywords):
                        candidates.append((1, btn))
                except (StaleElementReferenceException, WebDriverException):
                    continue

            if candidates:
                candidates.sort(key=lambda item: item[0])
                return candidates[0][1]

            # Fallback if WebKit exposes the action button as Link or Other
            for cls_name in ("XCUIElementTypeLink", "XCUIElementTypeOther"):
                try:
                    others = self.driver.find_elements(AppiumBy.CLASS_NAME, cls_name)
                except WebDriverException:
                    continue
                for el in others:
                    try:
                        r = el.rect
                        y = float(r.get("y", 0))
                        w = float(r.get("width", 0))
                        h = float(r.get("height", 0))
                        if w <= 0 or h <= 0 or h > 100 or y < 200 or y > (win_h - 55):
                            continue
                        txt = self._read_text(el).strip()
                        if txt and txt.lower() in exact_lower:
                            return el
                    except (StaleElementReferenceException, WebDriverException):
                        continue
        return None

    def _find_webview_delete_button(self) -> Optional[WebElement]:
        """Locate the removal confirmation button ('刪除' / 'Delete' / 'Remove') inside preview.home.google.com."""
        return self._find_webview_button_by_labels(
            self.WEBVIEW_DELETE_EXACT_LABELS,
            substring_keywords=("刪除", "删除", "移除", "delete", "remove"),
        )

    def _click_webview_button_with_tap_fallback(self, btn: WebElement, desc: str) -> bool:
        """Click a SafariViewService XPC WebView button, falling back to coordinate tap if .click() is ignored."""
        _win_w, win_h = self._get_window_dimensions()
        cx: Optional[int] = None
        cy: Optional[int] = None
        try:
            r = btn.rect
            x = float(r.get("x", 0))
            y = float(r.get("y", 0))
            w = float(r.get("width", 0))
            h = float(r.get("height", 0))
            if w > 0 and h > 0 and (y + h) > (win_h - 55):
                self._scroll_settings("down")
                refreshed = self._find_webview_delete_button()
                if refreshed is not None:
                    btn = refreshed
                    r = btn.rect
                    x = float(r.get("x", 0))
                    y = float(r.get("y", 0))
                    w = float(r.get("width", 0))
                    h = float(r.get("height", 0))
            if w > 0 and h > 0:
                cx = int(x + w / 2.0)
                cy = int(y + h / 2.0)
        except (StaleElementReferenceException, WebDriverException):
            pass

        try:
            btn.click()
        except (StaleElementReferenceException, WebDriverException):
            if cx is not None and cy is not None:
                try:
                    self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                    return True
                except WebDriverException:
                    return False
            return False

        time.sleep(1.0)
        if (
                cx is not None
                and cy is not None
                and self._is_decommission_webview_open()
                and self._find_webview_delete_button() is not None
        ):
            self._logger.info(
                f"[Decommission] {desc} still visible in WebView after .click(); "
                f"tapping coordinates ({cx}, {cy})..."
            )
            try:
                self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
            except WebDriverException:
                pass
        return True

    def _try_accept_signin_or_native_decommission_alert(self) -> Optional[str]:
        """Handle native 'Decommission' alert OR iOS ASWebAuthenticationSession 'Continue' Sign-In alert.

        Returns:
            'native_decommission', 'web_signin_continue', or None if no alert was present.
        """
        win_w, win_h = self._get_window_dimensions()
        with self._fast_probe():
            # 1. Native 'Decommission' / 'Remove' confirmation alert/sheet
            alert_btns: List[WebElement] = []
            for chain in (
                    '**/XCUIElementTypeAlert/**/XCUIElementTypeButton[`name == "Decommission" OR label == "Decommission"`]',
                    '**/XCUIElementTypeSheet/**/XCUIElementTypeButton[`name == "Decommission" OR label == "Decommission"`]',
                    '**/XCUIElementTypeAlert/**/XCUIElementTypeButton[`name IN {"Remove", "Remove Device", "Delete"} OR label IN {"Remove", "Remove Device", "Delete"}`]',
                    '**/XCUIElementTypeSheet/**/XCUIElementTypeButton[`name IN {"Remove", "Remove Device", "Delete"} OR label IN {"Remove", "Remove Device", "Delete"}`]',
            ):
                try:
                    alert_btns.extend(self.driver.find_elements(IOS_CLASS_CHAIN_BY, chain))
                except WebDriverException:
                    pass

            if not alert_btns:
                for btn_pred in (self.DECOMMISSION_BTN_PREDICATE, self.REMOVE_BTN_PREDICATE):
                    try:
                        all_btns = self.driver.find_elements(IOS_PREDICATE_BY, btn_pred)
                        visible_btns = [b for b in all_btns if b.is_displayed()]
                        if len(visible_btns) >= 2:
                            visible_btns.sort(key=lambda b: b.rect.get("y", 9999))
                            alert_btns = [visible_btns[0]]
                            break
                    except WebDriverException:
                        pass

            for confirm_btn in alert_btns:
                rect = None
                try:
                    rect = confirm_btn.rect
                except WebDriverException:
                    rect = None
                confirm_label = self._read_text(confirm_btn) or "Decommission"
                self._logger.info(f"Confirming '{confirm_label}' in alert/confirmation dialog...")
                try:
                    confirm_btn.click()
                    time.sleep(1.0)
                except WebDriverException:
                    pass
                still_open = False
                try:
                    alerts = self.driver.find_elements(IOS_PREDICATE_BY,
                                                       self.ALERT_CONTAINER_PREDICATE)
                    still_open = any(a.is_displayed() for a in alerts)
                except WebDriverException:
                    still_open = False
                if still_open:
                    try:
                        self.driver.execute_script(
                            "mobile: alert", {"action": "accept", "buttonLabel": confirm_label}
                        )
                        time.sleep(0.8)
                    except WebDriverException:
                        pass
                    if rect:
                        cx = int(rect["x"] + rect["width"] / 2)
                        cy = int(rect["y"] + rect["height"] / 2)
                        try:
                            self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                            time.sleep(1.0)
                        except WebDriverException:
                            pass
                return "native_decommission"

            # 2. iOS ASWebAuthenticationSession Sign-In alert ('... Wants to Use "preview.home.google.com" to Sign In' -> 'Continue')
            signin_alerts: List[WebElement] = []
            try:
                signin_alerts = list(
                    self.driver.find_elements(IOS_PREDICATE_BY, self.WEB_SIGNIN_ALERT_PREDICATE)
                )
            except WebDriverException:
                signin_alerts = []

            cont_btns: List[WebElement] = []
            try:
                cont_btns = [
                    b
                    for b in self.driver.find_elements(
                        IOS_PREDICATE_BY, self.WEB_SIGNIN_CONTINUE_BTN_PREDICATE
                    )
                    if b.is_displayed() or signin_alerts
                ]
            except WebDriverException:
                cont_btns = []

            if not cont_btns and signin_alerts:
                for al in signin_alerts:
                    try:
                        cont_btns.extend(
                            al.find_elements(IOS_PREDICATE_BY,
                                             self.WEB_SIGNIN_CONTINUE_BTN_PREDICATE)
                        )
                    except WebDriverException:
                        pass

            for cont_btn in cont_btns:
                btn_label = self._read_text(cont_btn) or "Continue"
                cx, cy = int(win_w * 0.69), int(win_h * 0.60)
                try:
                    r = cont_btn.rect
                    if float(r.get("width", 0)) > 0 and float(r.get("height", 0)) > 0:
                        cx = int(float(r["x"]) + float(r["width"]) / 2.0)
                        cy = int(float(r["y"]) + float(r["height"]) / 2.0)
                except (StaleElementReferenceException, WebDriverException):
                    pass

                self._logger.info(
                    f"[Decommission] Clicking '{btn_label}' on 'home.google.com' Sign-In alert..."
                )
                try:
                    cont_btn.click()
                except (StaleElementReferenceException, WebDriverException):
                    try:
                        self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                    except WebDriverException:
                        pass
                time.sleep(0.8)

                # Verify Sign-In alert closed; follow up with coordinate tap + mobile:alert if XPC ignored .click()
                still_signin = False
                try:
                    rem_btns = self.driver.find_elements(
                        IOS_PREDICATE_BY, self.WEB_SIGNIN_CONTINUE_BTN_PREDICATE
                    )
                    still_signin = any(b.is_displayed() for b in rem_btns)
                except WebDriverException:
                    still_signin = False
                if still_signin:
                    self._logger.info(
                        f"[Decommission] '{btn_label}' still visible after .click(); "
                        f"tapping ({cx}, {cy}) and mobile:alert accept..."
                    )
                    try:
                        self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                    except WebDriverException:
                        pass
                    try:
                        self.driver.execute_script(
                            "mobile: alert", {"action": "accept", "buttonLabel": btn_label}
                        )
                    except WebDriverException:
                        pass
                    time.sleep(0.8)
                return "web_signin_continue"

            # 3. SpringBoard-hosted system alert outside app tree (via WDA 'mobile: alert')
            raw_buttons = None
            try:
                raw_buttons = self.driver.execute_script("mobile: alert", {"action": "getButtons"})
            except Exception:
                raw_buttons = None

            if isinstance(raw_buttons, (list, tuple)) and raw_buttons:
                matched_btn: Optional[str] = None
                for candidate in (
                        "Decommission",
                        "Continue",
                        "繼續",
                        "继续",
                        "Allow",
                        "允許",
                        "Remove Device",
                        "Remove",
                        "Delete",
                        "OK",
                        "好",
                ):
                    for b in raw_buttons:
                        if str(b).strip().lower() == candidate.lower():
                            matched_btn = str(b).strip()
                            break
                    if matched_btn:
                        break
                if matched_btn:
                    self._logger.info(
                        f"[Decommission] Accepting SpringBoard system alert via '{matched_btn}' "
                        f"(buttons={list(raw_buttons)})..."
                    )
                    accepted = False
                    try:
                        self.driver.execute_script(
                            "mobile: alert", {"action": "accept", "buttonLabel": matched_btn}
                        )
                        accepted = True
                    except Exception:
                        try:
                            self.driver.switch_to.alert.accept()
                            accepted = True
                        except Exception:
                            pass
                    time.sleep(0.7)
                    still_btns = None
                    try:
                        still_btns = self.driver.execute_script(
                            "mobile: alert", {"action": "getButtons"}
                        )
                    except Exception:
                        still_btns = None
                    if not accepted or (
                            isinstance(still_btns, (list, tuple))
                            and any(
                        str(b).strip().lower() == matched_btn.lower() for b in still_btns)
                    ):
                        try:
                            self.driver.execute_script(
                                "mobile: tap",
                                {"x": int(win_w * 0.69), "y": int(win_h * 0.60)},
                            )
                        except WebDriverException:
                            pass
                        time.sleep(0.6)
                    return (
                        "native_decommission"
                        if "decommission" in matched_btn.lower()
                        else "web_signin_continue"
                    )

        return None

    def _complete_decommission_confirmation_flow(
            self,
            timeout: float = 35.0,
            decom_btn_rect: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Handle all post-'Decommission' confirmation steps:
        1. Native 'Decommission device?' alert (if shown),
        2. iOS ASWebAuthenticationSession Sign-In alert ('Wants to Use "preview.home.google.com" to Sign In' -> 'Continue'),
        3. Google Home WebView removal confirmation page ('要移除攝影機並刪除記錄嗎？' -> '刪除' / 'Delete' / 'Remove').
        """
        start_ts = time.time()
        deadline = start_ts + timeout
        retried_decom_tap = False
        native_confirmed = False
        post_native_grace_until = 0.0
        web_signin_accepted = False
        web_signin_accepted_at = 0.0
        webview_seen = False
        webview_scroll_check_at = 0.0
        webview_delete_clicked = False
        webview_delete_clicked_at = 0.0

        while time.time() < deadline:
            # Step A: Check native Decommission alert or ASWebAuthenticationSession Sign-In alert
            alert_action = self._try_accept_signin_or_native_decommission_alert()
            if alert_action == "native_decommission":
                native_confirmed = True
                post_native_grace_until = time.time() + 5.5
                deadline = max(deadline, time.time() + 25.0)
                continue
            if alert_action == "web_signin_continue":
                web_signin_accepted = True
                web_signin_accepted_at = time.time()
                deadline = max(deadline, time.time() + 25.0)
                time.sleep(1.0)
                continue

            # Step B: Check 'preview.home.google.com' removal confirmation WebView
            if self._is_decommission_webview_open():
                now = time.time()
                if not webview_seen:
                    webview_seen = True
                    webview_scroll_check_at = now
                    deadline = max(deadline, now + 25.0)
                    self._logger.info(
                        "[Decommission] Detected 'home.google.com' removal confirmation WebView..."
                    )

                del_btn = self._find_webview_delete_button()
                if del_btn is not None:
                    if not webview_delete_clicked or (now - webview_delete_clicked_at) >= 6.0:
                        btn_txt = self._read_text(del_btn) or "刪除/Delete"
                        self._logger.info(
                            f"[Decommission] Clicking WebView removal confirmation button '{btn_txt}'..."
                        )
                        self._click_webview_button_with_tap_fallback(
                            del_btn, desc=f"WebView '{btn_txt}'"
                        )
                        webview_delete_clicked = True
                        webview_delete_clicked_at = time.time()
                        deadline = max(deadline, time.time() + 15.0)
                        time.sleep(1.2)
                        continue
                else:
                    if webview_delete_clicked and (now - webview_delete_clicked_at) >= 3.0:
                        done_btn = self._find_webview_button_by_labels(
                            self.WEBVIEW_POST_DELETE_CLOSE_LABELS
                        )
                        if done_btn is not None:
                            done_txt = self._read_text(done_btn) or "Done"
                            self._logger.info(
                                f"[Decommission] Clicking post-removal WebView button '{done_txt}'..."
                            )
                            self._click_webview_button_with_tap_fallback(
                                done_btn, desc=f"WebView '{done_txt}'"
                            )
                            time.sleep(1.0)
                            continue
                    elif not webview_delete_clicked and (now - webview_scroll_check_at) >= 4.0:
                        self._scroll_settings("down")
                        webview_scroll_check_at = time.time()

                time.sleep(0.6)
                continue

            # Step C: WebView is NOT currently on screen — check completion conditions
            if webview_delete_clicked:
                time.sleep(0.6)
                if not self._is_decommission_webview_open() and not self._is_web_signin_alert_open():
                    self._logger.info(
                        "[Decommission] 'home.google.com' removal confirmation WebView completed and closed."
                    )
                    return True
                continue

            if web_signin_accepted and not webview_seen:
                # Waiting for SafariViewService WebView to appear after tapping 'Continue' on Sign-In alert
                if (time.time() - web_signin_accepted_at) >= 12.0:
                    self._logger.info(
                        "[Decommission] Sign-In prompt accepted and no WebView remained open; continuing."
                    )
                    return True
                time.sleep(0.6)
                continue

            if native_confirmed and not web_signin_accepted and not webview_seen:
                # Hold briefly after native Decommission alert in case ASWebAuthenticationSession pops up right after
                if time.time() >= post_native_grace_until:
                    return True
                time.sleep(0.5)
                continue

            # If GHP popped back to Camera Live / Player BEFORE any confirmation alert/WebView opened,
            # 'Decommission' was either swallowed or interrupted by navigation — bail out fast so caller recovers!
            if (
                    not native_confirmed
                    and not web_signin_accepted
                    and not webview_seen
                    and (time.time() - start_ts) >= 1.2
                    and self._is_on_camera_player_screen()
            ):
                self._logger.warning(
                    "[Decommission] Screen returned to Camera Live / Player before any Decommission "
                    "confirmation appeared; re-entering Settings / Device Details to retry..."
                )
                return False

            # Retry tapping 'Decommission' once if first click only stopped scroll momentum or hit a non-button text
            if (
                    not retried_decom_tap
                    and (time.time() - start_ts) >= 2.0
            ):
                live_btn = self._find_settings_decommission_button()
                if live_btn is not None:
                    live_rect = decom_btn_rect
                    try:
                        r_now = live_btn.rect
                        if isinstance(r_now, dict) and float(r_now.get("width", 0)) > 0:
                            live_rect = r_now
                    except WebDriverException:
                        pass
                    if live_rect:
                        retried_decom_tap = True
                        cx = int(live_rect["x"] + live_rect["width"] / 2)
                        cy = int(live_rect["y"] + live_rect["height"] / 2)
                        self._logger.info(
                            f"[Decommission] Retrying tap on 'Decommission' button at ({cx}, {cy})..."
                        )
                        try:
                            self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                        except WebDriverException:
                            pass
                        time.sleep(0.8)
                        continue

            time.sleep(0.5)

        return native_confirmed or webview_delete_clicked

    def _return_to_devices_tab_after_decommission(self, wait_seconds: float = 12.0) -> None:
        """Wait for Decommission RPC / WebView to complete and navigate back to the Devices tab if needed."""
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if self._is_web_signin_alert_open() or self._is_decommission_webview_open():
                self._complete_decommission_confirmation_flow(timeout=25.0)
                continue
            with self._fast_probe():
                try:
                    bars = self.driver.find_elements(IOS_CLASS_CHAIN_BY, "**/XCUIElementTypeTabBar")
                    if any(b.is_displayed() for b in bars):
                        return
                except WebDriverException:
                    pass
                # Wait while Decommission alert / spinner is still running
                try:
                    alerts = self.driver.find_elements(IOS_PREDICATE_BY,
                                                       self.ALERT_CONTAINER_PREDICATE)
                    if any(a.is_displayed() for a in alerts):
                        time.sleep(0.8)
                        continue
                except WebDriverException:
                    pass
                # If Decommission button is gone (left Settings) or Back/Close button is shown, navigate back
                if self._find_settings_decommission_button() is None:
                    try:
                        nav_btns = self.driver.find_elements(IOS_PREDICATE_BY,
                                                             self.BACK_OR_CLOSE_PREDICATE)
                        for b in nav_btns:
                            if b.is_displayed():
                                b.click()
                                break
                    except WebDriverException:
                        pass
            time.sleep(0.8)

    def _open_device_details_fallback_for_decommission(
            self, owner: Any = None
    ) -> Optional[WebElement]:
        """Fallback when CameraLiveView keeps popping Settings: go to Devices tab -> long-press 'Device Details...'."""
        sess = getattr(owner, "session", None) or getattr(self, "session", None)
        if sess is None and hasattr(owner, "_open_device_details_via_long_press"):
            sess = owner
        if sess is None or not hasattr(sess, "_open_device_details_via_long_press"):
            return None

        candidates: List[str] = []
        if hasattr(sess, "_get_cleanup_candidate_names"):
            try:
                candidates = list(
                    sess._get_cleanup_candidate_names(getattr(owner, "device_name", None)))
            except Exception:
                candidates = []
        if not candidates:
            raw_dev = getattr(owner, "device_name", None) or getattr(sess, "device_name", None)
            if raw_dev and str(raw_dev).strip():
                candidates = [str(raw_dev).strip()]
        if not candidates:
            return None

        self._logger.warning(
            "[GHP Settings] Falling back to Devices tab long-press 'Device Details...' "
            f"for {candidates} to execute Decommission without live player..."
        )
        from page_object.iGHP.ghp_device_page import GHPDevicePage

        try:
            GHPDevicePage.go_to_tab(sess, "Devices")
        except Exception:
            pass

        opened = False
        for cand in candidates:
            try:
                if sess._open_device_details_via_long_press(cand):
                    opened = True
                    break
            except Exception:
                continue
        if not opened:
            return None

        # Opportunistically capture missing Device ID / metadata from DeviceDetailsView
        if self.device_tech_info.get("device_id", "UNKNOWN") in ("", "UNKNOWN"):
            extra: Dict[str, str] = dict(self.device_tech_info)
            self._collect_visible_kv_pairs(extra)
            self._store_tech_info(owner or self, extra)

        for _ in range(5):
            btn = self._find_settings_decommission_button()
            if btn is not None:
                return btn
            if not self._scroll_settings_down_checked():
                break
        return self._find_settings_decommission_button()

    def _scroll_settings_to_find_remove_button(
            self, max_scrolls: int = 12, owner: Any = None
    ) -> Optional[WebElement]:
        """Scroll Settings downward until 'Decommission' / 'Remove' appears or bottom is confirmed."""
        reopen_attempts = 0
        max_reopens = 4
        unchanged_scrolls = 0
        for step in range(max_scrolls + 1):
            decom_btn = self._find_settings_decommission_button()
            if decom_btn is not None:
                return decom_btn
            if self._is_on_camera_player_screen():
                if reopen_attempts < max_reopens and self._reopen_settings_if_on_player_page():
                    reopen_attempts += 1
                    unchanged_scrolls = 0
                    decom_btn = self._find_settings_decommission_button()
                    if decom_btn is not None:
                        return decom_btn
                else:
                    # Never scroll CameraPlayerView's event timeline when stuck on Player!
                    break
            if step >= max_scrolls:
                break
            moved = self._scroll_settings_down_checked()
            if self._is_on_camera_player_screen():
                if reopen_attempts < max_reopens and self._reopen_settings_if_on_player_page():
                    reopen_attempts += 1
                    unchanged_scrolls = 0
                    continue
                break
            if moved:
                unchanged_scrolls = 0
            else:
                unchanged_scrolls += 1
                if unchanged_scrolls >= 2:
                    # Reached bottom of scroll view: wait briefly and perform one final check before stopping
                    time.sleep(0.5)
                    decom_btn = self._find_settings_decommission_button()
                    if decom_btn is not None:
                        return decom_btn
                    if reopen_attempts < max_reopens and self._reopen_settings_if_on_player_page():
                        reopen_attempts += 1
                        unchanged_scrolls = 0
                        continue
                    break

        decom_btn = self._find_settings_decommission_button()
        if decom_btn is not None:
            return decom_btn
        return self._open_device_details_fallback_for_decommission(owner=owner)

    def click_remove_device_btn(self, max_scrolls: int = 12) -> bool:
        """Scroll all the way down to 'Decommission' / 'Remove' in GHP Settings, click it, and confirm removal."""
        page = GHPDeviceSettingPage._resolve_page(self)
        _win_w, win_h = page._get_window_dimensions()

        confirmed = False
        for decommission_attempt in range(1, 3):
            if decommission_attempt == 1:
                page._logger.info(
                    "Scrolling to bottom of GHP Settings for 'Decommission' / 'Remove' button..."
                )
                decom_btn = page._scroll_settings_to_find_remove_button(
                    max_scrolls=max_scrolls, owner=self
                )
            else:
                page._logger.warning(
                    "[Decommission] Retry attempt 2/2: re-locating 'Decommission' button after "
                    "unconfirmed tap / unexpected screen pop..."
                )
                if page._is_on_camera_player_screen():
                    if not page._reopen_settings_if_on_player_page():
                        decom_btn = page._open_device_details_fallback_for_decommission(owner=self)
                    else:
                        decom_btn = page._scroll_settings_to_find_remove_button(
                            max_scrolls=max_scrolls, owner=self
                        )
                else:
                    decom_btn = page._scroll_settings_to_find_remove_button(
                        max_scrolls=max_scrolls, owner=self
                    )
                    if decom_btn is None:
                        decom_btn = page._open_device_details_fallback_for_decommission(owner=self)

            if decom_btn is None:
                if decommission_attempt == 1:
                    decom_btn = page._open_device_details_fallback_for_decommission(owner=self)
                if decom_btn is None:
                    page._log_decommission_probe_diagnostics()
                    msg = "Failed to locate 'Decommission' button on GHP Settings page."
                    page._logger.error(msg)
                    BasePage.capture_failure_screenshot(page.driver, reason=msg, force=False,
                                                        lock=True)
                    raise AssertionError(msg)

            rect = None
            try:
                rect = decom_btn.rect
            except WebDriverException:
                rect = None

            # If 'Decommission' sits inside the bottom iOS Home-Indicator bar, nudge slightly up
            if isinstance(rect, dict) and float(rect.get("height", 0)) > 0:
                cy_check = float(rect.get("y", 0)) + float(rect.get("height", 0)) / 2.0
                if cy_check > float(win_h - 30):
                    page._scroll_settings("down", x_ratio=0.5, span=(0.60, 0.42))
                    refreshed_btn = page._find_settings_decommission_button()
                    if refreshed_btn is not None:
                        decom_btn = refreshed_btn
                        try:
                            rect = decom_btn.rect
                        except WebDriverException:
                            pass

            try:
                was_displayed = bool(decom_btn.is_displayed())
            except WebDriverException:
                was_displayed = False
            try:
                elem_type = str(decom_btn.get_attribute("type") or "")
            except WebDriverException:
                elem_type = ""

            page._logger.info(
                f"Clicking 'Decommission' button (type={elem_type or 'unknown'}, displayed={was_displayed}, "
                f"attempt={decommission_attempt}/2)..."
            )
            clicked = False
            if decommission_attempt == 1:
                try:
                    decom_btn.click()
                    clicked = True
                except WebDriverException as err:
                    page._logger.debug(
                        f"Direct click on 'Decommission' failed ({err}); tapping center...")

            if rect and float(rect.get("width", 0)) > 0 and float(rect.get("height", 0)) > 0:
                if clicked:
                    time.sleep(0.6)
                if (
                        not clicked
                        or decommission_attempt >= 2
                        or not was_displayed
                        or elem_type != "XCUIElementTypeButton"
                        or (
                        not page._has_any_decommission_prompt_open()
                        and page._find_settings_decommission_button() is not None
                )
                ):
                    cx = int(rect["x"] + rect["width"] / 2)
                    cy = int(rect["y"] + rect["height"] / 2)
                    try:
                        page.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                    except WebDriverException:
                        pass

            time.sleep(0.8)
            confirmed = page._complete_decommission_confirmation_flow(
                timeout=35.0, decom_btn_rect=rect
            )
            if confirmed:
                break

        if not confirmed:
            msg = (
                "Clicked 'Decommission', but removal confirmation dialog / WebView "
                "did not appear or could not be confirmed."
            )
            page._logger.error(msg)
            BasePage.capture_failure_screenshot(page.driver, reason=msg, force=False, lock=True)
            raise AssertionError(msg)

        page._logger.info("Confirmed 'Decommission'. Waiting for device removal to complete...")
        time.sleep(1.5)
        page._return_to_devices_tab_after_decommission(wait_seconds=12.0)
        page._logger.info("Device decommissioned successfully from GHP.")
        return True
