"""Session Page Object managing iGHP Sample App lifecycle and aggregating all iGHP sub-page objects."""

from contextlib import contextmanager
import re
import threading
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple
import xml.etree.ElementTree as ET
from appium import webdriver
from appium.options.common import AppiumOptions
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from common import constants
from common.base_page import BasePage
from page_object.iGHP.ghp_camera_live_page import GHPCameraLivePage
from page_object.iGHP.ghp_commission_flow import GHPCommissioningPageObject
from page_object.iGHP.ghp_device_page import GHPDevicePage, get_ghp_bundle_id
from page_object.iGHP.ghp_device_setting_page import GHPDeviceSettingPage
from utils import logging_utils
from utils.camera_reset_utils import DeviceResetUtils

IOS_PREDICATE_BY = getattr(AppiumBy, "IOS_PREDICATE", "-ios predicate string")
IOS_CLASS_CHAIN_BY = getattr(AppiumBy, "IOS_CLASS_CHAIN", "-ios class chain")


class GHPSession:
    """Central entry point managing GoogleHomeAPISampleIOS (`iGHP`) lifecycle and sub-page objects."""

    EMERGENCY_REMOVE_ATTEMPTS: int = 2
    WDA_ERROR_SIGNATURES: Tuple[str, ...] = (
        "ECONNREFUSED",
        "Could not proxy command to the remote server",
        "socket hang up",
        "A session is either terminated or not started",
        "invalid session id",
        "NoSuchDriverError",
    )

    SCROLL_VIEW_LOCATORS: Tuple[Tuple[str, str], ...] = (
        (IOS_PREDICATE_BY, 'type == "XCUIElementTypeScrollView" AND visible == 1'),
        (IOS_PREDICATE_BY, 'type == "XCUIElementTypeCollectionView" AND visible == 1'),
    )
    TOP_RIGHT_MORE_PREDICATE: str = (
        '(type IN {"XCUIElementTypeOther", "XCUIElementTypeButton"}) AND ('
        'name IN {"More", "ellipsis", "ellipsis.circle"} '
        'OR label IN {"More", "ellipsis", "More Options"})'
    )
    ABOUT_MENU_BTN_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND (name == "About" OR label == "About")'
    )
    ABOUT_SHEET_MARKER_PREDICATE: str = (
        'type IN {"XCUIElementTypeStaticText", "XCUIElementTypeCell", "XCUIElementTypeButton"} AND ('
        'name CONTAINS "SDK Version" OR label CONTAINS "SDK Version" '
        'OR name CONTAINS "App Version" OR label CONTAINS "App Version" '
        'OR name CONTAINS "Revoke app permission" OR label CONTAINS "Revoke app permission")'
    )

    def __init__(self, driver: WebDriver) -> None:
        self.driver = driver
        self.timeout = getattr(constants, "DEFAULT_TIMEOUT_SECONDS", 15.0)
        self._logger = logging_utils.get_logger(__name__, "ghp_session")
        self._ghp_stopped_in_cleanup = False
        self._device_removed_in_emergency = False
        self.device_name: Optional[str] = None
        self.pairing_code: Optional[str] = None
        self.room_name: str = "Attic"
        self.device_tech_info: Dict[str, str] = {}
        self.sample_app_version: str = "UNKNOWN"
        self.sdk_version: str = "UNKNOWN"
        self._versions_collected: bool = False

        bundle_id = get_ghp_bundle_id()
        constants.ACTIVE_APP_BUNDLE_ID = bundle_id
        if driver is not None:
            try:
                setattr(driver, "_active_app_bundle_id", bundle_id)
                cached_ver = getattr(driver, "_ghp_version_info", None)
                if isinstance(cached_ver, dict):
                    s_ver = str(cached_ver.get("sample_app_version") or "").strip()
                    k_ver = str(cached_ver.get("sdk_version") or "").strip()
                    if s_ver and s_ver.upper() not in ("UNKNOWN", "UNKNOWN / NOT INSTALLED"):
                        self.sample_app_version = s_ver
                    if k_ver and k_ver.upper() not in ("UNKNOWN", "UNKNOWN / NOT INSTALLED"):
                        self.sdk_version = k_ver
                        self._versions_collected = True
            except Exception:
                pass

        page_classes = [
            GHPDevicePage,
            GHPCommissioningPageObject,
            GHPCameraLivePage,
            GHPDeviceSettingPage,
        ]
        for cls in page_classes:
            attr_name = cls.__name__.lower()
            page_instance = cls(driver)
            page_instance.session = self
            setattr(self, attr_name, page_instance)

    def __getattr__(self, name: str) -> Any:
        """Delegate missing method/attribute lookups across all registered iGHP page objects."""
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        for val in self.__dict__.values():
            if isinstance(val, BasePage) and hasattr(val, name):
                return getattr(val, name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    @classmethod
    def _resolve_session(cls, ctx: Any) -> "GHPSession":
        if isinstance(ctx, cls):
            return ctx
        session = getattr(ctx, "session", None)
        if isinstance(session, cls):
            return session
        return ctx

    @contextmanager
    def _no_implicit_wait(self) -> Iterator[None]:
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

    @classmethod
    def _is_wda_connection_error(cls, exc: Exception) -> bool:
        msg = str(exc)
        return any(sig in msg for sig in cls.WDA_ERROR_SIGNATURES)

    def _reconnect_wda_driver(self) -> bool:
        """Rebuild the Appium WebDriver session in-place when WDA disconnects."""
        self._logger.warning(
            "[WDA Reconnect] Detected dead WDA connection. Rebuilding Appium WebDriver session..."
        )
        device_tech_info = getattr(self.driver, "device_tech_info", None)
        ghp_version_info = getattr(self.driver, "_ghp_version_info", None)
        try:
            self.driver.quit()
        except Exception:
            pass
        try:
            options = AppiumOptions()
            options.load_capabilities(constants.IOS_CAPABILITIES)
            new_driver = webdriver.Remote(constants.APPIUM_SERVER_URL, options=options)
            new_driver.implicitly_wait(getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0))
            setattr(new_driver, "_active_app_bundle_id", get_ghp_bundle_id())
            if device_tech_info is not None:
                new_driver.device_tech_info = device_tech_info
            if ghp_version_info is not None:
                setattr(new_driver, "_ghp_version_info", ghp_version_info)
            self.driver.__dict__.update(new_driver.__dict__)
            self._logger.info(
                f"[WDA Reconnect] Re-established Appium/WDA session (session_id={self.driver.session_id})."
            )
            return True
        except Exception as err:
            self._logger.error(f"[WDA Reconnect] Failed to rebuild Appium WebDriver session: {err}")
            return False

    def ensure_device_unlocked(self) -> bool:
        """Ensure iOS screen is unlocked before launching or interacting with GHP Sample App."""
        sess = GHPSession._resolve_session(self)
        try:
            if hasattr(sess.driver, "is_locked") and sess.driver.is_locked():
                return BasePage._unlock_device_if_locked(sess)
            return True
        except WebDriverException as err:
            if sess._is_wda_connection_error(err) and sess._reconnect_wda_driver():
                return BasePage._unlock_device_if_locked(sess)
            sess._logger.warning(f"Failed checking lock state: {err}")
            return False
        except Exception as err:
            sess._logger.warning(f"Unexpected error checking lock state: {err}")
            return False

    def _is_ghp_running(self) -> bool:
        bundle_id = get_ghp_bundle_id()
        fg_state = getattr(constants, "APP_STATE_FOREGROUND", 4)
        try:
            return self.driver.query_app_state(bundle_id) == fg_state
        except WebDriverException as err:
            self._logger.error(f"Failed to query iGHP app state: {err}")
            return False

    def start_ghp(self, timeout: float = 15.0) -> bool:
        """Start GoogleHomeAPISampleIOS (`iGHP`) and verify it reaches active foreground."""
        sess = GHPSession._resolve_session(self)
        bundle_id = get_ghp_bundle_id()
        sess._ghp_stopped_in_cleanup = False
        sess.ensure_device_unlocked()
        if sess._is_ghp_running():
            sess._logger.info("iGHP Sample App is already running in foreground.")
            return True

        sess._logger.info(f"Starting iGHP Sample App ('{bundle_id}') on iOS...")
        try:
            sess.driver.activate_app(bundle_id)
        except WebDriverException as err:
            if sess._is_wda_connection_error(err) and sess._reconnect_wda_driver():
                try:
                    sess.driver.activate_app(bundle_id)
                except WebDriverException as retry_err:
                    sess._logger.error(f"Failed to activate iGHP after WDA reconnect: {retry_err}")
                    return False
            else:
                sess._logger.error(f"Failed to activate iGHP Sample App: {err}")
                return False

        start_ts = time.time()
        while time.time() - start_ts < timeout:
            if sess._is_ghp_running():
                sess._logger.info("iGHP Sample App launched successfully in foreground.")
                return True
            try:
                sess.driver.activate_app(bundle_id)
            except WebDriverException:
                pass
            time.sleep(0.8)
        sess._logger.error(f"Timed out after {timeout}s waiting for iGHP Sample App.")
        return False

    def stop_ghp(self) -> bool:
        """Terminate GoogleHomeAPISampleIOS (`iGHP`), with WDA disconnect self-healing."""
        sess = GHPSession._resolve_session(self)
        bundle_id = get_ghp_bundle_id()
        not_running_state = getattr(constants, "APP_STATE_NOT_RUNNING", 1)
        try:
            app_state = sess.driver.query_app_state(bundle_id)
            if app_state != not_running_state:
                sess.driver.terminate_app(bundle_id)
                sess._logger.info("iGHP Sample App stopped successfully.")
            else:
                sess._logger.info("iGHP Sample App is not running.")
            sess._ghp_stopped_in_cleanup = False
            return True
        except WebDriverException as err:
            if getattr(sess, "_ghp_stopped_in_cleanup", False):
                sess._ghp_stopped_in_cleanup = False
                sess._logger.warning(
                    f"[WDA] WDA connection dropped during post-test ADB reset ({err}), "
                    "but iGHP was already stopped prior to Step 2/2. Treating stop_ghp() as SUCCESS."
                )
                return True
            if sess._is_wda_connection_error(err) and sess._reconnect_wda_driver():
                try:
                    app_state = sess.driver.query_app_state(bundle_id)
                    if app_state != not_running_state:
                        sess.driver.terminate_app(bundle_id)
                    return True
                except WebDriverException as retry_err:
                    sess._logger.error(f"Failed to stop iGHP after WDA reconnect: {retry_err}")
                    return False
            sess._logger.error(f"Failed to stop iGHP Sample App: {err}")
            return False

    # Compatibility aliases for shared utilities expecting start_gha / stop_gha
    start_gha = start_ghp
    stop_gha = stop_ghp

    def _get_devices_scroll_view(self) -> Optional[Any]:
        with self._no_implicit_wait():
            for by, loc in self.SCROLL_VIEW_LOCATORS:
                try:
                    for elem in self.driver.find_elements(by, loc):
                        if elem.is_displayed():
                            return elem
                except Exception:
                    continue
        return None

    def _pull_down_to_refresh(self, element: Any = None) -> None:
        rect: Optional[Dict[str, int]] = None
        if element is not None:
            try:
                rect = element.rect
            except Exception:
                rect = None
        if not rect:
            try:
                win = self.driver.get_window_size()
                rect = {
                    "x": 0,
                    "y": 100,
                    "width": int(win.get("width", 390)),
                    "height": max(300, int(win.get("height", 844)) - 180),
                }
            except Exception:
                rect = {"x": 0, "y": 100, "width": 390, "height": 600}
        center_x = rect["x"] + rect["width"] // 2
        start_y = rect["y"] + int(rect["height"] * 0.18)
        end_y = rect["y"] + int(rect["height"] * 0.68)
        actions = ActionChains(self.driver)
        actions.w3c_actions = ActionBuilder(
            self.driver, mouse=PointerInput(interaction.POINTER_TOUCH, "touch")
        )
        actions.w3c_actions.pointer_action.move_to_location(center_x, start_y)
        actions.w3c_actions.pointer_action.pointer_down()
        actions.w3c_actions.pointer_action.pause(0.3)
        actions.w3c_actions.pointer_action.move_to_location(center_x, end_y)
        actions.w3c_actions.pointer_action.pause(0.5)
        actions.w3c_actions.pointer_action.pointer_up()
        actions.perform()

    def refresh_ghp_devices(self, timeout: float = 5.0) -> None:
        """Ensure GHP is on the Devices tab and pull down to refresh the structure device list."""
        sess = GHPSession._resolve_session(self)
        default_wait = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
        try:
            time.sleep(2.0)
            GHPDevicePage.go_to_tab(sess, "Devices")
            scroll_view = sess._get_devices_scroll_view()
            sess._pull_down_to_refresh(scroll_view)
            time.sleep(0.5)
            spinner_locator = (IOS_CLASS_CHAIN_BY, "**/XCUIElementTypeActivityIndicator")
            try:
                sess.driver.implicitly_wait(0)
                WebDriverWait(sess.driver, timeout).until(
                    EC.invisibility_of_element_located(spinner_locator)
                )
            except TimeoutException:
                pass
            finally:
                try:
                    sess.driver.implicitly_wait(default_wait)
                except Exception:
                    pass
            sess._logger.info("iGHP device list refreshed.")
        except Exception as err:
            sess._logger.warning(f"Failed to refresh iGHP devices: {err}")

        if not getattr(sess, "_versions_collected", False):
            try:
                sess.collect_app_and_sdk_versions()
            except Exception as ver_err:
                sess._logger.warning(f"Failed to collect iGHP App/SDK versions: {ver_err}")

    refresh_gha_devices = refresh_ghp_devices

    # -------------------------------------------------------------------------
    # GHP Sample App Version & Home SDK Version Extraction (More -> About)
    # -------------------------------------------------------------------------
    @staticmethod
    def _clean_version_candidate(raw: str, label_prefix: str) -> Optional[str]:
        text = (raw or "").strip()
        if not text:
            return None
        low = text.lower()
        pref = label_prefix.lower()
        if low == pref:
            return None
        if low.startswith(pref):
            remainder = re.sub(r"^[\s,:\-–—]+", "", text[len(label_prefix):]).strip()
            return remainder or None
        return text

    def _read_app_version_via_list_apps(self) -> Optional[str]:
        """Fast non-UI fallback reading CFBundleShortVersionString via `mobile: listApps`."""
        bundle_id = get_ghp_bundle_id()
        try:
            apps = self.driver.execute_script("mobile: listApps", {"applicationType": "User"})
            info: Any = None
            if isinstance(apps, list):
                info = next(
                    (a for a in apps if
                     isinstance(a, dict) and a.get("CFBundleIdentifier") == bundle_id),
                    None,
                )
            elif isinstance(apps, dict):
                info = apps.get(bundle_id)
            if isinstance(info, str) and info.strip():
                return info.strip()
            if isinstance(info, dict):
                ver = (
                        info.get("CFBundleShortVersionString")
                        or info.get("CFBundleVersion")
                        or info.get("version")
                )
                if ver and str(ver).strip():
                    return str(ver).strip()
        except Exception:
            pass
        return None

    def _extract_about_versions_from_screen(self) -> Tuple[Optional[str], Optional[str]]:
        """Extract (`App Version`, `SDK Version`) from the open SwiftUI `AboutView` modal sheet."""
        app_ver: Optional[str] = None
        sdk_ver: Optional[str] = None

        # Layer 1: Inspect XCUIElementTypeCell containers (child StaticTexts + merged cell label/name)
        try:
            cells = self.driver.find_elements(IOS_PREDICATE_BY, 'type == "XCUIElementTypeCell"')
        except Exception:
            cells = []

        for cell in cells:
            try:
                cell_text = (
                        cell.get_attribute("label")
                        or cell.get_attribute("name")
                        or cell.get_attribute("value")
                        or ""
                ).strip()
                child_texts: List[str] = []
                for st in cell.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText"):
                    val = (
                            st.get_attribute("value")
                            or st.get_attribute("label")
                            or st.get_attribute("name")
                            or getattr(st, "text", "")
                            or ""
                    ).strip()
                    if val:
                        child_texts.append(val)

                joined_low = " | ".join([cell_text] + child_texts).lower()
                if app_ver is None and "app version" in joined_low:
                    for item in child_texts + ([cell_text] if cell_text else []):
                        cand = self._clean_version_candidate(item, "App Version")
                        if cand and "sdk version" not in cand.lower() and "bundle id" not in cand.lower():
                            app_ver = cand
                            break
                if sdk_ver is None and "sdk version" in joined_low:
                    for item in child_texts + ([cell_text] if cell_text else []):
                        cand = self._clean_version_candidate(item, "SDK Version")
                        if cand and "app version" not in cand.lower() and "bundle id" not in cand.lower():
                            sdk_ver = cand
                            break
            except Exception:
                continue

        if app_ver and sdk_ver:
            return app_ver, sdk_ver

        # Layer 2: Horizontal HStack row geometry pairing across XCUIElementTypeStaticText elements
        try:
            static_els = self.driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText")
        except Exception:
            static_els = []

        items_with_rect: List[Tuple[str, Dict[str, int]]] = []
        for el in static_els:
            try:
                txt = (
                        el.get_attribute("value")
                        or el.get_attribute("label")
                        or el.get_attribute("name")
                        or getattr(el, "text", "")
                        or ""
                ).strip()
                if not txt:
                    continue
                if app_ver is None and txt.lower().startswith("app version") and len(txt) > len(
                        "App Version"):
                    cand = self._clean_version_candidate(txt, "App Version")
                    if cand:
                        app_ver = cand
                if sdk_ver is None and txt.lower().startswith("sdk version") and len(txt) > len(
                        "SDK Version"):
                    cand = self._clean_version_candidate(txt, "SDK Version")
                    if cand:
                        sdk_ver = cand
                rect = getattr(el, "rect", None) or {}
                if rect:
                    items_with_rect.append((txt, rect))
            except Exception:
                continue

        def _match_same_row(target_label: str) -> Optional[str]:
            label_rect: Optional[Dict[str, int]] = None
            for txt, r in items_with_rect:
                if txt.lower() == target_label.lower():
                    label_rect = r
                    break
            if not label_rect:
                return None
            cy_ref = label_rect.get("y", 0) + label_rect.get("height", 0) / 2.0
            x_ref = label_rect.get("x", 0)
            best: Optional[Tuple[int, str]] = None
            for txt, r in items_with_rect:
                if txt.lower() == target_label.lower():
                    continue
                cy = r.get("y", 0) + r.get("height", 0) / 2.0
                if abs(cy - cy_ref) <= 22 and r.get("x", 0) > x_ref:
                    if best is None or r.get("x", 0) > best[0]:
                        best = (int(r.get("x", 0)), txt)
            return best[1] if best else None

        if app_ver is None:
            app_ver = _match_same_row("App Version")
        if sdk_ver is None:
            sdk_ver = _match_same_row("SDK Version")

        if app_ver and sdk_ver:
            return app_ver, sdk_ver

        # Layer 3: Fast XML page_source fallback
        try:
            xml_src = getattr(self.driver, "page_source", "") or ""
            if xml_src and ("SDK Version" in xml_src or "App Version" in xml_src):
                root = ET.fromstring(xml_src)
                flat_texts: List[str] = []
                for node in root.iter():
                    raw_txt = (
                            node.attrib.get("label")
                            or node.attrib.get("name")
                            or node.attrib.get("value")
                            or ""
                    ).strip()
                    if not raw_txt:
                        continue
                    if app_ver is None and raw_txt.lower().startswith("app version") and len(
                            raw_txt) > 11:
                        cand = self._clean_version_candidate(raw_txt, "App Version")
                        if cand:
                            app_ver = cand
                    if sdk_ver is None and raw_txt.lower().startswith("sdk version") and len(
                            raw_txt) > 11:
                        cand = self._clean_version_candidate(raw_txt, "SDK Version")
                        if cand:
                            sdk_ver = cand
                    if node.tag.endswith("StaticText"):
                        flat_texts.append(raw_txt)
                for idx, val in enumerate(flat_texts[:-1]):
                    if app_ver is None and val.lower() == "app version":
                        nxt = flat_texts[idx + 1]
                        if nxt.lower() not in ("sdk version", "bundle id"):
                            app_ver = nxt
                    if sdk_ver is None and val.lower() == "sdk version":
                        nxt = flat_texts[idx + 1]
                        if nxt.lower() not in ("app version", "bundle id"):
                            sdk_ver = nxt
        except Exception:
            pass

        return app_ver, sdk_ver

    def _is_about_sheet_open(self) -> bool:
        try:
            for el in self.driver.find_elements(IOS_PREDICATE_BY,
                                                self.ABOUT_SHEET_MARKER_PREDICATE):
                if el.is_displayed():
                    return True
        except Exception:
            pass
        return False

    def _dismiss_about_sheet(self) -> None:
        """Pull down the SwiftUI `AboutView` modal sheet cleanly until it disappears."""
        try:
            win = self.driver.get_window_size() or {}
            w = int(win.get("width", 390))
            h = int(win.get("height", 844))
        except Exception:
            w, h = 390, 844

        for attempt in range(1, 4):
            if not self._is_about_sheet_open():
                return
            try:
                self.driver.execute_script(
                    "mobile: dragFromToForDuration",
                    {
                        "duration": 0.22,
                        "fromX": w // 2,
                        "fromY": int(h * 0.16),
                        "toX": w // 2,
                        "toY": int(h * 0.88),
                    },
                )
            except Exception:
                try:
                    self.driver.execute_script("mobile: swipe", {"direction": "down"})
                except Exception:
                    pass
            time.sleep(0.5)
            if not self._is_about_sheet_open():
                return
            if attempt >= 2:
                try:
                    self.driver.execute_script("mobile: swipe", {"direction": "down"})
                    time.sleep(0.4)
                except Exception:
                    pass

    def collect_app_and_sdk_versions(self, force: bool = False) -> Dict[str, str]:
        """Open `More (•••) -> About` once per session to capture `Sample App Version` and `SDK Version`."""
        sess = GHPSession._resolve_session(self)
        if getattr(sess, "_versions_collected", False) and not force:
            return {
                "sample_app_version": sess.sample_app_version,
                "sdk_version": sess.sdk_version,
            }

        list_apps_ver = sess._read_app_version_via_list_apps()
        if list_apps_ver:
            sess.sample_app_version = list_apps_ver

        with sess._no_implicit_wait():
            try:
                win = sess.driver.get_window_size() or {}
                w = int(win.get("width", 390))
            except Exception:
                w = 390

            more_el = None
            try:
                candidates = sess.driver.find_elements(IOS_PREDICATE_BY,
                                                       sess.TOP_RIGHT_MORE_PREDICATE)
                best_x = -1
                for cand in candidates:
                    r = getattr(cand, "rect", None) or {}
                    rx, ry, rw, rh = (
                        int(r.get("x", 0)),
                        int(r.get("y", 0)),
                        int(r.get("width", 0)),
                        int(r.get("height", 0)),
                    )
                    if rw > 0 and rh > 0 and ry < 160 and rx >= best_x:
                        best_x = rx
                        more_el = cand
            except Exception:
                more_el = None

            has_navbar = False
            if more_el is None:
                try:
                    navs = sess.driver.find_elements(
                        IOS_PREDICATE_BY, 'type == "XCUIElementTypeNavigationBar"'
                    )
                    has_navbar = bool(navs)
                except Exception:
                    has_navbar = False

            if more_el is not None or has_navbar:
                try:
                    if more_el is not None:
                        r = getattr(more_el, "rect", None) or {}
                        cx = int(r.get("x", w - 56) + r.get("width", 36) / 2)
                        cy = int(r.get("y", 51) + r.get("height", 36) / 2)
                        sess._logger.info(
                            f"[GHP Version] Tapping top-right 'More' menu at ({cx}, {cy})..."
                        )
                        try:
                            sess.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                        except Exception:
                            more_el.click()
                    else:
                        tx, ty = int(w - 38), 69
                        sess._logger.info(
                            f"[GHP Version] Tapping top-right 'More' fallback at ({tx}, {ty})..."
                        )
                        sess.driver.execute_script("mobile: tap", {"x": tx, "y": ty})

                    about_btn = None
                    menu_deadline = time.time() + 3.5
                    while time.time() < menu_deadline:
                        try:
                            btns = sess.driver.find_elements(
                                IOS_PREDICATE_BY, sess.ABOUT_MENU_BTN_PREDICATE
                            )
                            for b in btns:
                                if b.is_displayed():
                                    about_btn = b
                                    break
                        except Exception:
                            pass
                        if about_btn is not None:
                            break
                        time.sleep(0.25)

                    if about_btn is not None:
                        sess._logger.info(
                            "[GHP Version] Clicking 'About' to inspect App & SDK versions...")
                        try:
                            about_btn.click()
                        except Exception:
                            br = getattr(about_btn, "rect", None) or {}
                            sess.driver.execute_script(
                                "mobile: tap",
                                {
                                    "x": int(br.get("x", w - 80) + br.get("width", 80) / 2),
                                    "y": int(br.get("y", 220) + br.get("height", 44) / 2),
                                },
                            )

                        sheet_deadline = time.time() + 4.5
                        ui_app_ver: Optional[str] = None
                        ui_sdk_ver: Optional[str] = None
                        while time.time() < sheet_deadline:
                            if sess._is_about_sheet_open():
                                ui_app_ver, ui_sdk_ver = sess._extract_about_versions_from_screen()
                                if ui_sdk_ver:
                                    break
                            time.sleep(0.3)

                        if ui_app_ver and ui_app_ver.upper() != "UNKNOWN":
                            sess.sample_app_version = ui_app_ver
                        if ui_sdk_ver and ui_sdk_ver.upper() != "UNKNOWN":
                            sess.sdk_version = ui_sdk_ver
                    else:
                        try:
                            sess.driver.execute_script("mobile: tap", {"x": w // 2, "y": 55})
                        except Exception:
                            pass
                except Exception as err:
                    sess._logger.warning(f"[GHP Version] Failed reading AboutView versions: {err}")
                finally:
                    sess._dismiss_about_sheet()

        sess._versions_collected = True
        version_payload = {
            "sample_app_version": sess.sample_app_version,
            "sdk_version": sess.sdk_version,
        }
        try:
            setattr(sess.driver, "_ghp_version_info", dict(version_payload))
        except Exception:
            pass
        sess._logger.info(
            f"[GHP Version] Captured Sample App Version='{sess.sample_app_version}' | "
            f"SDK Version='{sess.sdk_version}'"
        )
        return version_payload

    # -------------------------------------------------------------------------
    # High-Level Test Steps (Matching GHASession API)
    # -------------------------------------------------------------------------
    def click_add_devices_button(self, prefer_3p: bool = True) -> bool:
        """Tap '+' on GHP Devices tab and select 'Add Device to Google & 3P Fabric'."""
        return GHPCommissioningPageObject.click_add_device_to_fabric(self, prefer_3p=prefer_3p)

    def pair_device_with_pairing_code(self) -> bool:
        """Click 'Scan code or hold iPhone near the accessory. More options…' and enter setup code."""
        code = str(getattr(self, "pairing_code", "") or "")
        sess = GHPSession._resolve_session(self)
        sess._logger.info(
            f"[PairingCode] Device='{getattr(self, 'device_name', '')}' | pairing_code length={len(code)}"
        )
        return GHPCommissioningPageObject.enter_pairing_code_on_apple_sheet(self, pairing_code=code)

    def handle_pairing_until_device_connected(self) -> bool:
        """Run Apple Matter commissioning + GHP Camera OOBE (OTA verification + Settings + Done)."""
        sess = GHPSession._resolve_session(self)
        device_name = str(getattr(self, "device_name", "") or "")
        room_name = str(getattr(self, "room_name", "Attic") or "Attic")
        return GHPCommissioningPageObject.complete_commissioning_and_pairing_flow(
            sess, device_name=device_name, room_name=room_name
        )

    def _open_device_details_via_long_press(self, device_name: str) -> bool:
        """Fallback for offline devices: long-press tile on Devices tab -> click 'Device Details...'."""
        dev_page = GHPDevicePage._resolve_page(self)
        dev_page.go_to_tab("Devices")
        hit = dev_page._locate_device_tile_with_scroll(device_name, max_scrolls=6)
        if hit is None:
            return False
        tile, title, _status = hit
        tile = dev_page._ensure_tile_in_safe_tap_zone(tile, title)
        try:
            rect = tile.rect
            cx = int(rect["x"] + rect["width"] / 2)
            cy = int(rect["y"] + rect["height"] / 2)
            self._logger.info(
                f"[Emergency Teardown] Long-pressing tile '{title}' at ({cx}, {cy}) for 'Device Details...'..."
            )
            self.driver.execute_script(
                "mobile: touchAndHold", {"x": cx, "y": cy, "duration": 1.2}
            )
            time.sleep(1.0)
            with self._no_implicit_wait():
                btns = self.driver.find_elements(
                    IOS_PREDICATE_BY,
                    'type == "XCUIElementTypeButton" AND ('
                    'name CONTAINS[c] "Device Details" OR label CONTAINS[c] "Device Details")',
                )
                for b in btns:
                    if b.is_displayed():
                        b.click()
                        time.sleep(1.5)
                        return True
        except WebDriverException as err:
            self._logger.warning(f"[Emergency Teardown] Long-press fallback failed: {err}")
        return False

    def _emergency_recover_and_remove_device(
            self, attempts: int = EMERGENCY_REMOVE_ATTEMPTS
    ) -> bool:
        """Restart GHP and decommission the camera so subsequent iterations start clean."""
        sess = GHPSession._resolve_session(self)
        target_name = str(
            getattr(self, "device_name", None) or getattr(sess, "device_name", "") or "")
        removed = False
        for attempt in range(1, attempts + 1):
            sess._logger.warning(
                f"[Emergency Teardown] Attempt {attempt}/{attempts}: restarting iGHP to decommission '{target_name}'..."
            )
            try:
                sess.stop_ghp()
                time.sleep(1.5)
                sess.start_ghp()
                time.sleep(3.0)
                sess.refresh_ghp_devices()

                opened_settings = False
                try:
                    GHPDevicePage.enter_device_page(sess, device_name=target_name)
                    opened_settings = GHPCameraLivePage.click_setting_btn(sess)
                except Exception as live_err:
                    sess._logger.warning(
                        f"[Emergency Teardown] Could not open Settings via Camera Live ({live_err}); "
                        "trying long-press 'Device Details...' fallback..."
                    )
                if not opened_settings:
                    opened_settings = sess._open_device_details_via_long_press(target_name)

                if opened_settings:
                    sess.handle_remove_device()
                    removed = True
                    sess._device_removed_in_emergency = True
                    sess._logger.info(
                        "[Emergency Teardown] Camera successfully decommissioned during emergency cleanup."
                    )
                    break
            except Exception as err:
                sess._logger.error(
                    f"[Emergency Teardown] Attempt {attempt}/{attempts} failed: {err}")

        try:
            sess.refresh_ghp_devices()
        except Exception:
            pass
        return removed

    def _start_wda_keepalive(self, interval_seconds: float = 15.0) -> threading.Event:
        """Send periodic `query_app_state` calls during long ADB resets so WDA does not time out."""
        stop_event = threading.Event()
        bundle_id = get_ghp_bundle_id()

        def _heartbeat() -> None:
            while not stop_event.wait(interval_seconds):
                try:
                    self.driver.query_app_state(bundle_id)
                except Exception as hb_err:
                    self._logger.debug(f"[WDA KeepAlive] Ignored heartbeat error: {hb_err}")

        thread = threading.Thread(target=_heartbeat, name="ghp-wda-keepalive", daemon=True)
        thread.start()
        return stop_event

    def reset_target_device(self, reason: str = "post-test cleanup") -> bool:
        """Mandatory post-test hardware reset: Smart Plug detail-page power-cycle + ADB factory reset."""
        sess = GHPSession._resolve_session(self)
        device = str(
            getattr(self, "device_name", None) or getattr(sess, "device_name", "") or "ALL")
        sess._logger.info(
            f"[Device Reset] '{device}' -> Smart plug detail-page power-cycle + ADB factory reset ({reason})"
        )
        plug_ok = False
        try:
            sess._logger.info(
                "[Device Reset] Step 1/2: Running GHP Smart plug power-cycle (enter plug page -> OFF/ON)..."
            )
            plug_ok = bool(GHPCommissioningPageObject.power_cycle_smart_plug(sess))
            sess._logger.info(
                f"[Device Reset] Step 1/2: Smart plug power-cycle {'SUCCESS' if plug_ok else 'FAILED'}."
            )
        except Exception as plug_err:
            sess._logger.error(
                f"[Device Reset] Step 1/2: Smart plug power-cycle FAILED: {plug_err}")

        try:
            if sess.stop_ghp():
                sess._ghp_stopped_in_cleanup = True
        except Exception:
            pass

        sess._logger.info(
            "[Device Reset] Step 2/2: Running ADB factory reset (with WDA keep-alive)..."
        )
        stop_keepalive = sess._start_wda_keepalive(interval_seconds=15.0)
        try:
            adb_target = (
                device if DeviceResetUtils.get_config(device) is not None else "Ref2 Battery Camera"
            )
            adb_ok = DeviceResetUtils.adb_factory_reset(adb_target, reason=reason)
        finally:
            stop_keepalive.set()

        sess._logger.info(
            f"[Device Reset] Step 2/2: ADB factory reset {'SUCCESS' if adb_ok else 'FAILED'}."
        )
        ok = plug_ok and adb_ok
        sess._logger.info(
            f"[Device Reset] Result for '{device}' ({reason}): "
            f"smart_plug={'SUCCESS' if plug_ok else 'FAILED'}, adb_reset={'SUCCESS' if adb_ok else 'FAILED'}."
        )
        return ok

    def handle_remove_device(self) -> None:
        """Extract camera metadata from GHP Settings and execute Decommission."""
        sess = GHPSession._resolve_session(self)
        sess._logger.info("Start step: extract GHP device info & decommission camera")
        GHPDeviceSettingPage.get_device_information(self)
        GHPDeviceSettingPage.click_remove_device_btn(self)

    def handle_verify_camera_live_stream_and_remove(self) -> None:
        """Verify 30s camera live stream on GHP, extract info, decommission, and run hardware reset."""
        sess = GHPSession._resolve_session(self)
        sess._device_removed_in_emergency = False
        target_name = str(
            getattr(self, "device_name", None) or getattr(sess, "device_name", "") or "")
        main_error: Optional[Exception] = None

        try:
            sess.refresh_ghp_devices()
            GHPDevicePage.is_device_exist_device_page(self, device_name=target_name)
            GHPDevicePage.enter_device_page(self, device_name=target_name)
            GHPCameraLivePage.verify_camera_live_stream(self)
        except Exception as exc:
            main_error = exc
            BasePage.capture_failure_screenshot(
                sess.driver, reason=f"GHP Verification failure: {exc}", force=True, lock=True
            )
            raise
        finally:
            remove_error: Optional[Exception] = None
            try:
                if getattr(sess, "_device_removed_in_emergency", False):
                    sess._logger.info(
                        "[Post-Test Cleanup] Camera was already decommissioned by emergency teardown; "
                        "proceeding directly to Smart Plug + ADB hardware reset."
                    )
                    sess._device_removed_in_emergency = False
                else:
                    try:
                        GHPSession.handle_remove_device(self)
                    except Exception as rem_exc:
                        remove_error = rem_exc
                        if main_error is None:
                            BasePage.capture_failure_screenshot(
                                sess.driver,
                                reason=f"GHP Decommission failure: {rem_exc}",
                                force=True,
                                lock=True,
                            )
                        sess._logger.error(
                            f"[Post-Test Cleanup] Failed to decommission device via iGHP UI ({rem_exc}). "
                            "Proceeding to mandatory Smart Plug + ADB factory reset..."
                        )
                    if remove_error is None:
                        try:
                            sess.refresh_ghp_devices()
                        except Exception as refresh_exc:
                            sess._logger.warning(
                                f"[Post-Test Cleanup] Refresh iGHP devices failed: {refresh_exc}"
                            )
            finally:
                GHPSession.reset_target_device(self, reason="post-test cleanup")
            if remove_error is not None and main_error is None:
                raise remove_error
