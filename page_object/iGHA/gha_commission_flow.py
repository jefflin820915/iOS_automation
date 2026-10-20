"""Page object for Matter device commissioning and iOS system sheets with StaleElement resilience."""
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
    PROGRESS_KEYWORDS = (
        "Adding device", "Getting your device ready", "Next, your device will be added",
        "Connecting",
        "Setting up", "Activating camera", "Downloading update", "Update finished",
    )
    DEFAULT_PLUG_KEYWORDS = ("Eve", "Eve Energy Plug", "Eve Energy", "Eve Energy plug")
    PLUG_ON_VALUES = ("on", "1", "true")
    PLUG_OFF_VALUES = ("off", "0", "false")
    CM_POLL_INTERVAL = 1.5
    CM_PROGRESS_INTERVAL = 2.5
    CM_REMOVE_ATTEMPTS = 2

    @contextmanager
    def _cm_no_implicit_wait(self) -> Iterator[None]:
        """Temporarily disable implicit wait and always restore the previous value."""
        try:
            previous = self.driver.timeouts.implicit_wait
        except Exception:
            previous = getattr(constants, "DEFAULT_IMPLICIT_WAIT", 10.0)
        self.driver.implicitly_wait(0)
        try:
            yield
        finally:
            try:
                self.driver.implicitly_wait(previous)
            except WebDriverException:
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
                text = (elem.get_attribute(attr) or "").strip()
                if text:
                    return text
            return (elem.text or "").strip()
        except WebDriverException:
            return ""

    def _cm_is_gha_foreground(self) -> bool:
        try:
            return self.driver.query_app_state(
                constants.GHA_BUNDLE_ID) == constants.APP_STATE_FOREGROUND
        except WebDriverException as e:
            self._logger.error(f"Failed to query GHA app state: {e}")
            return False

    def stop_gha(self) -> bool:
        """Terminate the GHA application."""
        try:
            if self.driver.query_app_state(
                    constants.GHA_BUNDLE_ID) == constants.APP_STATE_NOT_RUNNING:
                self._logger.info("GHA is not running.")
            else:
                self.driver.terminate_app(constants.GHA_BUNDLE_ID)
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
        self._logger.info("Starting Google Home App on iOS...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.driver.activate_app(constants.GHA_BUNDLE_ID)
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
        """Dismiss the failed Apple sheet and signal the main flow (which recovers and raises)."""
        self._logger.error(f"[AppleSheet] Reported failure: '{card_title}'")
        self._cm_apple_failure_title = card_title
        self._cm_last_apple_card_title = card_title
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
                if not GHASettingsPage(self.driver).open_device_settings(device_name=device_name):
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
        """Dismiss commissioning screens, optionally remove paired offline device, and reset the device. Never raises.
        Reset method comes from DeviceResetUtils: adb factory reset for configured devices
        (e.g. 'Ref2 Battery Camera'), smart plug power-cycle for every other device.  [DEVICE RESET]
        Returns:
            The FATAL error message. The CALLER must raise it, so that the innermost
            page_object frame (used as Failure Stage) is the caller, not this helper.
        """
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

    def _cm_tile_identity(self, tile: WebElement) -> str:
        """Human-readable device name of a tile (title text > first part of label > name)."""
        titles = self._cm_find_all(*self.DEVICE_TILE_TITLE, root=tile)
        if titles:
            title = self._cm_read_text(titles[0], ("value",))
            if title:
                return title
        label = self._cm_read_text(tile, ("label", "name", "value"))
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

    def _cm_all_tile_candidates(self) -> List[WebElement]:
        """Return all device tile elements across both legacy GHA (deviceTile) and new GHA (XCUIElementTypeOther)."""
        legacy = self._cm_find_all(*self.DEVICE_TILE) + self._cm_find_all(*self.DEVICE_TILE_CELL)
        if legacy:
            return legacy
        others = [
            elem for elem in self._cm_find_all(*self.DEVICE_TILE_OTHER)
            if self._cm_is_valid_other_tile(elem)
        ]
        if others:
            return others
        return self._cm_find_all(*self.DEVICE_TILE_STATIC_TEXT)

    def _cm_is_plug(self, elem: WebElement, keywords: Sequence[str]) -> bool:
        text = " ".join(self._cm_read_text(elem, (attr,)) for attr in ("label", "value", "name"))
        return _contains_any(text, keywords)

    def _cm_discover_plugs(self, keywords: Sequence[str]) -> List[str]:
        """Collect unique names of plug/outlet tiles on the Devices / All devices view (scrolls once if needed)."""
        found: List[str] = []
        for attempt in range(2):
            candidates = self._cm_all_tile_candidates()
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
        """Freshly locate a plug tile by name across legacy and new GHA UI (avoids stale references)."""
        target = target_name.lower()
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
        for other in self._cm_find_all(*self.DEVICE_TILE_OTHER):
            try:
                if not self._cm_is_valid_other_tile(other):
                    continue
                if target in self._cm_tile_identity(other).lower() or \
                        target in self._cm_read_text(other, ("label", "name")).lower():
                    return other
            except WebDriverException:
                continue
        for st in self._cm_find_all(*self.DEVICE_TILE_STATIC_TEXT):
            try:
                if target in self._cm_read_text(st, ("label", "name", "value")).lower():
                    return st
            except WebDriverException:
                continue
        return None

    def _cm_read_plug_state(self, tile: WebElement) -> str:
        """Read 'on' / 'off' state from legacy value attribute, 'Name, On/Off' label suffix, or child StaticText."""
        val = self._cm_read_text(tile, ("value",)).lower()
        if val in self.PLUG_ON_VALUES or val in self.PLUG_OFF_VALUES:
            return val
        label_or_name = self._cm_read_text(tile, ("label", "name"))
        if "," in label_or_name:
            suffix = label_or_name.rsplit(",", 1)[-1].strip().lower()
            if suffix:
                return suffix
        for child in self._cm_find_all(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText", root=tile):
            child_txt = self._cm_read_text(child, ("value", "label", "name")).lower()
            if child_txt in self.PLUG_ON_VALUES or child_txt in self.PLUG_OFF_VALUES or child_txt == "offline":
                return child_txt
        return val

    def _cm_tap_plug_tile(self, tile: WebElement, plug_name: str, target_off: bool) -> bool:
        """Click the plug tile; if XCUIElementTypeOther has accessible=false and click is a no-op, tap center coords."""
        clicked = False
        try:
            tile.click()
            clicked = True
        except WebDriverException:
            pass
        if clicked:
            time.sleep(1.2)
            refreshed = self._cm_locate_plug_tile(plug_name)
            if refreshed is not None:
                new_state = self._cm_read_plug_state(refreshed)
                if target_off and new_state in self.PLUG_OFF_VALUES:
                    return True
                if not target_off and new_state in self.PLUG_ON_VALUES:
                    return True
            else:
                return True
        # Fallback: coordinate tap at the center of the tile rect (needed when accessible == false).
        target_elem = self._cm_locate_plug_tile(plug_name) or tile
        try:
            rect = target_elem.rect
            cx = int(rect["x"] + rect["width"] / 2)
            cy = int(rect["y"] + rect["height"] / 2)
            self._logger.info(f"[PowerCycle] Coordinate-tapping '{plug_name}' at ({cx}, {cy})...")
            self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
            return True
        except WebDriverException as e:
            self._logger.error(f"[PowerCycle] Coordinate tap failed for '{plug_name}': {e}")
            return clicked

    def _cm_power_cycle_one(self, plug_name: str, off_wait: float, on_wait: float) -> bool:
        """Turn a plug OFF (if not already), wait, then turn it back ON."""
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
                tile = self._cm_locate_plug_tile(plug_name) or tile
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
        Args:
            device_name: Desired device name to fill in the Apple sheet.
            room_name: Target room for 'Where is this device?'.
            timeout: Total timeout in seconds.
        Returns:
            True when the live video page is reached.
        Raises:
            AssertionError: On failure headline, Apple sheet failure, timeout, or unexpected error
                (after dismissing screens, removing paired offline device if applicable, and
                resetting the device). All final raises happen in THIS method so the reported
                Failure Stage is COMPLETE_COMMISSIONING_AND_PAIRING_FLOW.
        """
        self._logger.info(
            f"[Commissioning] Starting flow for '{device_name}' (timeout {int(timeout)}s)...")
        self._cm_reset_device_name = device_name
        self._cm_last_apple_card_title: str = ""
        self._cm_apple_failure_title: str = ""
        self._cm_named_in_current_flow: bool = False
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
            raise AssertionError(
                self._cm_recover(f"Commissioning timed out after {int(timeout)}s{apple_ctx}"))
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
