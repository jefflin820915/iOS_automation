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
        'type == "XCUIElementTypeButton" AND '
        '(name == "Decommission" OR label == "Decommission" '
        'OR name CONTAINS[c] "Decommission" OR label CONTAINS[c] "Decommission")'
    )

    ALERT_CONTAINER_PREDICATE: str = (
        'type IN {"XCUIElementTypeAlert", "XCUIElementTypeSheet"} AND ('
        'name CONTAINS[c] "Decommission" OR label CONTAINS[c] "Decommission" '
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

    def _scroll_settings(self, direction: str = "down") -> None:
        try:
            win = self.driver.get_window_size()
            w = int(win.get("width", 390))
            h = int(win.get("height", 844))
        except Exception:
            w, h = 390, 844
        cx = w // 2
        if direction == "down":
            from_y, to_y = int(h * 0.72), int(h * 0.28)
        else:
            from_y, to_y = int(h * 0.28), int(h * 0.72)
        try:
            self.driver.execute_script(
                "mobile: dragFromToForDuration",
                {"duration": 0.25, "fromX": cx, "fromY": from_y, "toX": cx, "toY": to_y},
            )
        except WebDriverException:
            try:
                self.driver.execute_script("mobile: scroll", {"direction": direction})
            except WebDriverException:
                pass
        time.sleep(0.8)

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
        """Scan visible XCUIElementTypeCell rows and StaticText pairs for technical metadata."""
        with self._fast_probe():
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
                    v = self._read_text(t)
                    if v and v not in vals:
                        vals.append(v)
                if len(vals) >= 2:
                    key = self._match_canonical_key(vals[0])
                    val = vals[1].strip()
                    if key and val and val != "?":
                        if key not in collected or collected[key] in ("", "UNKNOWN", "?"):
                            collected[key] = val

            # Also handle non-Cell VStack/ScrollView layouts (e.g. DeviceDetailsView LineItemView)
            try:
                all_texts = self.driver.find_elements(AppiumBy.CLASS_NAME,
                                                      "XCUIElementTypeStaticText")
            except WebDriverException:
                all_texts = []
            ordered_vals = [self._read_text(t) for t in all_texts]
            ordered_vals = [v for v in ordered_vals if v]
            for idx in range(len(ordered_vals) - 1):
                key = self._match_canonical_key(ordered_vals[idx])
                nxt = ordered_vals[idx + 1].strip()
                if key and nxt and nxt != "?" and self._match_canonical_key(nxt) is None:
                    if key not in collected or collected[key] in ("", "UNKNOWN", "?"):
                        collected[key] = nxt

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
            self, max_scrolls: int = 4, verify_ota_status: bool = True
    ) -> Dict[str, str]:
        """Extract Software Version, Serial Number, IP Address, Device ID, and OTA Status from Camera Settings."""
        page = GHPDeviceSettingPage._resolve_page(self)
        page._logger.info("Extracting camera technical information from GHP Settings...")
        collected: Dict[str, str] = {}

        # Wait briefly for Settings rows to initialize (CameraSettingsView shows ProgressView while loading)
        deadline = time.time() + 8.0
        while time.time() < deadline:
            page._collect_visible_kv_pairs(collected)
            if collected:
                break
            time.sleep(0.5)

        for step in range(max_scrolls):
            page._collect_visible_kv_pairs(collected)
            # Stop scrolling early if Decommission button is already visible and core fields are captured
            if (
                    collected.get("software_version")
                    and collected.get("serial_number")
                    and page._find_settings_decommission_button() is not None
            ):
                break
            page._scroll_settings("down")
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

    def _find_settings_decommission_button(self) -> Optional[WebElement]:
        """Locate the primary 'Decommission' button in Camera Settings (excluding alert buttons)."""
        with self._fast_probe():
            try:
                btns = self.driver.find_elements(IOS_PREDICATE_BY, self.DECOMMISSION_BTN_PREDICATE)
            except WebDriverException:
                btns = []
            for btn in btns:
                try:
                    if not btn.is_displayed():
                        continue
                    txt = self._read_text(btn).lower()
                    if "history" in txt or "cancel" in txt:
                        continue
                    return btn
                except WebDriverException:
                    continue
        return None

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
            # 1. Native 'Decommission' confirmation alert/sheet
            alert_btns: List[WebElement] = []
            for chain in (
                    '**/XCUIElementTypeAlert/**/XCUIElementTypeButton[`name == "Decommission" OR label == "Decommission"`]',
                    '**/XCUIElementTypeSheet/**/XCUIElementTypeButton[`name == "Decommission" OR label == "Decommission"`]',
            ):
                try:
                    alert_btns.extend(self.driver.find_elements(IOS_CLASS_CHAIN_BY, chain))
                except WebDriverException:
                    pass

            if not alert_btns:
                try:
                    all_btns = self.driver.find_elements(IOS_PREDICATE_BY,
                                                         self.DECOMMISSION_BTN_PREDICATE)
                    visible_btns = [b for b in all_btns if b.is_displayed()]
                    if len(visible_btns) >= 2:
                        visible_btns.sort(key=lambda b: b.rect.get("y", 9999))
                        alert_btns = [visible_btns[0]]
                except WebDriverException:
                    pass

            for confirm_btn in alert_btns:
                rect = None
                try:
                    rect = confirm_btn.rect
                except WebDriverException:
                    rect = None
                self._logger.info("Confirming 'Decommission' in alert/confirmation dialog...")
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
                            "mobile: alert", {"action": "accept", "buttonLabel": "Decommission"}
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

            # Retry tapping 'Decommission' once if first click only stopped scroll momentum
            if (
                    not retried_decom_tap
                    and decom_btn_rect
                    and (time.time() - start_ts) >= 3.5
                    and self._find_settings_decommission_button() is not None
            ):
                retried_decom_tap = True
                cx = int(decom_btn_rect["x"] + decom_btn_rect["width"] / 2)
                cy = int(decom_btn_rect["y"] + decom_btn_rect["height"] / 2)
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

    def click_remove_device_btn(self, max_scrolls: int = 6) -> bool:
        """Scroll to 'Decommission' in GHP Camera Settings, click it, and complete native + WebView removal confirmations."""
        page = GHPDeviceSettingPage._resolve_page(self)
        page._logger.info("Scrolling to 'Decommission' button in GHP Settings...")
        decom_btn: Optional[WebElement] = None
        for step in range(max_scrolls + 1):
            decom_btn = page._find_settings_decommission_button()
            if decom_btn is not None:
                break
            if step < max_scrolls:
                page._scroll_settings("down")

        if decom_btn is None:
            msg = "Failed to locate 'Decommission' button on GHP Settings page."
            page._logger.error(msg)
            BasePage.capture_failure_screenshot(page.driver, reason=msg, force=False, lock=True)
            raise AssertionError(msg)

        rect = None
        try:
            rect = decom_btn.rect
        except WebDriverException:
            rect = None

        page._logger.info("Clicking 'Decommission' button...")
        clicked = False
        try:
            decom_btn.click()
            clicked = True
        except WebDriverException as err:
            page._logger.debug(f"Direct click on 'Decommission' failed ({err}); tapping center...")
        if rect and not clicked:
            cx = int(rect["x"] + rect["width"] / 2)
            cy = int(rect["y"] + rect["height"] / 2)
            page.driver.execute_script("mobile: tap", {"x": cx, "y": cy})

        time.sleep(0.8)
        confirmed = page._complete_decommission_confirmation_flow(
            timeout=35.0, decom_btn_rect=rect
        )

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
