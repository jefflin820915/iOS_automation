"""Page object for Matter device commissioning and iOS system sheets with StaleElement resilience."""
import sys
import time
from contextlib import contextmanager
from typing import Callable, Iterator, List, NoReturn, Optional, Sequence, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException
from common import constants
from common.base_page import BasePage
from page_object.iGHA.gha_camera_activated_page import GHACameraActivatedPage
from page_object.iGHA.gha_connect_device_to_google_account_page import \
    GHAConnectDeviceToGoogleAccountPage
from page_object.iGHA.gha_device_connected_page import GHADeviceConnectedPage
from page_object.iGHA.gha_device_setting_page import GHADeviceSettingPage
from page_object.iGHA.gha_setting_page import GHASettingsPage
from page_object.iGHA.gha_tab_page import GHATabPage
from page_object.iGHA.gha_watch_setup_video_page import GHAWatchSetupVideoPage
from page_object.iGHA.gha_where_is_this_device_page import GHAWhereIsThisDevicePage
from page_object.iGHA.gha_you_should_now_see_live_video_page import GHAYouShouldNowSeeLiveVideoPage
from utils.camera_reset_utils import DeviceResetUtils

Locator = Tuple[str, str]
HeadlineHandler = Callable[[str], bool]


def _contains_any(text: str, keywords: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(kw.lower() in lowered for kw in keywords)


class _CMAppleSheetFailure(AssertionError):
    """Signals that the Apple Matter sheet reported a failure.
    Caught in complete_commissioning_and_pairing_flow and re-raised there as a plain
    AssertionError, so the reported Failure Stage stays COMPLETE_COMMISSIONING_AND_PAIRING_FLOW.
    Subclasses AssertionError so a standalone call of handle_apple_commissioning_sheet still fails.
    """

    def __init__(self, reason: str, card_title: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.card_title = card_title or reason


class GHACommissioningPageObject(BasePage):
    """Unified handler for Apple Matter system sheets and Google Home App commissioning steps.
    NOTE: Private helpers are prefixed with `_cm_` to avoid MRO name collisions in GHASession.
    NOTE: Failure Stage is derived from the innermost page_object frame of the traceback, so
          private helpers must NOT raise the final AssertionError; the public flow method does.
    """
    HEADLINE_LOCATOR: Locator = (AppiumBy.ACCESSIBILITY_ID,
                                 constants.GHA_CONNECTING_TITLE_ACCESSIBILITY_ID)
    APPLE_OVERLAY_WINDOW_CHAIN = '**/XCUIElementTypeWindow[`name == "SBTransientOverlayWindow" AND visible == 1`]'
    APPLE_CARD_TITLE_CHAIN = f'{APPLE_OVERLAY_WINDOW_CHAIN}/**/XCUIElementTypeTextView[`visible == 1`]'
    APPLE_CARD_STATIC_TEXT_CHAIN = f'{APPLE_OVERLAY_WINDOW_CHAIN}/**/XCUIElementTypeStaticText[`visible == 1`]'
    APPLE_TEXT_FIELD_CHAIN = f'{APPLE_OVERLAY_WINDOW_CHAIN}/**/XCUIElementTypeTextField[`visible == 1`]'
    APPLE_KEYBOARD_DONE_CHAIN = (
        '**/XCUIElementTypeKeyboard/**/'
        'XCUIElementTypeButton[`name IN {"Done", "Return", "done", "return"} OR '
        'label IN {"Done", "Return", "done", "return"}`]'
    )
    APPLE_ADD_BTN_CHAIN = (
        f'{APPLE_OVERLAY_WINDOW_CHAIN}/**/'
        'XCUIElementTypeButton[`name CONTAINS "Add to" OR label CONTAINS "Add to"`]'
    )
    APPLE_SET_UP_BTN_CHAIN = (
        f'{APPLE_OVERLAY_WINDOW_CHAIN}/**/'
        'XCUIElementTypeButton[`name CONTAINS "Set Up" OR label CONTAINS "Set Up"`]'
    )
    RECOVERY_EXIT_BTN: Locator = (
        AppiumBy.IOS_PREDICATE,
        'type == "XCUIElementTypeButton" AND '
        '(name IN {"Exit setup", "Exit", "Leave", "Cancel", "Close", "Done", "Dismiss"} OR '
        'label IN {"Exit setup", "Exit", "Leave", "Cancel", "Close", "Done", "Dismiss"})',
    )
    DEVICES_TAB_BTN: Locator = (
        AppiumBy.IOS_CLASS_CHAIN,
        '**/XCUIElementTypeTabBar/**/XCUIElementTypeButton[`name == "Devices" OR label == "Devices"`]',
    )
    DEVICE_TILE: Locator = (AppiumBy.NAME, "deviceTile")
    DEVICE_TILE_TITLE: Locator = (AppiumBy.NAME, "deviceTileTitleTextView")
    DEVICE_TILE_CELL: Locator = (AppiumBy.IOS_PREDICATE,
                                 'type == "XCUIElementTypeCell" AND name CONTAINS "deviceTileCell"')
    # New GHA 'All devices' grid represents each tile as an XCUIElementTypeOther (e.g. name="Eve Energy Plug, On").
    DEVICE_TILE_OTHER: Locator = (
        AppiumBy.IOS_PREDICATE,
        'type == "XCUIElementTypeOther" AND visible == 1 AND (name != NULL OR label != NULL)',
    )
    DEVICE_TILE_STATIC_TEXT: Locator = (
        AppiumBy.IOS_PREDICATE,
        'type == "XCUIElementTypeStaticText" AND visible == 1',
    )
    SYSTEM_ALERT_BUTTONS = ("Add Anyway", "Set up anyway", "OK", "Allow")
    APPLE_SHEET_IGNORED_BUTTON_LABELS = {"ok", "done", "cancel", "continue", "set up", "add anyway"}
    APPLE_FAILURE_KEYWORDS = (
        "unable to add accessory",
        "unable to add",
        "couldn't add",
        "could not add",
        "pairing failed",
        "setup failed",
        "failed to",
        "accessory not found",
        "accessory is not reachable",
        "not reachable",
        "cannot be used",
        "can't be used",
    )
    FAILURE_KEYWORDS = (
        "Can’t connect", "Can't connect", "Couldn't connect", "Could not connect",
        "Unable to connect",
        "Something went wrong", "Check your connection", "Device not found", "Setup failed",
        "Service failure",
        "Reset this device", "Device not reachable", "There may be a problem"
    )
    PAIRED_OFFLINE_FAILURE_KEYWORDS = (
        "There may be a problem",
    )
    OFFLINE_TILE_KEYWORDS = (
        "offline",
        "not connected",
        "unreachable",
        "can't connect",
        "can’t connect",
        "couldn't connect",
        "could not connect",
        "unavailable",
    )
    ALL_DEVICES_FILTER_CHIPS = {
        "favorites",
        "all devices",
        "cameras",
        "lighting",
        "lights",
        "wifi",
        "climate",
        "devices",
    }
    PROGRESS_KEYWORDS = (
        "Adding device", "Getting your device ready", "Next, your device will be added",
        "Connecting",
        "Setting up", "Activating camera", "Downloading update", "Update finished",
    )
    DEFAULT_PLUG_KEYWORDS = (
        "Plug",
        "Outlet",
        "Eve",
        "Eve Energy Plug",
        "Eve Energy",
        "Eve Energy plug",
        "Meross",
        "Meross Mini Plug",
        "Tapo Mini Plug",
        "Tapo Mini",
        "Tapo Mini plug"
    )
    PLUG_ON_VALUES = ("on", "1", "true")
    PLUG_OFF_VALUES = ("off", "0", "false")
    CM_POLL_INTERVAL = 1.5
    CM_PROGRESS_INTERVAL = 2.5
    CM_REMOVE_ATTEMPTS = 2
    CM_ALL_DEVICES_MAX_SCROLLS = 6

    @contextmanager
    def _cm_no_implicit_wait(self) -> Iterator[None]:
        """Temporarily disable implicit wait and always restore the configured default value."""
        previous = getattr(
            constants,
            "DEFAULT_IMPLICIT_WAIT_SECONDS",
            getattr(constants, "DEFAULT_IMPLICIT_WAIT", 10.0),
        )
        try:
            self.driver.implicitly_wait(0)
        except Exception:
            pass
        try:
            yield
        finally:
            try:
                self.driver.implicitly_wait(previous)
            except Exception:
                pass

    def _cm_find_all(self, by: str, value: str, root: Optional[WebElement] = None) -> List[
        WebElement]:
        with self._cm_no_implicit_wait():
            try:
                return (root or self.driver).find_elements(by, value)
            except WebDriverException:
                return []

    def _cm_find_displayed(self, by: str, value: str) -> Optional[WebElement]:
        """Return the first displayed element immediately (stale-safe), or None."""
        for elem in self._cm_find_all(by, value):
            try:
                if elem.is_displayed():
                    return elem
            except WebDriverException:
                continue
        return None

    def _cm_click_displayed(self, by: str, value: str) -> bool:
        elem = self._cm_find_displayed(by, value)
        if elem is None:
            return False
        try:
            elem.click()
            return True
        except WebDriverException:
            return False

    @staticmethod
    def _cm_read_text(elem: WebElement, attrs: Sequence[str] = ("value", "label", "name")) -> str:
        try:
            for attr in attrs:
                raw = elem.get_attribute(attr)
                if isinstance(raw, str) and raw.strip():
                    return raw.strip()
            txt = getattr(elem, "text", "")
            return txt.strip() if isinstance(txt, str) else ""
        except WebDriverException:
            return ""

    def _cm_is_gha_foreground(self) -> bool:
        try:
            bundle_id = getattr(constants, "GHA_BUNDLE_ID", "com.google.Chromecast.enterprise")
            fg_state = getattr(constants, "APP_STATE_FOREGROUND", 4)
            state = self.driver.query_app_state(bundle_id)
            if not isinstance(state, int):
                return True
            return state == fg_state
        except WebDriverException as e:
            self._logger.error(f"Failed to query GHA app state: {e}")
            return False

    def stop_gha(self) -> bool:
        """Terminate the GHA application."""
        try:
            bundle_id = getattr(constants, "GHA_BUNDLE_ID", "com.google.Chromecast.enterprise")
            not_running = getattr(constants, "APP_STATE_NOT_RUNNING", 1)
            if self.driver.query_app_state(bundle_id) == not_running:
                self._logger.info("GHA is not running.")
            else:
                self.driver.terminate_app(bundle_id)
                self._logger.info("GHA stopped successfully.")
            return True
        except WebDriverException as e:
            self._logger.error(f"Failed to stop GHA: {e}")
            return False

    def start_gha(self, timeout: float = 10.0) -> bool:
        """Start GHA and ensure it is running in the foreground."""
        if self._cm_is_gha_foreground():
            self._logger.info("GHA is already running in foreground.")
            return True
        bundle_id = getattr(constants, "GHA_BUNDLE_ID", "com.google.Chromecast.enterprise")
        self._logger.info("Starting Google Home App on iOS...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.driver.activate_app(bundle_id)
            except WebDriverException as e:
                self._logger.debug(f"activate_app failed: {e}")
            if self._cm_is_gha_foreground():
                self._logger.info("GHA launched successfully in foreground.")
                return True
            time.sleep(0.5)
        self._logger.error(f"Timed out after {timeout}s waiting for GHA.")
        return False

    def is_apple_sheet_present(self) -> bool:
        """Check if Apple's native Matter sheet (SBTransientOverlayWindow) is visible."""
        return self._cm_find_displayed(AppiumBy.IOS_CLASS_CHAIN,
                                       self.APPLE_OVERLAY_WINDOW_CHAIN) is not None

    def _cm_read_alert_title(self, alert_elem: WebElement) -> str:
        """Extract the title/message from an iOS system alert before dismissing it."""
        texts: List[str] = []
        for cls_name in ("XCUIElementTypeStaticText", "XCUIElementTypeTextView"):
            for child in self._cm_find_all(AppiumBy.CLASS_NAME, cls_name, root=alert_elem):
                t = self._cm_read_text(child, ("label", "name", "value"))
                if t and t.lower() not in self.APPLE_SHEET_IGNORED_BUTTON_LABELS and t not in texts:
                    texts.append(t)
        if texts:
            return texts[0]
        return self._cm_read_text(alert_elem, ("label", "name", "value"))

    def handle_system_alert(self) -> bool:
        """Dismiss iOS system alerts like 'Uncertified Accessory'.
        Note: Does NOT click 'OK' on an Apple Matter failure card so _cm_on_apple_failure can handle it.
        """
        alert_elem = self._cm_find_displayed(AppiumBy.CLASS_NAME,
                                             constants.GHA_COMMISSION_WINDOW_ALERT)
        if alert_elem is None:
            return False
        alert_title = self._cm_read_alert_title(alert_elem)
        if alert_title:
            self._cm_last_apple_card_title = alert_title
            if _contains_any(alert_title, self.APPLE_FAILURE_KEYWORDS):
                self._cm_apple_failure_title = alert_title
                return False
        # If the Apple sheet is active and showing a failure card, let handle_apple_commissioning_sheet handle it.
        if self.is_apple_sheet_present():
            card_title = self._cm_get_apple_card_title()
            if card_title:
                self._cm_last_apple_card_title = card_title
                if _contains_any(card_title, self.APPLE_FAILURE_KEYWORDS):
                    self._cm_apple_failure_title = card_title
                    return False
        self._logger.warning(
            f"Detected iOS System Alert dialog{f' ({alert_title!r})' if alert_title else ''}!")
        for btn_text in self.SYSTEM_ALERT_BUTTONS:
            if self._cm_click_displayed(AppiumBy.ACCESSIBILITY_ID, btn_text):
                if btn_text == "OK" and alert_title and not getattr(self, "_cm_apple_failure_title",
                                                                    ""):
                    self._cm_apple_failure_title = alert_title
                self._logger.info(f"Dismissed system alert via '{btn_text}'.")
                return True
        return False

    def _cm_get_apple_card_title(self) -> str:
        for _ in range(3):
            candidates: List[str] = []
            for elem in self._cm_find_all(AppiumBy.IOS_CLASS_CHAIN, self.APPLE_CARD_TITLE_CHAIN):
                try:
                    if not elem.is_displayed():
                        continue
                except WebDriverException:
                    continue
                title = self._cm_read_text(elem, ("name", "label", "value"))
                if title and title.lower() not in self.APPLE_SHEET_IGNORED_BUTTON_LABELS:
                    candidates.append(title)
            if not candidates:
                for elem in self._cm_find_all(AppiumBy.IOS_CLASS_CHAIN,
                                              self.APPLE_CARD_STATIC_TEXT_CHAIN):
                    try:
                        if not elem.is_displayed():
                            continue
                    except WebDriverException:
                        continue
                    title = self._cm_read_text(elem, ("name", "label", "value"))
                    if title and title.lower() not in self.APPLE_SHEET_IGNORED_BUTTON_LABELS:
                        candidates.append(title)
            if candidates:
                for c in candidates:
                    if _contains_any(c, self.APPLE_FAILURE_KEYWORDS):
                        return c
                return candidates[0]
            time.sleep(0.4)
        return ""

    def _cm_click_apple_sheet_button(self, *names: str) -> bool:
        """Click the first matching button inside SBTransientOverlayWindow."""
        for name in names:
            chain = (
                f'{self.APPLE_OVERLAY_WINDOW_CHAIN}/**/'
                f'XCUIElementTypeButton[`name == "{name}" OR label == "{name}"`]'
            )
            if self._cm_click_displayed(AppiumBy.IOS_CLASS_CHAIN, chain):
                return True
        return False

    def _cm_on_apple_added(self) -> None:
        self._logger.info("[AppleSheet] Device successfully added! Clicking 'Done'...")
        done_id = getattr(constants, "GHA_DONE_BTN_ACCESSIBILITY_ID", "Done")
        if self._cm_click_apple_sheet_button(done_id, "Done"):
            time.sleep(1.5)

    def _cm_on_apple_failure(self, card_title: str) -> NoReturn:
        """Capture failure screenshot on the Apple sheet, then dismiss it and signal the main flow."""
        self._logger.error(f"[AppleSheet] Reported failure: '{card_title}'")
        self._cm_apple_failure_title = card_title
        self._cm_last_apple_card_title = card_title
        if hasattr(BasePage, "capture_failure_screenshot"):
            BasePage.capture_failure_screenshot(
                self.driver, reason=f"Apple sheet failure: {card_title}", force=True, lock=True
            )
        self._cm_click_apple_sheet_button("OK", "Done")
        time.sleep(2.0)
        raise _CMAppleSheetFailure(f"Apple sheet failed with '{card_title}'", card_title=card_title)

    def _cm_on_apple_bridge_name(self, device_name: str) -> None:
        self._logger.info(
            f"[AppleSheet] Naming step detected. Setting device name to '{device_name}'...")
        field = (
                self._cm_find_displayed(AppiumBy.IOS_CLASS_CHAIN, self.APPLE_TEXT_FIELD_CHAIN)
                or self._cm_find_displayed(AppiumBy.CLASS_NAME,
                                           constants.GHA_TEXT_EDIT_VIEW_CLASS_NAME)
        )
        if field is None:
            self._logger.debug("[AppleSheet] Name field not found yet (sheet transitioning).")
            return
        target_name = (device_name or "").strip()
        current_val = self._cm_read_text(field, ("value",)).strip()
        already_typed = (
                bool(target_name)
                and (
                        current_val == target_name
                        or (
                                getattr(self, "_cm_named_in_current_flow", False)
                                and current_val in ("", target_name)
                        )
                )
        )
        if already_typed:
            self._logger.info(
                f"[AppleSheet] Name field already set to '{target_name}'; skipping clear() to prevent race."
            )
        else:
            try:
                field.clear()
                time.sleep(0.5)
                field.send_keys(device_name)
                time.sleep(0.5)
                self._cm_named_in_current_flow = True
            except WebDriverException as e:
                self._logger.debug(f"[AppleSheet] Naming field transition: {e}")
                return
        if self._cm_click_displayed(AppiumBy.IOS_CLASS_CHAIN, self.APPLE_KEYBOARD_DONE_CHAIN):
            self._logger.info(
                "[AppleSheet] Clicked keyboard 'Done'/'Return' to commit device name.")
            time.sleep(0.5)
        if self._cm_click_apple_sheet_button("Continue") or \
                self._cm_click_displayed(AppiumBy.ACCESSIBILITY_ID, "Continue"):
            self._logger.info("[AppleSheet] Submitted custom device name.")
            time.sleep(2.0)

    def _cm_click_apple_add_button(self) -> bool:
        if self._cm_click_displayed(AppiumBy.IOS_CLASS_CHAIN, self.APPLE_ADD_BTN_CHAIN):
            self._logger.info("[AppleSheet] Clicked 'Add to Google Home'.")
            time.sleep(1.0)
            return True
        return False

    def _cm_click_apple_setup_button(self) -> bool:
        if self._cm_click_displayed(AppiumBy.IOS_CLASS_CHAIN, self.APPLE_SET_UP_BTN_CHAIN):
            self._logger.info("[AppleSheet] Clicked 'Set Up'.")
            time.sleep(1.0)
            return True
        return False

    def handle_apple_commissioning_sheet(self, device_name: str) -> bool:
        """Observe and act on the foreground Apple Matter sheet.
        Returns:
            True if a system alert / Apple sheet was present (and handled), False otherwise.
        Raises:
            _CMAppleSheetFailure (an AssertionError): If the Apple sheet reports
                'Unable to Add Accessory' (or other APPLE_FAILURE_KEYWORDS). Recovery is performed by the caller.
        """
        try:
            if self.is_apple_sheet_present():
                card_title = self._cm_get_apple_card_title()
                if card_title:
                    self._cm_last_apple_card_title = card_title
                    self._logger.info(f"[AppleSheet] Active card: '{card_title}'")
                    if _contains_any(card_title, self.APPLE_FAILURE_KEYWORDS):
                        self._cm_on_apple_failure(card_title)
                    if _contains_any(card_title, ("added to",)):
                        self._cm_on_apple_added()
                        return True
                    if "Bridge Name" in card_title or "Name" in card_title:
                        self._cm_on_apple_bridge_name(device_name)
                        return True
                    if self._cm_click_apple_add_button() or self._cm_click_apple_setup_button():
                        return True
                if self.handle_system_alert():
                    time.sleep(1.0)
                    return True
                if card_title:
                    self._logger.info(f"[AppleSheet] In progress: '{card_title}'... Waiting.")
                    time.sleep(2.0)
                return True
            if self.handle_system_alert():
                time.sleep(1.0)
                return True
            return False
        except AssertionError:
            raise
        except WebDriverException as e:
            self._logger.debug(
                f"[AppleSheet] Transition in progress ({e.__class__.__name__}). Retrying...")
            time.sleep(1.0)
            return True

    def _cm_dismiss_commissioning_and_go_to_devices(self) -> None:
        """Dismiss error dialogs / setup screens and return GHA to the Devices tab."""
        self._logger.info(
            "[Recovery] Dismissing commissioning screens and returning to Devices tab...")
        for _ in range(5):
            btn = self._cm_find_displayed(*self.RECOVERY_EXIT_BTN)
            if btn is None:
                break
            label = self._cm_read_text(btn, ("label", "name")) or "Exit"
            self._logger.info(f"[Recovery] Clicking '{label}'...")
            try:
                btn.click()
            except WebDriverException:
                pass
            time.sleep(1.5)
        if self._cm_click_displayed(*self.DEVICES_TAB_BTN):
            self._logger.info("[Recovery] Tapped Devices tab.")
            time.sleep(2.0)

    def _cm_remove_paired_device(self, device_name: str,
                                 attempts: int = CM_REMOVE_ATTEMPTS) -> bool:
        """Restart GHA and remove the paired (offline) device from Home Settings before hardware reset."""
        if not device_name:
            self._logger.warning("[Recovery] No device_name specified for paired device removal.")
            return False
        resolved_fallback = getattr(self, "_cm_resolved_tile_name", "") or ""
        for attempt in range(1, attempts + 1):
            self._logger.warning(
                f"[Recovery] Removing paired offline device '{device_name}' "
                f"(attempt {attempt}/{attempts})..."
            )
            try:
                self.stop_gha()
                time.sleep(2.0)
                self.start_gha()
                time.sleep(5.0)
                self._logger.info("[Recovery] Navigating to Home Settings to remove device...")
                GHATabPage(self.driver).enter_home_settings_page()
                settings_page = GHASettingsPage(self.driver)
                opened = settings_page.open_device_settings(device_name=device_name)
                if not opened and resolved_fallback and resolved_fallback.lower() != device_name.lower():
                    self._logger.info(
                        f"[Recovery] Primary name '{device_name}' not found in Settings; "
                        f"trying resolved tile name '{resolved_fallback}'..."
                    )
                    opened = settings_page.open_device_settings(device_name=resolved_fallback)
                if not opened:
                    raise RuntimeError(f"Device '{device_name}' not found in Settings")
                GHADeviceSettingPage(self.driver).get_device_information()
                if GHADeviceSettingPage(self.driver).click_remove_device_btn() is False:
                    raise RuntimeError(f"Failed to remove '{device_name}' in Device Settings")
                self._logger.info(
                    f"[Recovery] Successfully removed paired offline device '{device_name}'.")
                return True
            except Exception as err:
                self._logger.error(
                    f"[Recovery] Remove paired device attempt {attempt}/{attempts} failed: {err}"
                )
        return False

    def _cm_format_apple_sheet_context(self) -> str:
        """Return a parenthetical suffix with the Apple sheet's failure or last title if present."""
        apple_fail = getattr(self, "_cm_apple_failure_title", "") or ""
        apple_last = getattr(self, "_cm_last_apple_card_title", "") or ""
        if apple_fail:
            return f" | Apple sheet failed with '{apple_fail}'"
        if apple_last:
            return f" | Apple sheet last title: '{apple_last}'"
        return ""

    def _cm_recover(self, reason: str, remove_paired_device: bool = False) -> str:
        """Capture failure screenshot, dismiss commissioning screens, optionally remove paired offline device, and reset.
        Reset method comes from DeviceResetUtils: adb factory reset for configured devices
        (e.g. 'Ref2 Battery Camera'), smart plug power-cycle for every other device.  [DEVICE RESET]
        Returns:
            The FATAL error message. The CALLER must raise it, so that the innermost
            page_object frame (used as Failure Stage) is the caller, not this helper.
        """
        if hasattr(BasePage, "capture_failure_screenshot"):
            BasePage.capture_failure_screenshot(self.driver, reason=reason, force=True, lock=True)
        try:
            self._cm_dismiss_commissioning_and_go_to_devices()
        except Exception as e:
            self._logger.warning(f"[Recovery] Dismiss step error: {e}")
        device = getattr(self, "_cm_reset_device_name", "") or ""  # [DEVICE RESET]
        remove_msg = ""
        if remove_paired_device:
            removed = self._cm_remove_paired_device(device)
            remove_msg = f" Remove paired device: {'SUCCESS' if removed else 'FAILED'}."
        method = DeviceResetUtils.describe(device)
        try:
            reset_ok = DeviceResetUtils.reset_device(
                device, smart_plug_reset=self.power_cycle_smart_plug,
                reason="commissioning recovery"
            )
        except Exception as e:
            self._logger.warning(f"[Recovery] {method} step error: {e}")
            reset_ok = False
        return f"FATAL: {reason}.{remove_msg} {method}: {'SUCCESS' if reset_ok else 'FAILED'}."

    @staticmethod
    def _cm_get_fallback_device_names(device_name: str) -> List[str]:
        """Return default GHA hardware-type fallback names ('Doorbell' / 'Camera') if custom naming did not sync."""
        norm = " ".join((device_name or "").split()).strip().lower()
        if not norm:
            return []
        if "doorbell" in norm and norm != "doorbell":
            return ["Doorbell"]
        if "camera" in norm and norm != "camera":
            return ["Camera"]
        return []

    @staticmethod
    def _cm_matches_exact_tile_name(raw_text: str, target_name: str) -> bool:
        """Check whether raw_text from a tile represents a device whose title is exactly target_name."""
        norm_target = " ".join((target_name or "").split()).strip().lower()
        if not norm_target or not raw_text:
            return False
        lines = [" ".join(line.split()).strip() for line in raw_text.splitlines() if line.strip()]
        first_seg = " ".join(raw_text.split()).split(",")[0].strip().lower()
        candidates = {first_seg}
        if lines:
            candidates.add(lines[0].split(",")[0].strip().lower())
        return norm_target in candidates or f"attic {norm_target}" in candidates

    def _cm_dismiss_setup_new_devices_prompt(self) -> bool:
        """Dismiss the 'Set up new devices?' bottom sheet if present after GHA launch (0s implicit wait)."""
        not_now_locators = (
            (AppiumBy.ACCESSIBILITY_ID, "actionBarSecondaryButton"),
            (AppiumBy.ACCESSIBILITY_ID, "Not now"),
            (
                AppiumBy.IOS_PREDICATE,
                'type IN {"XCUIElementTypeButton", "XCUIElementTypeStaticText"} AND '
                '(name IN {"actionBarSecondaryButton", "Not now"} OR label == "Not now")',
            ),
        )
        for by, loc in not_now_locators:
            if self._cm_click_displayed(by, loc):
                self._logger.info(
                    "[Commissioning] Dismissed 'Set up new devices?' sheet via 'Not now'."
                )
                time.sleep(1.0)
                return True
        return False

    def _cm_inspect_target_device_on_screen(
            self, target_name: str, exact_tile_match: bool = False
    ) -> Optional[str]:
        """Check if `target_name` is visible on the current 'All devices' viewport and read its online/offline state.
        Returns:
            'online'  -> Target device tile is visible and NOT showing an offline state.
            'offline' -> Target device tile is visible and showing 'Offline' / 'Not connected' / etc.
            None      -> Target device tile is not visible on the current screen.
        """
        norm_target = " ".join((target_name or "").split()).strip().lower()
        if not norm_target:
            return None
        clean = target_name.strip().replace('"', '\\"')
        predicate = (
            'type IN {"XCUIElementTypeCell", "XCUIElementTypeButton", "XCUIElementTypeOther", "XCUIElementTypeStaticText"} '
            f'AND (label CONTAINS[c] "{clean}" OR name CONTAINS[c] "{clean}" OR value CONTAINS[c] "{clean}")'
        )
        candidates = list(self._cm_find_all(AppiumBy.IOS_PREDICATE, predicate))
        for extra in self._cm_find_all(*self.DEVICE_TILE_CELL) + self._cm_find_all(
                *self.DEVICE_TILE):
            if extra not in candidates:
                candidates.append(extra)
        found_target = False
        saw_offline = False
        matched_rects: List[dict] = []
        for elem in candidates:
            try:
                if not elem.is_displayed():
                    continue
            except WebDriverException:
                continue
            label = self._cm_read_text(elem, ("label",))
            name = self._cm_read_text(elem, ("name",))
            value = self._cm_read_text(elem, ("value",))
            child_texts: List[str] = []
            for child in self._cm_find_all(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText",
                                           root=elem):
                ct = self._cm_read_text(child, ("label", "name", "value"))
                if ct and ct not in child_texts:
                    child_texts.append(ct)
            all_parts = [p for p in (label, name, value, *child_texts) if p]
            combined = " | ".join(all_parts)
            if not combined or "scroll bar" in combined.lower():
                continue
            rect = None
            try:
                r = elem.rect
                if isinstance(r, dict) and isinstance(r.get("height"), (int, float)):
                    rect = r
            except Exception:
                rect = None
            if rect is not None:
                if rect.get("y", 100) <= 50 or rect.get("height", 50) < 12 or rect.get("height",
                                                                                       50) > 260:
                    continue
            if label and label != "deviceTile" and not label.startswith("deviceTileCell"):
                primary_title = label
            elif name and name != "deviceTile" and not name.startswith("deviceTileCell"):
                primary_title = name
            elif child_texts:
                primary_title = child_texts[0]
            else:
                primary_title = combined
            if primary_title.strip().lower() in self.ALL_DEVICES_FILTER_CHIPS:
                continue
            if exact_tile_match:
                if not self._cm_matches_exact_tile_name(primary_title, target_name):
                    continue
            else:
                if norm_target not in combined.lower():
                    continue
            found_target = True
            if rect is not None:
                matched_rects.append(rect)
            if _contains_any(combined, self.OFFLINE_TILE_KEYWORDS):
                saw_offline = True
        # If a title StaticText was matched directly without a container wrapping its sibling 'Offline' status label,
        # check if any visible StaticText with an offline keyword lies within the same tile bounding region.
        if found_target and not saw_offline and matched_rects:
            offline_pred = (
                'type == "XCUIElementTypeStaticText" AND ('
                'label CONTAINS[c] "Offline" OR name CONTAINS[c] "Offline" OR value CONTAINS[c] "Offline" OR '
                'label CONTAINS[c] "Not connected" OR label CONTAINS[c] "Unreachable")'
            )
            for off_elem in self._cm_find_all(AppiumBy.IOS_PREDICATE, offline_pred):
                try:
                    if not off_elem.is_displayed():
                        continue
                    or_rect = off_elem.rect
                    if not isinstance(or_rect, dict):
                        continue
                    ox = or_rect.get("x", 0) + or_rect.get("width", 0) / 2
                    oy = or_rect.get("y", 0) + or_rect.get("height", 0) / 2
                    for m_rect in matched_rects:
                        mx = m_rect.get("x", 0) + m_rect.get("width", 0) / 2
                        my = m_rect.get("y", 0)
                        if abs(ox - mx) <= 110 and -20 <= (oy - my) <= 130:
                            saw_offline = True
                            break
                    if saw_offline:
                        break
                except Exception:
                    continue
        if not found_target:
            return None
        return "offline" if saw_offline else "online"

    def _cm_collect_visible_tile_names(self) -> List[str]:
        """Return visible device tile titles on the current 'All devices' screen to detect scroll progress."""
        names: List[str] = []
        elems = (
                self._cm_find_all(*self.DEVICE_TILE_CELL)
                + self._cm_find_all(*self.DEVICE_TILE)
                + self._cm_find_all(*self.DEVICE_TILE_OTHER)
        )
        for elem in elems:
            try:
                if not elem.is_displayed():
                    continue
                ident = self._cm_tile_identity(elem)
                if ident and ident.strip().lower() not in self.ALL_DEVICES_FILTER_CHIPS and ident not in names:
                    names.append(ident)
            except Exception:
                continue
        return names

    def _cm_check_device_status_on_all_devices(
            self, device_name: str, max_scrolls: int = CM_ALL_DEVICES_MAX_SCROLLS
    ) -> str:
        """Restart GHA, navigate to the 'All devices' page, and check if `device_name` exists and is online/offline.
        Returns:
            'online'    -> Device exists in Home on 'All devices' and is online.
            'offline'   -> Device exists in Home on 'All devices' and is offline.
            'not_found' -> Device does not exist in Home on 'All devices'.
        """
        target = (device_name or "").strip()
        self._cm_resolved_tile_name = target
        if not target:
            return "not_found"
        self._logger.info(
            f"[Commissioning] Restarting GHA and navigating to 'All devices' to check if '{target}' "
            "exists in Home after commissioning timeout..."
        )
        self.stop_gha()
        time.sleep(2.0)
        if not self.start_gha():
            self._logger.warning(
                "[Commissioning] Failed to start GHA during timeout 'All devices' check."
            )
            return "not_found"
        time.sleep(2.5)
        self._cm_dismiss_setup_new_devices_prompt()
        try:
            devices_tab = getattr(getattr(constants, "TAB", None), "DEVICES", "Devices")
            GHATabPage(self.driver).go_to_tab(devices_tab)
            time.sleep(2.0)
        except Exception as nav_err:
            self._logger.warning(
                f"[Commissioning] Failed to navigate to 'All devices' tab: {nav_err}"
            )
        fallback_names = self._cm_get_fallback_device_names(target)

        def _probe_current_screen() -> Optional[Tuple[str, str]]:
            st = self._cm_inspect_target_device_on_screen(target, exact_tile_match=False)
            if st is not None:
                return st, target
            for fb in fallback_names:
                fb_st = self._cm_inspect_target_device_on_screen(fb, exact_tile_match=True)
                if fb_st is not None:
                    return fb_st, fb
            return None

        # Poll top screen first (up to 3 checks if tiles are present/loading)
        for poll_idx in range(3):
            hit = _probe_current_screen()
            if hit is not None:
                initial_status, matched_name = hit
                time.sleep(1.5)
                settled = _probe_current_screen()
                final_status = settled[0] if settled is not None else initial_status
                self._cm_resolved_tile_name = matched_name
                self._logger.info(
                    f"[Commissioning] Found '{matched_name}' on 'All devices' (top screen) "
                    f"with status='{final_status.upper()}'."
                )
                return final_status
            if poll_idx == 0 and not self._cm_collect_visible_tile_names():
                # No tiles rendered on screen (e.g. unit-test mock driver or empty Home); exit fast.
                break
            time.sleep(1.0)
        seen_tiles = set(self._cm_collect_visible_tile_names())
        if not seen_tiles:
            return "not_found"
        consecutive_no_new = 0
        for scroll_idx in range(1, max_scrolls + 1):
            self._logger.info(
                f"[Commissioning] '{target}' not in current 'All devices' view; "
                f"scrolling down ({scroll_idx}/{max_scrolls})..."
            )
            try:
                self.driver.execute_script("mobile: scroll", {"direction": "down"})
            except Exception:
                try:
                    win = self.driver.get_window_size()
                    cx = int(win.get("width", 390)) // 2
                    sy = int(win.get("height", 844) * 0.68)
                    ey = int(win.get("height", 844) * 0.38)
                    self.driver.swipe(cx, sy, cx, ey, duration=450)
                except Exception:
                    break
            time.sleep(1.5)
            hit = _probe_current_screen()
            if hit is not None:
                initial_status, matched_name = hit
                time.sleep(1.5)
                settled = _probe_current_screen()
                final_status = settled[0] if settled is not None else initial_status
                self._cm_resolved_tile_name = matched_name
                self._logger.info(
                    f"[Commissioning] Found '{matched_name}' on 'All devices' (scroll {scroll_idx}) "
                    f"with status='{final_status.upper()}'."
                )
                return final_status
            curr_tiles = self._cm_collect_visible_tile_names()
            new_tiles = [t for t in curr_tiles if t not in seen_tiles]
            if new_tiles:
                seen_tiles.update(new_tiles)
                consecutive_no_new = 0
            else:
                consecutive_no_new += 1
                if consecutive_no_new >= 2:
                    break
        return "not_found"

    def _cm_mark_timeout_online_recovery(self) -> None:
        """Record that commissioning succeeded via the timeout 'All devices' online check.
        Also installs a lightweight guard on the 4 post-commissioning OOBE page methods so that
        even if the caller invokes them after GHA was restarted onto 'All devices', they return
        immediately instead of waiting on OOBE screens that were already bypassed.
        """
        self._cm_recovered_online_on_timeout = True
        try:
            setattr(self.driver, "_commissioned_via_timeout_online", True)
        except Exception:
            pass
        resolved = getattr(self, "_cm_resolved_tile_name", "") or ""
        target = getattr(self, "_cm_reset_device_name", "") or ""
        if resolved and target and resolved.lower() != target.lower():
            session = getattr(self, "session", None)
            if session is not None:
                session._resolved_device_name = resolved
            dev_mod = sys.modules.get("page_object.iGHA.gha_device_page")
            if dev_mod is not None and hasattr(dev_mod, "GHADevicePage"):
                dev_mod.GHADevicePage._resolved_device_name = resolved
        oobe_targets = (
            (
                "page_object.iGHA.gha_choose_whether_you_want_to_turn_on_video_history",
                "GHAChooseWhetherYouWantToTurnOnVideoPage",
                "enable_video_history_and_proceed",
                False,
            ),
            (
                "page_object.iGHA.gha_adjust_your_mic_settings",
                "GHAAdjustYourMicSettingsPage",
                "enable_all_mic_settings_and_proceed",
                False,
            ),
            (
                "page_object.iGHA.gha_stay_in_the_know_page",
                "GHAStayInTheKnowPage",
                "handle_stay_in_the_know_page_process",
                False,
            ),
            (
                "page_object.iGHA.gha_your_camera_device_is_ready_page",
                "GHAYourCameraDeviceIsReadyPage",
                "click_done_btn",
                True,
            ),
        )
        for mod_name, cls_name, method_name, clear_flag in oobe_targets:
            mod = sys.modules.get(mod_name)
            cls = getattr(mod, cls_name, None) if mod is not None else None
            orig = getattr(cls, method_name, None) if cls is not None else None
            if orig is None or getattr(orig, "_cm_timeout_online_wrapped", False):
                continue

            def _make_wrapper(fn, m_name: str, should_clear: bool):
                def _wrapped(page_or_session, *args, **kwargs):
                    drv = getattr(page_or_session, "driver", None)
                    if drv is not None and getattr(drv, "_commissioned_via_timeout_online", False):
                        if should_clear:
                            try:
                                setattr(drv, "_commissioned_via_timeout_online", False)
                            except Exception:
                                pass
                        logger = getattr(page_or_session, "_logger", None)
                        if logger is not None:
                            logger.info(
                                f"[Commissioning] Skipping '{m_name}' because device is already "
                                "confirmed ONLINE on 'All devices' after timeout recovery."
                            )
                        return True
                    return fn(page_or_session, *args, **kwargs)

                _wrapped._cm_timeout_online_wrapped = True
                return _wrapped

            setattr(cls, method_name, _make_wrapper(orig, method_name, clear_flag))

    @staticmethod
    def _cm_build_plug_predicate(keywords: Sequence[str]) -> str:
        """Build a fast IOS_PREDICATE matching only plug/outlet tiles by name or label (without slow visible==1)."""
        clauses: List[str] = []
        seen = set()
        for kw in keywords:
            clean = kw.strip().replace('"', '\\"')
            if not clean or clean.lower() in seen:
                continue
            seen.add(clean.lower())
            clauses.append(f'label CONTAINS[c] "{clean}" OR name CONTAINS[c] "{clean}"')
        kw_filter = " OR ".join(
            clauses) if clauses else 'label CONTAINS[c] "Plug" OR name CONTAINS[c] "Plug"'
        return (
            'type IN {"XCUIElementTypeOther", "XCUIElementTypeButton", "XCUIElementTypeCell"} '
            f'AND ({kw_filter})'
        )

    def _cm_ensure_all_devices_ready(self) -> bool:
        """Ensure iOS screen is unlocked and GHA is in foreground on the 'All devices' tab.
        If the screen locked or GHA closed/crashed during plug toggling, automatically unlocks
        the screen, relaunches GHA, and navigates back to the Devices ('All devices') tab.
        """
        try:
            if hasattr(self.driver, "is_locked") and self.driver.is_locked() is True:
                self._logger.warning(
                    "[PowerCycle] iOS screen is LOCKED during power-cycle! Auto-unlocking...")
                if hasattr(BasePage, "_unlock_device_if_locked"):
                    BasePage._unlock_device_if_locked(self)
                elif hasattr(self.driver, "unlock"):
                    self.driver.unlock()
        except Exception as lock_err:
            self._logger.debug(f"[PowerCycle] Lock check ignored error: {lock_err}")
        if not self._cm_is_gha_foreground():
            self._logger.warning(
                "[PowerCycle] GHA is NOT in foreground (closed/crashed)! "
                "Relaunching GHA and returning to 'All devices'..."
            )
            if not self.start_gha():
                return False
            time.sleep(2.0)
            try:
                GHATabPage(self.driver).go_to_tab(constants.TAB.DEVICES)
                time.sleep(1.5)
            except Exception as nav_err:
                self._logger.warning(
                    f"[PowerCycle] Failed to re-open 'All devices' tab after relaunch: {nav_err}")
                return False
        return True

    def _cm_tile_identity(self, tile: WebElement) -> str:
        """Human-readable device name of a tile (fast label/name check first, legacy title element fallback)."""
        label = self._cm_read_text(tile, ("label", "name", "value"))
        if label and label != "deviceTile" and not label.startswith("deviceTileCell"):
            return label.split(",")[0].strip()
        titles = self._cm_find_all(*self.DEVICE_TILE_TITLE, root=tile)
        if titles:
            title = self._cm_read_text(titles[0], ("value", "label", "name"))
            if title:
                return title
        return label.split(",")[0].strip() if label else ""

    def _cm_is_valid_other_tile(self, elem: WebElement) -> bool:
        """Filter XCUIElementTypeOther elements to actual device tile cards (excludes full-screen containers)."""
        text = self._cm_read_text(elem, ("label", "name"))
        if not text or "vertical scroll bar" in text.lower() or "horizontal scroll bar" in text.lower():
            return False
        try:
            rect = elem.rect
            return 20 <= rect.get("height", 0) <= 220 and rect.get("width", 0) >= 60
        except WebDriverException:
            return False

    def _cm_all_tile_candidates(self, keywords: Optional[Sequence[str]] = None) -> List[WebElement]:
        """Return matching plug tile elements quickly without scanning all XCUIElementTypeOther views."""
        search_kws = tuple(keywords or self.DEFAULT_PLUG_KEYWORDS)
        predicate = self._cm_build_plug_predicate(search_kws)
        matched = [
            elem for elem in self._cm_find_all(AppiumBy.IOS_PREDICATE, predicate)
            if self._cm_is_valid_other_tile(elem)
        ]
        if matched:
            return matched
        legacy = self._cm_find_all(*self.DEVICE_TILE) + self._cm_find_all(*self.DEVICE_TILE_CELL)
        return legacy

    def _cm_is_plug(self, elem: WebElement, keywords: Sequence[str]) -> bool:
        text = self._cm_read_text(elem, ("label", "name", "value"))
        return _contains_any(text, keywords)

    def _cm_discover_plugs(self, keywords: Sequence[str]) -> List[str]:
        """Collect unique names of plug/outlet tiles on the Devices / All devices view (scrolls once if needed)."""
        found: List[str] = []
        for attempt in range(2):
            if not self._cm_ensure_all_devices_ready():
                break
            candidates = self._cm_all_tile_candidates(keywords)
            for elem in candidates:
                try:
                    if not self._cm_is_plug(elem, keywords):
                        continue
                    name = self._cm_tile_identity(elem)
                except WebDriverException:
                    continue
                if name and name not in found:
                    found.append(name)
            if found or attempt == 1:
                break
            self._logger.info("[PowerCycle] No plugs found on top fold, scrolling down...")
            try:
                self.driver.execute_script("mobile: scroll", {"direction": "down"})
                time.sleep(1.5)
            except WebDriverException:
                pass
        return found

    def _cm_locate_plug_tile(self, target_name: str) -> Optional[WebElement]:
        """Freshly locate a plug tile by name using a direct targeted predicate (avoids slow full-screen scans)."""
        if not self._cm_is_gha_foreground():
            return None
        target = target_name.strip().lower()
        predicate = self._cm_build_plug_predicate((target_name,))
        for elem in self._cm_find_all(AppiumBy.IOS_PREDICATE, predicate):
            try:
                if not self._cm_is_valid_other_tile(elem):
                    continue
                ident = self._cm_tile_identity(elem).lower()
                raw = self._cm_read_text(elem, ("label", "name")).lower()
                if target == ident or target in ident or target in raw:
                    return elem
            except WebDriverException:
                continue
        for tile in self._cm_find_all(*self.DEVICE_TILE):
            try:
                if target in self._cm_tile_identity(tile).lower() or \
                        target in self._cm_read_text(tile, ("label", "name")).lower():
                    return tile
            except WebDriverException:
                continue
        for cell in self._cm_find_all(*self.DEVICE_TILE_CELL):
            if target in self._cm_read_text(cell, ("label", "name")).lower():
                inner = self._cm_find_all(*self.DEVICE_TILE, root=cell)
                return inner[0] if inner else cell
        return None

    def _cm_read_plug_state(self, tile: WebElement) -> str:
        """Read 'on' / 'off' state from 'Name, On/Off' label suffix, value attribute, or child StaticText."""
        label_or_name = self._cm_read_text(tile, ("label", "name"))
        if "," in label_or_name:
            suffix = label_or_name.rsplit(",", 1)[-1].strip().lower()
            if suffix:
                return suffix
        val = self._cm_read_text(tile, ("value",)).lower()
        if val in self.PLUG_ON_VALUES or val in self.PLUG_OFF_VALUES:
            return val
        for child in self._cm_find_all(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText", root=tile):
            child_txt = self._cm_read_text(child, ("value", "label", "name")).lower()
            if child_txt in self.PLUG_ON_VALUES or child_txt in self.PLUG_OFF_VALUES or child_txt == "offline":
                return child_txt
        return val

    def _cm_is_desired_plug_state(self, state: str, target_off: bool) -> bool:
        """Return True if `state` matches the desired ON/OFF target."""
        if target_off:
            return state in self.PLUG_OFF_VALUES
        return state in self.PLUG_ON_VALUES

    def _cm_tap_plug_tile(self, tile: WebElement, plug_name: str, target_off: bool) -> bool:
        """Tap the plug tile immediately via center coordinates (with element.click fallback) and verify state.
        Automatically recovers if GHA closes/crashed or the iOS screen locks during the toggle.
        """
        target_label = "OFF" if target_off else "ON"
        if not self._cm_ensure_all_devices_ready():
            return False
        active_tile = tile
        rect = None
        try:
            rect = active_tile.rect
        except WebDriverException:
            active_tile = self._cm_locate_plug_tile(plug_name)
            if active_tile is not None:
                try:
                    rect = active_tile.rect
                except WebDriverException:
                    rect = None
        tapped = False
        if rect:
            cx = int(rect["x"] + rect["width"] / 2)
            cy = int(rect["y"] + rect["height"] / 2)
            try:
                self._logger.info(
                    f"[PowerCycle] Tapping '{plug_name}' at ({cx}, {cy}) to switch {target_label}..."
                )
                self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                tapped = True
            except WebDriverException as tap_err:
                self._logger.debug(f"[PowerCycle] mobile: tap failed for '{plug_name}': {tap_err}")
        if not tapped and active_tile is not None:
            try:
                active_tile.click()
                tapped = True
            except WebDriverException as click_err:
                self._logger.error(f"[PowerCycle] Click failed for '{plug_name}': {click_err}")
                return False
        time.sleep(1.2)
        if not self._cm_ensure_all_devices_ready():
            return False
        refreshed = self._cm_locate_plug_tile(plug_name)
        if refreshed is not None:
            new_state = self._cm_read_plug_state(refreshed)
            if self._cm_is_desired_plug_state(new_state, target_off):
                self._logger.info(
                    f"[PowerCycle] '{plug_name}' confirmed {target_label} (state='{new_state}').")
                return True
            # Fallback: if state did not toggle yet, try element.click() or a second coordinate tap
            self._logger.info(
                f"[PowerCycle] '{plug_name}' state is still '{new_state}' after first tap; retrying click..."
            )
            try:
                refreshed.click()
                tapped = True
            except WebDriverException:
                try:
                    r2 = refreshed.rect
                    self.driver.execute_script(
                        "mobile: tap",
                        {"x": int(r2["x"] + r2["width"] / 2), "y": int(r2["y"] + r2["height"] / 2)},
                    )
                    tapped = True
                except WebDriverException:
                    pass
            time.sleep(1.2)
            if not self._cm_ensure_all_devices_ready():
                return False
            refreshed2 = self._cm_locate_plug_tile(plug_name)
            if refreshed2 is not None:
                final_state = self._cm_read_plug_state(refreshed2)
                if self._cm_is_desired_plug_state(final_state, target_off):
                    self._logger.info(
                        f"[PowerCycle] '{plug_name}' confirmed {target_label} on retry (state='{final_state}')."
                    )
                    return True
                self._logger.warning(
                    f"[PowerCycle] '{plug_name}' state after retry is '{final_state}' (expected {target_label})."
                )
        return tapped

    def _cm_power_cycle_one(self, plug_name: str, off_wait: float, on_wait: float) -> bool:
        """Turn a plug OFF (if not already), wait, then turn it back ON (with crash/lock recovery)."""
        if not self._cm_ensure_all_devices_ready():
            return False
        tile = self._cm_locate_plug_tile(plug_name)
        if tile is None:
            self._logger.warning(f"[PowerCycle] Could not locate '{plug_name}'. Skipping.")
            return False
        state = self._cm_read_plug_state(tile)
        self._logger.info(f"[PowerCycle] '{plug_name}' initial state: '{state or 'unknown'}'")
        try:
            if state not in self.PLUG_OFF_VALUES:
                self._logger.info(f"[PowerCycle] Turning OFF '{plug_name}', waiting {off_wait}s...")
                if not self._cm_tap_plug_tile(tile, plug_name, target_off=True):
                    return False
                time.sleep(off_wait)
            if not self._cm_ensure_all_devices_ready():
                return False
            tile = self._cm_locate_plug_tile(plug_name)
            if tile is None:
                self._logger.warning(
                    f"[PowerCycle] Could not re-locate '{plug_name}' before turning ON.")
                return False
            curr_state = self._cm_read_plug_state(tile)
            if curr_state in self.PLUG_ON_VALUES:
                self._logger.info(
                    f"[PowerCycle] '{plug_name}' is already ON after recovery; tapping OFF -> ON to complete cycle..."
                )
                if not self._cm_tap_plug_tile(tile, plug_name, target_off=True):
                    return False
                time.sleep(off_wait)
                if not self._cm_ensure_all_devices_ready():
                    return False
                tile = self._cm_locate_plug_tile(plug_name)
                if tile is None:
                    return False
            self._logger.info(
                f"[PowerCycle] Turning ON '{plug_name}', waiting {on_wait}s for boot...")
            if not self._cm_tap_plug_tile(tile, plug_name, target_off=False):
                return False
            time.sleep(on_wait)
            return True
        except WebDriverException as e:
            self._logger.error(f"[PowerCycle] Failed power-cycling '{plug_name}': {e}")
            return False

    def power_cycle_smart_plug(
            self,
            keywords: Optional[Sequence[str]] = None,
            off_wait: float = 5.0,
            on_wait: float = 8.0,
    ) -> bool:
        """Restart GHA, then power-cycle every plug/outlet device on the Devices tab.
        Returns:
            True if all discovered plugs were power-cycled successfully.
        """
        keywords = tuple(keywords or self.DEFAULT_PLUG_KEYWORDS)
        self._logger.info("[PowerCycle] Restarting GHA and navigating to Devices tab...")
        self.stop_gha()
        time.sleep(2.0)
        self.start_gha()
        time.sleep(3.0)
        GHATabPage(self.driver).go_to_tab(constants.TAB.DEVICES)
        time.sleep(2.0)
        plugs = self._cm_discover_plugs(keywords)
        if not plugs:
            self._logger.error(
                f"[PowerCycle] No smart plug/outlet found matching {list(keywords)}.")
            return False
        self._logger.info(
            f"[PowerCycle] Found {len(plugs)} plug(s): {plugs}. Power-cycling sequentially...")
        results = []
        for idx, name in enumerate(plugs, start=1):
            self._logger.info(f"[PowerCycle] [{idx}/{len(plugs)}] Processing '{name}'...")
            results.append(self._cm_power_cycle_one(name, off_wait, on_wait))
        self._logger.info(f"[PowerCycle] Finished: {sum(results)}/{len(plugs)} succeeded.")
        return all(results)

    def _cm_get_headline(self) -> str:
        elem = self._cm_find_displayed(*self.HEADLINE_LOCATOR)
        return self._cm_read_text(elem) if elem is not None else ""

    def _cm_on_watch_setup_video(self, _headline: str) -> bool:
        self._logger.info("Detected 'Watch setup video'. Clicking Next/Done...")
        GHAWatchSetupVideoPage(self.driver).handle_watch_setup_video_page_process()
        time.sleep(1.0)
        return False

    def _cm_on_connect_google_account(self, _headline: str) -> bool:
        self._logger.info("Detected 'Connect device to Google Account'. Clicking I agree...")
        GHAConnectDeviceToGoogleAccountPage(self.driver).click_i_agree_btn()
        time.sleep(1.0)
        return False

    def _cm_on_where_is_this_device(self, room_name: str) -> bool:
        self._logger.info(f"Reached room selection. Selecting room '{room_name}'...")
        try:
            GHAWhereIsThisDevicePage(self.driver).select_room_or_add_custom(room_name=room_name)
        except Exception as e:
            self._logger.warning(
                f"select_room_or_add_custom error: {e}. Falling back to first visible cell...")
            cells = self._cm_find_all(AppiumBy.IOS_CLASS_CHAIN,
                                      '**/XCUIElementTypeCell[`visible == 1`]')
            if cells:
                cells[0].click()
            self._cm_click_displayed(AppiumBy.ACCESSIBILITY_ID,
                                     constants.GHA_NEXT_BTN_ACCESSIBILITY_ID)
        time.sleep(1.0)
        return False

    def _cm_on_device_connected(self, _headline: str) -> bool:
        self._logger.info("Device connected! Clicking Done...")
        try:
            GHADeviceConnectedPage(self.driver).click_done_btn()
        except Exception:
            self._cm_click_displayed(AppiumBy.ACCESSIBILITY_ID,
                                     constants.GHA_DONE_BTN_ACCESSIBILITY_ID)
        return False

    def _cm_on_camera_activated(self, headline: str) -> bool:
        self._logger.info(f"Device paired and transitioned to '{headline}'!")
        GHACameraActivatedPage(self.driver).handle_camera_activated_page_process()
        return False

    def _cm_on_live_video(self, headline: str) -> bool:
        self._logger.info(f"Device paired and transitioned to '{headline}'!")
        GHAYouShouldNowSeeLiveVideoPage(
            self.driver).handle_you_should_now_see_live_video_page_process()
        return True

    def _cm_on_uncertified_warning(self, headline: str) -> bool:
        self._logger.warning(f"Encountered warning: '{headline}'. Clicking 'Set up anyway'...")
        if not self._cm_click_displayed(AppiumBy.ACCESSIBILITY_ID, "Set up anyway"):
            self._cm_click_displayed(AppiumBy.ACCESSIBILITY_ID, "Exit")
        time.sleep(2.0)
        return False

    def _cm_build_headline_handlers(self, room_name: str) -> List[
        Tuple[Tuple[str, ...], HeadlineHandler]]:
        """Ordered (keywords, handler) table; the first matching entry wins."""
        return [
            (("Watch setup video",), self._cm_on_watch_setup_video),
            (("Connect this device to your Google Account",), self._cm_on_connect_google_account),
            (("Where is this device",), lambda _h: self._cm_on_where_is_this_device(room_name)),
            (("Device connected", "Device added"), self._cm_on_device_connected),
            (("Camera activated",), self._cm_on_camera_activated),
            (("You should now see live video",), self._cm_on_live_video),
            (("Uncertified", "Service failure"), self._cm_on_uncertified_warning),
        ]

    def complete_commissioning_and_pairing_flow(
            self, device_name: str, room_name: str = "Attic", timeout: float = 600
    ) -> bool:
        """State machine handling Apple sheets, GHA loading, room setup, and completion.
        If the flow hits `timeout`, restarts GHA and checks the 'All devices' page:
        - If the device is in Home and ONLINE (e.g. GHA crashed at the end of commissioning),
          continues the test flow (returns True).
        - If the device is in Home but OFFLINE, removes the device from Home, resets the hardware,
          and raises the commissioning timeout AssertionError.
        - If the device is not in Home, resets the hardware and raises the commissioning timeout
          AssertionError.
        """
        self._logger.info(
            f"[Commissioning] Starting flow for '{device_name}' (timeout {int(timeout)}s)...")
        self._cm_reset_device_name = device_name
        self._cm_resolved_tile_name = device_name
        self._cm_last_apple_card_title: str = ""
        self._cm_apple_failure_title: str = ""
        self._cm_named_in_current_flow: bool = False
        self._cm_recovered_online_on_timeout: bool = False
        try:
            setattr(self.driver, "_commissioned_via_timeout_online", False)
        except Exception:
            pass
        handlers = self._cm_build_headline_handlers(room_name)
        start_time = time.time()
        apple_sheet_active = False
        try:
            while time.time() - start_time < timeout:
                if self.handle_apple_commissioning_sheet(device_name):
                    apple_sheet_active = True
                    continue
                if apple_sheet_active:
                    self._logger.info(
                        "[Commissioning] Apple sheet dismissed. Back in GHA foreground.")
                    apple_sheet_active = False
                    time.sleep(1.0)
                headline = self._cm_get_headline()
                if not headline:
                    time.sleep(self.CM_POLL_INTERVAL)
                    continue
                self._logger.info(f"[{int(time.time() - start_time)}s] GHA Headline: '{headline}'")
                if _contains_any(headline, self.FAILURE_KEYWORDS):
                    self._logger.error(f"[Commissioning] Failure headline detected: '{headline}'")
                    is_paired_offline = _contains_any(headline,
                                                      self.PAIRED_OFFLINE_FAILURE_KEYWORDS)
                    if is_paired_offline:
                        self._logger.warning(
                            f"[Commissioning] '{headline}' indicates device '{device_name}' was already added "
                            "to Home (offline). Removing device from Home before running recovery..."
                        )
                    apple_ctx = self._cm_format_apple_sheet_context()
                    raise AssertionError(
                        self._cm_recover(
                            f"Commissioning failed with headline '{headline}'{apple_ctx}",
                            remove_paired_device=is_paired_offline,
                        )
                    )
                if _contains_any(headline, self.PROGRESS_KEYWORDS):
                    self._logger.info(f"Waiting for GHA background progress: '{headline}'...")
                    time.sleep(self.CM_PROGRESS_INTERVAL)
                    continue
                handler = next((h for kws, h in handlers if _contains_any(headline, kws)), None)
                if handler is None:
                    time.sleep(self.CM_POLL_INTERVAL)
                    continue
                if handler(headline):
                    self._logger.info("[Commissioning] Flow completed successfully..")
                    return True
            self._logger.error(f"[Commissioning] Flow timed out after {int(timeout)}s!")
            apple_ctx = self._cm_format_apple_sheet_context()
            timeout_reason = f"Commissioning timed out after {int(timeout)}s{apple_ctx}"
            if hasattr(BasePage, "capture_failure_screenshot"):
                BasePage.capture_failure_screenshot(
                    self.driver, reason=timeout_reason, force=False, lock=False
                )
            device_status = self._cm_check_device_status_on_all_devices(device_name)
            if device_status == "online":
                self._logger.warning(
                    f"[Commissioning] '{device_name}' exists in Home on 'All devices' and is ONLINE "
                    f"after {int(timeout)}s timeout (GHA likely crashed near the end of commissioning). "
                    "Continuing test flow..."
                )
                if hasattr(BasePage, "reset_failure_screenshot_state"):
                    BasePage.reset_failure_screenshot_state(self.driver, remove_existing=True)
                self._cm_mark_timeout_online_recovery()
                return True
            if device_status == "offline":
                self._logger.error(
                    f"[Commissioning] '{device_name}' exists in Home on 'All devices' after "
                    f"{int(timeout)}s timeout, but is OFFLINE. Removing device and reporting timeout..."
                )
                if hasattr(BasePage, "capture_failure_screenshot"):
                    BasePage.capture_failure_screenshot(
                        self.driver,
                        reason=f"{timeout_reason} (device offline on All devices)",
                        force=True,
                        lock=True,
                    )
                raise AssertionError(
                    self._cm_recover(timeout_reason, remove_paired_device=True)
                )
            self._logger.error(
                f"[Commissioning] '{device_name}' was not found on 'All devices' after "
                f"{int(timeout)}s timeout. Reporting commissioning timeout..."
            )
            raise AssertionError(
                self._cm_recover(timeout_reason, remove_paired_device=False)
            )
        except _CMAppleSheetFailure as e:
            gha_headline = self._cm_get_headline()
            if gha_headline and _contains_any(gha_headline, self.FAILURE_KEYWORDS):
                reason_msg = (
                    f"Commissioning failed with headline '{gha_headline}' | "
                    f"Apple sheet failed with '{e.card_title}'"
                )
            else:
                reason_msg = e.reason
            raise AssertionError(self._cm_recover(reason_msg)) from None
        except AssertionError:
            raise
        except Exception as e:
            self._logger.error(f"[Commissioning] Unexpected exception: {e}")
            self._cm_recover(f"Unexpected exception: {e}")
            raise AssertionError(f"Commissioning flow failed with unexpected exception: {e}") from e
