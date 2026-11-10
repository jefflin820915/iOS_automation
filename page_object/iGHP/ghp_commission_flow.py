"""Page object for GHP Sample App Matter commissioning, OOBE OTA verification, and Smart Plug power-cycle."""

import contextlib
import re
import time
from typing import Any, Iterator, List, Optional, Sequence, Set, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException

from common import constants
from common.base_page import BasePage
from page_object.iGHP.ghp_device_page import GHPDevicePage, get_ghp_bundle_id
from utils import logging_utils
from utils.camera_reset_utils import DeviceResetUtils

IOS_PREDICATE_BY = getattr(AppiumBy, "IOS_PREDICATE", "-ios predicate string")
IOS_CLASS_CHAIN_BY = getattr(AppiumBy, "IOS_CLASS_CHAIN", "-ios class chain")


def _contains_any(text: str, keywords: Sequence[str]) -> bool:
    low = (text or "").lower()
    return any(kw.lower() in low for kw in keywords)


class _GHPApiAppleSheetFailure(AssertionError):
    """Internal sentinel raised when Apple's Matter sheet displays a terminal failure card.

    Caught in `complete_commissioning_and_pairing_flow` and re-raised there as a plain
    `AssertionError` so `extract_failure_stage` attributes it to
    `COMPLETE_COMMISSIONING_AND_PAIRING_FLOW`.
    """

    def __init__(self, reason: str, card_title: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.card_title = card_title or reason


class GHPCommissioningPageObject(BasePage):
    """Unified handler for GHP '+' menu, Apple Matter setup code & sheets, Camera OOBE OTA, and Plug reset."""

    CM_POLL_INTERVAL: float = 1.0
    CM_OTA_POLL_INTERVAL: float = 2.0
    CM_OTA_ZERO_PERCENT_TIMEOUT: float = 20.0
    CM_OTA_DEFAULT_TIMEOUT: float = 600.0
    CM_OTA_EMPTY_HEADLINE_TOLERANCE: int = 3
    CM_POST_APPLE_OOBE_GRACE_SECONDS: float = 6.0

    DEFAULT_PLUG_KEYWORDS: Tuple[str, ...] = ("Plug", "Outlet", "Socket")
    PLUG_ON_VALUES: Tuple[str, ...] = ("1", "on", "true")
    PLUG_OFF_VALUES: Tuple[str, ...] = ("0", "off", "false")

    APPLE_FAILURE_KEYWORDS: Tuple[str, ...] = (
        "Unable to Add Accessory",
        "Unable to Add",
        "Pairing Failed",
        "Setup Failed",
        "Accessory Not Found",
        "Accessory Not Reachable",
        "Accessory is Not Reachable",
        "Not Reachable",
        "Couldn't Add",
        "Couldn’t Add",
        "Could Not Add",
        "Failed to Add",
        "Failed to",
        "Incorrect Setup Code",
        "Invalid Setup Code",
        "Security check failed",
        "Cannot Be Used",
        "Can't Be Used",
        "Can’t Be Used",
        "Already Added",
    )

    # Benign iOS / Apple HomeUIService modal alert buttons to accept automatically
    # (e.g. 'Additional Setup Required' -> 'OK', 'Uncertified Accessory' -> 'Add Anyway',
    # Local Network / Bluetooth permission -> 'Allow').
    # NOTE: Never include 'Continue' or 'Done' here because Apple PRXCard sheets themselves
    # have type == XCUIElementTypeAlert on iOS!
    SYSTEM_ALERT_ACCEPT_BUTTONS: Tuple[str, ...] = (
        "Add Anyway",
        "Set up anyway",
        "OK",
        "Ok",
        "Allow",
    )

    APPLE_OVERLAY_WINDOW_CHAIN: str = (
        '**/XCUIElementTypeWindow[`name == "SBTransientOverlayWindow" AND visible == 1`]'
    )
    APPLE_CARD_TITLE_CHAIN: str = (
        f"{APPLE_OVERLAY_WINDOW_CHAIN}/**/XCUIElementTypeTextView[`visible == 1`]"
    )
    APPLE_IGNORED_BUTTON_TITLES: Tuple[str, ...] = (
        "ok",
        "done",
        "cancel",
        "continue",
        "set up",
        "add anyway",
        "set up anyway",
        "allow",
        "don't allow",
        "don’t allow",
        "close",
    )

    GHP_FAILURE_KEYWORDS: Tuple[str, ...] = (
        "Commissioning failed",
        "Could not start commissioning",
        "Failed to mark configuration done",
        "Cannot add device on simulator",
    )

    OTA_KEYWORDS: Tuple[str, ...] = (
        "Software update",
        "Checking for update",
        "Preparing update",
        "Downloading update",
        "Downloading (",
        "Downloading",
        "Installing update",
        "Installing",
        "Applying update",
        "Update finished",
        "Progress:",
    )

    OTA_FAILURE_KEYWORDS: Tuple[str, ...] = (
        "There may be a problem",
        "Update failed",
        "Unable to update",
        "Failed to update",
    )

    OOBE_ERROR_ALERT_PREDICATE: str = (
        'type IN {"XCUIElementTypeAlert", "XCUIElementTypeStaticText", "XCUIElementTypeTextView"} AND ('
        'label CONTAINS[c] "Stream removed" '
        'OR label CONTAINS[c] "NSPOSIXErrorDomain" '
        'OR label CONTAINS[c] "Socket is not connected" '
        'OR label CONTAINS[c] "Internal error encountered" '
        'OR value CONTAINS[c] "Stream removed" '
        'OR value CONTAINS[c] "NSPOSIXErrorDomain" '
        'OR value CONTAINS[c] "Internal error encountered")'
    )

    ALERT_OK_BTN_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND '
        '(name IN {"OK", "Ok", "Dismiss", "Close"} OR label IN {"OK", "Ok", "Dismiss", "Close"})'
    )

    OTA_PERCENT_PREDICATE: str = (
        'type IN {"XCUIElementTypeStaticText", "XCUIElementTypeProgressIndicator", "XCUIElementTypeOther"} '
        'AND (label CONTAINS "%" OR value CONTAINS "%" OR name CONTAINS "%")'
    )

    # '+' Add button and Fabric menu in StructureView
    TOP_LEFT_ADD_PREDICATE: str = (
        '(type IN {"XCUIElementTypeOther", "XCUIElementTypeButton"}) AND ('
        'name IN {"Add", "plus", "plus.diamond"} OR label IN {"Add", "plus"})'
    )
    ADD_3P_FABRIC_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND ('
        'name == "Add Device to Google & 3P Fabric" OR label == "Add Device to Google & 3P Fabric" '
        'OR name CONTAINS[c] "3P Fabric" OR label CONTAINS[c] "3P Fabric")'
    )
    ADD_GOOGLE_FABRIC_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND ('
        'name == "Add Device to Google Fabric" OR label == "Add Device to Google Fabric")'
    )

    # Apple Matter pairing-code entry screens
    MORE_OPTIONS_LINK_PREDICATE: str = (
        'type IN {"XCUIElementTypeLink", "XCUIElementTypeButton", "XCUIElementTypeStaticText", '
        '"XCUIElementTypeTextView"} AND ('
        'name CONTAINS[c] "Scan code or hold iPhone near the accessory" '
        'OR label CONTAINS[c] "Scan code or hold iPhone near the accessory" '
        'OR name CONTAINS[c] "More options" OR label CONTAINS[c] "More options")'
    )
    NOT_SHOWN_BTN_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND ('
        'name CONTAINS[c] "My Accessory" OR label CONTAINS[c] "My Accessory" '
        'OR name CONTAINS[c] "Shown Here" OR label CONTAINS[c] "Shown Here")'
    )
    ENTER_CODE_LINK_PREDICATE: str = (
        'type == "XCUIElementTypeLink" AND ('
        'name CONTAINS[c] "Enter code" OR label CONTAINS[c] "Enter code")'
    )
    ENTER_CODE_TEXTVIEW_PREDICATE: str = (
        'type IN {"XCUIElementTypeTextView", "XCUIElementTypeStaticText"} AND ('
        'value CONTAINS[c] "manually enter the setup code" '
        'OR label CONTAINS[c] "manually enter the setup code")'
    )
    SETUP_CODE_HEADER_PREDICATE: str = (
        'type IN {"XCUIElementTypeTextView", "XCUIElementTypeStaticText"} AND ('
        'name == "Setup Code" OR label == "Setup Code" '
        'OR label CONTAINS[c] "Enter the code found on the accessory")'
    )
    CONTINUE_BTN_PREDICATE: str = (
        'type == "XCUIElementTypeButton" AND (name == "Continue" OR label == "Continue")'
    )

    def __init__(self, driver: WebDriver, timeout: float = 10.0) -> None:
        self.APP_BUNDLE_ID = get_ghp_bundle_id()
        super().__init__(driver, timeout=timeout)
        self._logger = logging_utils.get_logger(__name__, "ghp_commission")
        self._cm_reset_device_name: str = ""
        self._cm_resolved_tile_name: str = ""
        self._cm_named_in_current_flow: bool = False
        self._cm_named_card_titles: Set[str] = set()
        self._cm_picker_preferred_method: str = ""
        self._cm_apple_done_clicked_at: float = 0.0
        self._cm_last_apple_card_title: str = ""
        self._cm_springboard_failure_title: str = ""

    @classmethod
    def _resolve_page(cls, ctx: Any) -> "GHPCommissioningPageObject":
        if isinstance(ctx, cls):
            return ctx
        existing = getattr(ctx, "ghpcommissioningpageobject", None)
        if isinstance(existing, cls):
            return existing
        session = getattr(ctx, "session", None)
        if session is not None and isinstance(
                getattr(session, "ghpcommissioningpageobject", None), cls
        ):
            return session.ghpcommissioningpageobject
        page = cls(ctx.driver)
        if session is not None:
            page.session = session
        return page

    @contextlib.contextmanager
    def _cm_fast_probe(self) -> Iterator[None]:
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

    def _cm_find_all(
            self, by: str, value: str, root: Optional[WebElement] = None
    ) -> List[WebElement]:
        target = root if root is not None else self.driver
        with self._cm_fast_probe():
            try:
                return list(target.find_elements(by, value))
            except WebDriverException:
                return []

    def _cm_find_displayed(
            self, by: str, value: str, allow_hidden: bool = False
    ) -> Optional[WebElement]:
        elems = self._cm_find_all(by, value)
        first_elem: Optional[WebElement] = None
        for el in elems:
            if first_elem is None:
                first_elem = el
            try:
                if el.is_displayed():
                    return el
            except (StaleElementReferenceException, WebDriverException):
                continue
        return first_elem if allow_hidden else None

    def _cm_read_text(
            self, elem: Optional[WebElement], attrs: Tuple[str, ...] = ("label", "name", "value")
    ) -> str:
        if elem is None:
            return ""
        for attr in attrs:
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

    def _cm_tap_center(self, elem: WebElement, desc: str = "element") -> bool:
        try:
            rect = elem.rect
            cx = int(rect["x"] + rect["width"] / 2)
            cy = int(rect["y"] + rect["height"] / 2)
            self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
            return True
        except WebDriverException as err:
            self._logger.debug(f"mobile: tap failed on {desc}: {err}")
            try:
                elem.click()
                return True
            except WebDriverException:
                return False

    def _cm_click_or_tap(self, elem: WebElement, desc: str = "element") -> bool:
        rect = None
        try:
            rect = elem.rect
        except WebDriverException:
            rect = None
        try:
            elem.click()
            return True
        except WebDriverException as err:
            self._logger.debug(f"click() failed on {desc} ({err}); falling back to mobile: tap...")
        if rect:
            cx = int(rect["x"] + rect["width"] / 2)
            cy = int(rect["y"] + rect["height"] / 2)
            try:
                self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                return True
            except WebDriverException:
                pass
        return False

    # -------------------------------------------------------------------------
    # 1. Click '+' and select 'Add Device to Google & 3P Fabric'
    # -------------------------------------------------------------------------
    def _cm_open_fabric_menu_and_select(self, prefer_3p: bool = True) -> Optional[str]:
        """Internal helper: returns None on success, or an error description string on failure."""
        GHPDevicePage._resolve_page(self).go_to_tab("Devices")
        for attempt in range(1, 4):
            btn_3p = self._cm_find_displayed(IOS_PREDICATE_BY, self.ADD_3P_FABRIC_PREDICATE)
            btn_1p = self._cm_find_displayed(IOS_PREDICATE_BY, self.ADD_GOOGLE_FABRIC_PREDICATE)
            if btn_3p is None and btn_1p is None:
                add_el = self._cm_find_displayed(
                    IOS_PREDICATE_BY, self.TOP_LEFT_ADD_PREDICATE, allow_hidden=True
                )
                if add_el is not None:
                    self._logger.info(f"Tapping top-left '+' (Add) button (attempt {attempt}/3)...")
                    if not self._cm_tap_center(add_el, desc="GHP '+' Add button"):
                        self.driver.execute_script("mobile: tap", {"x": 38, "y": 69})
                else:
                    self._logger.info(
                        f"'+' element not exposed as accessible; tapping (38, 69) (attempt {attempt}/3)..."
                    )
                    self.driver.execute_script("mobile: tap", {"x": 38, "y": 69})

                menu_deadline = time.time() + 4.0
                while time.time() < menu_deadline:
                    btn_3p = self._cm_find_displayed(IOS_PREDICATE_BY, self.ADD_3P_FABRIC_PREDICATE)
                    btn_1p = self._cm_find_displayed(IOS_PREDICATE_BY,
                                                     self.ADD_GOOGLE_FABRIC_PREDICATE)
                    if btn_3p is not None or btn_1p is not None:
                        break
                    time.sleep(0.3)

            target_btn = (btn_3p or btn_1p) if prefer_3p else (btn_1p or btn_3p)
            if target_btn is not None:
                chosen_label = self._cm_read_text(target_btn) or "Add Device to Fabric"
                self._logger.info(f"Clicking fabric menu option: '{chosen_label}'...")
                self._cm_click_or_tap(target_btn, desc=chosen_label)
                time.sleep(1.5)

                # If device is < iOS 17.6, GHP shows snackbar 'iOS 17.6+ required to add 3P Fabric.'
                ios176_warn = self._cm_find_displayed(
                    IOS_PREDICATE_BY,
                    'type == "XCUIElementTypeStaticText" AND label CONTAINS[c] "iOS 17.6+ required"',
                )
                if ios176_warn is not None and prefer_3p:
                    self._logger.warning(
                        "Detected 'iOS 17.6+ required to add 3P Fabric'; falling back to 'Add Device to Google Fabric'..."
                    )
                    prefer_3p = False
                    continue
                return None

        return "Failed to open '+' menu and click 'Add Device to Google & 3P Fabric' in GHP."

    def click_add_device_to_fabric(self, prefer_3p: bool = True) -> bool:
        """Tap '+' on the GHP Devices tab and select 'Add Device to Google & 3P Fabric'."""
        page = GHPCommissioningPageObject._resolve_page(self)
        err = page._cm_open_fabric_menu_and_select(prefer_3p=prefer_3p)
        if err is not None:
            page._logger.error(err)
            BasePage.capture_failure_screenshot(page.driver, reason=err, force=False, lock=True)
            raise AssertionError(err)
        return True

    # -------------------------------------------------------------------------
    # 2. Apple Matter Setup Code Entry:
    #    'Scan code or hold iPhone near the accessory. More options…'
    #    -> "My Accessory Isn't Shown Here" -> "Enter code…" -> Setup Code + Continue
    # -------------------------------------------------------------------------
    def _cm_tap_more_options_link(self, elem: WebElement, attempt: int) -> None:
        """Click/tap 'Scan code or hold iPhone near the accessory. More options…' inline link."""
        try:
            rect = elem.rect
        except WebDriverException:
            rect = None

        if attempt == 1:
            try:
                elem.click()
                return
            except WebDriverException:
                pass

        if rect:
            # 'More options…' sits on the second line of the centered subtitle link (y ~ 75% of rect)
            offsets = (
                (0.62, 0.76),
                (0.50, 0.76),
                (0.72, 0.76),
                (0.50, 0.50),
            )
            rx, ry = offsets[(attempt - 1) % len(offsets)]
            tx = int(rect["x"] + rect["width"] * rx)
            ty = int(rect["y"] + rect["height"] * ry)
            self._logger.info(
                f"[PairingCode] Tapping 'More options…' link at ({tx}, {ty}) (attempt {attempt})..."
            )
            try:
                self.driver.execute_script("mobile: tap", {"x": tx, "y": ty})
                return
            except WebDriverException:
                pass
        self._cm_click_or_tap(elem, desc="More options…")

    def _cm_type_setup_code_digits(self, text_field: WebElement, digits: str) -> bool:
        """Enter setup code digits into Apple's Setup Code field, with digit-keypad tap fallback."""
        self._cm_click_or_tap(text_field, desc="Setup Code TextField")
        time.sleep(0.4)
        typed_ok = False
        try:
            text_field.send_keys(digits)
            time.sleep(0.6)
            current_val = re.sub(r"\D", "", self._cm_read_text(text_field, ("value", "label")))
            cont_btn = self._cm_find_displayed(IOS_PREDICATE_BY, self.CONTINUE_BTN_PREDICATE)
            cont_enabled = (
                    cont_btn is not None
                    and str(cont_btn.get_attribute("enabled") or "").lower() == "true"
            )
            if cont_enabled or len(current_val) >= min(8, len(digits)):
                typed_ok = True
        except WebDriverException as err:
            self._logger.debug(f"[PairingCode] send_keys failed on Setup Code field: {err}")

        if not typed_ok:
            self._logger.info(
                "[PairingCode] Typing setup code via on-screen numeric keypad buttons..."
            )
            try:
                text_field.clear()
            except WebDriverException:
                pass
            for ch in digits:
                btn = self._cm_find_displayed(
                    IOS_PREDICATE_BY,
                    f'type == "XCUIElementTypeButton" AND (name == "{ch}" OR label == "{ch}")',
                )
                if btn is None:
                    return False
                self._cm_click_or_tap(btn, desc=f"Keypad '{ch}'")
                time.sleep(0.08)
        return True

    def _cm_enter_pairing_code_steps(self, pairing_code: str, timeout: float = 45.0) -> Optional[
        str]:
        """Walk Apple HomeUIService sheet from 'Add Accessory' to submitting 'Setup Code'."""
        digits = "".join(ch for ch in str(pairing_code or "") if ch.isdigit())
        if not digits:
            digits = str(pairing_code or "").strip()
        if not digits:
            return "Pairing code is empty; please pass --pairing_code / -p."

        self._logger.info(
            f"[PairingCode] Navigating Apple sheet to enter pairing code (digits={len(digits)})..."
        )
        deadline = time.time() + timeout
        more_options_clicks = 0
        not_shown_clicks = 0
        enter_code_clicks = 0

        while time.time() < deadline:
            # Check if Apple sheet immediately surfaced an error card
            apple_err = self._cm_detect_apple_failure_title()
            if apple_err:
                return f"Apple sheet reported failure while entering setup code: '{apple_err}'"

            # Accept any benign iOS system alert (e.g. Local Network / Bluetooth 'Allow' / 'OK',
            # or 'Additional Setup Required' -> 'OK') before inspecting cards underneath
            if self._cm_handle_apple_system_alert():
                time.sleep(0.8)
                continue

            apple_err = self._cm_detect_apple_failure_title()
            if apple_err:
                return f"Apple sheet reported failure while entering setup code: '{apple_err}'"

            # Screen 4: 'Setup Code' screen with XCUIElementTypeTextField + 'Continue'
            setup_hdr = self._cm_find_displayed(
                IOS_PREDICATE_BY, self.SETUP_CODE_HEADER_PREDICATE, allow_hidden=True
            )
            if setup_hdr is not None:
                fields = self._cm_find_all(AppiumBy.CLASS_NAME, "XCUIElementTypeTextField")
                text_field = fields[0] if fields else None
                if text_field is not None:
                    self._logger.info(
                        "[PairingCode] Reached 'Setup Code' card. Entering pairing code...")
                    if not self._cm_type_setup_code_digits(text_field, digits):
                        return "Failed to enter digits into Apple 'Setup Code' TextField."
                    time.sleep(0.5)
                    cont_btn = self._cm_find_displayed(
                        IOS_PREDICATE_BY, self.CONTINUE_BTN_PREDICATE, allow_hidden=True
                    )
                    if cont_btn is None:
                        return "Entered setup code, but 'Continue' button was not found on 'Setup Code' card."
                    self._logger.info("[PairingCode] Clicking 'Continue' on 'Setup Code' card...")
                    self._cm_click_or_tap(cont_btn, desc="Setup Code Continue")

                    # Confirm transition away from Setup Code, accept 'Additional Setup Required' -> 'OK'
                    # (triggered by 21-digit custom-flow pairing codes), or catch immediate invalid code error.
                    submit_deadline = time.time() + 12.0
                    spinner_started_at: Optional[float] = None
                    while time.time() < submit_deadline:
                        err_after = self._cm_detect_apple_failure_title()
                        if err_after:
                            return f"Apple Setup Code rejected or failed: '{err_after}'"

                        if self._cm_handle_apple_system_alert():
                            self._logger.info(
                                "[PairingCode] Accepted system alert (e.g. 'Additional Setup Required' -> 'OK') "
                                "after submitting Setup Code."
                            )
                            time.sleep(1.0)
                            self._cm_handle_apple_system_alert()
                            return None

                        err_after = self._cm_detect_apple_failure_title()
                        if err_after:
                            return f"Apple Setup Code rejected or failed: '{err_after}'"

                        if (
                                self._cm_find_displayed(
                                    IOS_PREDICATE_BY, self.SETUP_CODE_HEADER_PREDICATE
                                )
                                is None
                        ):
                            self._logger.info(
                                "[PairingCode] Pairing code submitted; left 'Setup Code' card."
                            )
                            return None

                        # When Apple accepts 'Continue', the bottom 'Continue' button turns into a spinner
                        # while the 'Setup Code' card stays visible during BLE discovery (or right before
                        # 'Additional Setup Required' animates in). Give 2.5s for any modal alert to appear.
                        cont_still = self._cm_find_displayed(
                            IOS_PREDICATE_BY, self.CONTINUE_BTN_PREDICATE
                        )
                        if cont_still is None:
                            if spinner_started_at is None:
                                spinner_started_at = time.time()
                            elif (time.time() - spinner_started_at) >= 2.5:
                                self._logger.info(
                                    "[PairingCode] 'Setup Code' submitted (spinner active); "
                                    "handing off to Apple sheet handler."
                                )
                                return None

                        time.sleep(0.4)

                    # Only retry tapping 'Continue' if 'Continue' is still visible and no alert is open
                    cont_retry = self._cm_find_displayed(
                        IOS_PREDICATE_BY, self.CONTINUE_BTN_PREDICATE
                    )
                    if cont_retry is not None:
                        self._cm_tap_center(cont_retry, desc="Setup Code Continue retry")
                        time.sleep(1.2)
                        self._cm_handle_apple_system_alert()
                    return None

            # Screen 3: 'Accessory Setup Help' -> 'Enter code…' (accessible=false XCUIElementTypeLink)
            enter_link = self._cm_find_displayed(
                IOS_PREDICATE_BY, self.ENTER_CODE_LINK_PREDICATE, allow_hidden=True
            )
            if enter_link is not None:
                enter_code_clicks += 1
                self._logger.info(
                    f"[PairingCode] Clicking 'Enter code…' link (attempt {enter_code_clicks})..."
                )
                if enter_code_clicks % 2 == 1:
                    self._cm_tap_center(enter_link, desc="Enter code…")
                else:
                    self._cm_click_or_tap(enter_link, desc="Enter code…")
                time.sleep(1.5)
                continue

            help_tv = self._cm_find_displayed(
                IOS_PREDICATE_BY, self.ENTER_CODE_TEXTVIEW_PREDICATE, allow_hidden=True
            )
            if help_tv is not None:
                enter_code_clicks += 1
                try:
                    r = help_tv.rect
                    tx = int(r["x"] + r["width"] * 0.72)
                    ty = int(r["y"] + r["height"] * 0.80)
                    self._logger.info(
                        f"[PairingCode] Tapping 'Enter code…' inside TextView at ({tx}, {ty})..."
                    )
                    self.driver.execute_script("mobile: tap", {"x": tx, "y": ty})
                except WebDriverException:
                    self._cm_tap_center(help_tv, desc="Enter code TextView")
                time.sleep(1.5)
                continue

            # Screen 2: 'Select an Accessory to Add' -> "My Accessory Isn't Shown Here"
            not_shown_btn = self._cm_find_displayed(
                IOS_PREDICATE_BY, self.NOT_SHOWN_BTN_PREDICATE, allow_hidden=True
            )
            if not_shown_btn is not None:
                not_shown_clicks += 1
                self._logger.info(
                    f"[PairingCode] Tapping \"My Accessory Isn't Shown Here\" (attempt {not_shown_clicks})..."
                )
                if not_shown_clicks % 2 == 1:
                    self._cm_tap_center(not_shown_btn, desc="My Accessory Isn't Shown Here")
                else:
                    self._cm_click_or_tap(not_shown_btn, desc="My Accessory Isn't Shown Here")
                time.sleep(1.5)
                continue

            # Screen 1: 'Add Accessory' -> 'Scan code or hold iPhone near the accessory. More options…'
            more_link = self._cm_find_displayed(
                IOS_PREDICATE_BY, self.MORE_OPTIONS_LINK_PREDICATE, allow_hidden=True
            )
            if more_link is not None:
                more_options_clicks += 1
                self._logger.info(
                    "[PairingCode] Detected 'Scan code or hold iPhone near the accessory. More options…' "
                    f"(attempt {more_options_clicks}). Clicking..."
                )
                self._cm_tap_more_options_link(more_link, attempt=more_options_clicks)
                time.sleep(1.5)
                continue

            time.sleep(0.6)

        return (
            f"Timed out after {int(timeout)}s trying to reach 'Setup Code' and submit pairing code "
            "on Apple Matter sheet."
        )

    def enter_pairing_code_on_apple_sheet(
            self, pairing_code: Optional[str] = None, timeout: float = 45.0
    ) -> bool:
        """Navigate Apple's 'More options…' flow and submit the manual Matter pairing code."""
        page = GHPCommissioningPageObject._resolve_page(self)
        code = str(
            pairing_code if pairing_code is not None else getattr(self, "pairing_code", "") or "")
        err = page._cm_enter_pairing_code_steps(code, timeout=timeout)
        if err is not None:
            page._logger.error(f"[PairingCode] {err}")
            BasePage.capture_failure_screenshot(page.driver, reason=err, force=False, lock=True)
            raise AssertionError(err)
        return True

    # -------------------------------------------------------------------------
    # 3. Apple Matter Commissioning Sheets ('Add to Google Home', 'Uncertified',
    #    'Additional Setup Required', Location/Room, Custom Name, 'Done', and Failure Detection)
    # -------------------------------------------------------------------------
    def _cm_detect_apple_failure_title(self) -> Optional[str]:
        """Return matching Apple Matter failure text if a failure card/alert is on screen."""
        sb_fail = getattr(self, "_cm_springboard_failure_title", "") or ""
        if sb_fail:
            self._cm_springboard_failure_title = ""
            return sb_fail

        clauses = " OR ".join(
            f'label CONTAINS[c] "{kw}" OR name CONTAINS[c] "{kw}" OR value CONTAINS[c] "{kw}"'
            for kw in self.APPLE_FAILURE_KEYWORDS
        )
        predicate = (
            'type IN {"XCUIElementTypeTextView", "XCUIElementTypeStaticText", "XCUIElementTypeAlert"} '
            f"AND ({clauses})"
        )
        elem = self._cm_find_displayed(IOS_PREDICATE_BY, predicate, allow_hidden=True)
        if elem is not None:
            return self._cm_read_text(elem) or "Apple Matter Commissioning Failed"
        return None

    def _cm_tap_springboard_alert_button_fallback(self, button_label: str) -> bool:
        """Last-resort SpringBoard coordinate tap when iOS 26 Liquid Glass ignores WDA alert accept."""
        if not hasattr(self.driver, "update_settings"):
            return False
        prev_app = "auto"
        try:
            if hasattr(self.driver, "get_settings"):
                settings = self.driver.get_settings() or {}
                prev_app = settings.get("defaultActiveApplication", "auto") or "auto"
        except Exception:
            prev_app = "auto"

        try:
            self.driver.update_settings({"defaultActiveApplication": "com.apple.springboard"})
            escaped = button_label.replace('"', '\\"')
            sb_btn = self._cm_find_displayed(
                AppiumBy.ACCESSIBILITY_ID, button_label, allow_hidden=True
            ) or self._cm_find_displayed(
                IOS_PREDICATE_BY,
                f'type IN {{"XCUIElementTypeButton", "XCUIElementTypeOther"}} '
                f'AND (name == "{escaped}" OR label == "{escaped}")',
                allow_hidden=True,
            )
            if sb_btn is not None:
                self._logger.info(
                    f"[Apple Alert] Tapping '{button_label}' directly in SpringBoard UI tree..."
                )
                return self._cm_tap_center(sb_btn, desc=f"SpringBoard '{button_label}'")
        except Exception as err:
            self._logger.debug(f"[Apple Alert] SpringBoard fallback lookup failed: {err}")
        finally:
            try:
                self.driver.update_settings({"defaultActiveApplication": prev_app})
            except Exception:
                pass
        return False

    def _cm_handle_apple_system_alert(self) -> bool:
        """Accept benign iOS / Apple Matter modal alerts ('Additional Setup Required' -> 'OK',
        'Uncertified Accessory' -> 'Add Anyway', Local Network / Bluetooth -> 'Allow').

        Never swallows Apple Matter failure cards or GHP OOBE error/decommission alerts.
        Handles both UI-tree overlays (`SBTransientOverlayWindow`) and `SpringBoard` (`mobile: alert`).
        """
        # 1. Never swallow Apple Matter failure cards or GHP OOBE error/decommission alerts
        if self._cm_detect_apple_failure_title():
            return False
        if (
                self._cm_find_displayed(
                    IOS_PREDICATE_BY, self.OOBE_ERROR_ALERT_PREDICATE, allow_hidden=True
                )
                is not None
        ):
            return False
        if self._cm_detect_ghp_failure_text():
            return False

        alerts = self._cm_find_all(AppiumBy.CLASS_NAME, "XCUIElementTypeAlert")
        detected_alert_title = ""
        for alert in alerts:
            txt = self._cm_read_text(alert)
            if not txt:
                continue
            if _contains_any(
                    txt,
                    (
                            "Stream removed",
                            "NSPOSIXErrorDomain",
                            "Socket is not connected",
                            "Internal error",
                            "Decommission",
                            "Commissioning failed",
                            "Could not start commissioning",
                    ),
            ):
                return False
            if _contains_any(txt, self.APPLE_FAILURE_KEYWORDS):
                self._cm_springboard_failure_title = txt
                return False
            if not detected_alert_title and txt.lower() != "setup code":
                detected_alert_title = txt

        if not detected_alert_title:
            add_setup_el = self._cm_find_displayed(
                IOS_PREDICATE_BY,
                'type IN {"XCUIElementTypeStaticText", "XCUIElementTypeTextView"} AND ('
                'label CONTAINS[c] "Additional Setup Required" '
                'OR label CONTAINS[c] "requires additional setup" '
                'OR label CONTAINS[c] "Uncertified Accessory")',
                allow_hidden=True,
            )
            if add_setup_el is not None:
                detected_alert_title = self._cm_read_text(add_setup_el)

        # 2. Path A: Button visible in active app / SBTransientOverlayWindow accessibility tree
        for btn_label in self.SYSTEM_ALERT_ACCEPT_BUTTONS:
            escaped = btn_label.replace('"', '\\"')
            btn_pred = (
                f'type == "XCUIElementTypeButton" AND (name == "{escaped}" OR label == "{escaped}")'
            )
            btn_elem = self._cm_find_displayed(AppiumBy.ACCESSIBILITY_ID, btn_label)
            if btn_elem is None:
                btn_elem = self._cm_find_displayed(IOS_PREDICATE_BY, btn_pred)
            if btn_elem is None:
                for alert in alerts:
                    nested = self._cm_find_all(IOS_PREDICATE_BY, btn_pred, root=alert)
                    if nested:
                        btn_elem = nested[0]
                        break
            if btn_elem is not None:
                if detected_alert_title:
                    self._cm_last_apple_card_title = detected_alert_title
                self._logger.info(
                    f"[Apple Alert] Clicking '{btn_label}' on system alert"
                    f"{f' ({detected_alert_title!r})' if detected_alert_title else ''}..."
                )
                self._cm_click_or_tap(btn_elem, desc=f"System alert '{btn_label}'")
                time.sleep(0.7)

                # On iOS 26 Liquid Glass XPC overlays, .click() can return 200 without dismissing;
                # verify dismissal and follow up with coordinate tap + mobile:alert accept if still present.
                still_there = self._cm_find_displayed(IOS_PREDICATE_BY, btn_pred)
                if still_there is not None:
                    self._logger.info(
                        f"[Apple Alert] '{btn_label}' still visible after click(); "
                        "tapping button coordinates and mobile:alert accept..."
                    )
                    self._cm_tap_center(still_there, desc=f"System alert '{btn_label}' tap")
                    try:
                        with self._cm_fast_probe():
                            self.driver.execute_script(
                                "mobile: alert", {"action": "accept", "buttonLabel": btn_label}
                            )
                    except Exception:
                        pass
                    time.sleep(0.6)
                return True

        # 3. Path B: SpringBoard-hosted system alert outside app UI tree (via WDA 'mobile: alert')
        raw_buttons = None
        try:
            with self._cm_fast_probe():
                raw_buttons = self.driver.execute_script("mobile: alert", {"action": "getButtons"})
        except Exception:
            raw_buttons = None

        if isinstance(raw_buttons, (list, tuple)) and raw_buttons:
            sb_text = ""
            try:
                sb_text = str(self.driver.switch_to.alert.text or "").strip()
            except Exception:
                sb_text = ""

            if _contains_any(
                    sb_text,
                    (
                            "Stream removed",
                            "NSPOSIXErrorDomain",
                            "Socket is not connected",
                            "Internal error",
                            "Decommission",
                            "Commissioning failed",
                            "Could not start commissioning",
                    ),
            ):
                return False

            if _contains_any(sb_text, self.APPLE_FAILURE_KEYWORDS):
                self._cm_springboard_failure_title = sb_text
                return False

            matched_btn: Optional[str] = None
            for candidate in self.SYSTEM_ALERT_ACCEPT_BUTTONS:
                for b in raw_buttons:
                    if str(b).strip().lower() == candidate.lower():
                        matched_btn = str(b).strip()
                        break
                if matched_btn:
                    break

            if matched_btn:
                if sb_text:
                    self._cm_last_apple_card_title = sb_text.splitlines()[0].strip()
                self._logger.info(
                    f"[Apple Alert] Accepting SpringBoard alert "
                    f"{f'({sb_text!r}) ' if sb_text else ''}via '{matched_btn}' "
                    f"(buttons={list(raw_buttons)})..."
                )
                accepted = False
                try:
                    with self._cm_fast_probe():
                        self.driver.execute_script(
                            "mobile: alert", {"action": "accept", "buttonLabel": matched_btn}
                        )
                    accepted = True
                except Exception as err:
                    self._logger.debug(
                        f"[Apple Alert] mobile:alert accept({matched_btn}) failed: {err}")
                    try:
                        self.driver.switch_to.alert.accept()
                        accepted = True
                    except Exception as err2:
                        self._logger.debug(f"[Apple Alert] switch_to.alert.accept() failed: {err2}")

                time.sleep(0.6)
                still_open_btns = None
                try:
                    with self._cm_fast_probe():
                        still_open_btns = self.driver.execute_script(
                            "mobile: alert", {"action": "getButtons"}
                        )
                except Exception:
                    still_open_btns = None

                if not accepted or (
                        isinstance(still_open_btns, (list, tuple))
                        and any(
                    str(b).strip().lower() == matched_btn.lower() for b in still_open_btns)
                ):
                    self._cm_tap_springboard_alert_button_fallback(matched_btn)
                    time.sleep(0.6)
                return True

        return False

    def _cm_is_apple_proximity_card_open(self) -> bool:
        """Return True if an Apple HomeUIService PRXCard sheet or SBTransientOverlayWindow is visible."""
        if (
                self._cm_find_displayed(IOS_CLASS_CHAIN_BY, self.APPLE_OVERLAY_WINDOW_CHAIN)
                is not None
        ):
            return True
        pred = (
            'name == "PRXCardBottomTray" '
            'OR type == "XCUIElementTypePickerWheel" '
            'OR (type == "XCUIElementTypeButton" AND name == "Close" AND label == "Close") '
            'OR (type == "XCUIElementTypeButton" AND ('
            'name BEGINSWITH[c] "Add to" OR label BEGINSWITH[c] "Add to" '
            'OR name == "Set Up" OR label == "Set Up"))'
        )
        return self._cm_find_displayed(IOS_PREDICATE_BY, pred, allow_hidden=True) is not None

    def _cm_click_apple_button_with_tap_fallback(
            self, btn: WebElement, card_title: str = "", desc: str = "Apple button"
    ) -> bool:
        """Click an Apple HomeUIService PRXCard button, falling back to coordinate tap if XPC ignores .click()."""
        cx: Optional[int] = None
        cy: Optional[int] = None
        try:
            r = btn.rect
            w = float(r.get("width", 0))
            h = float(r.get("height", 0))
            if w > 0 and h > 0:
                cx = int(float(r.get("x", 0)) + w / 2.0)
                cy = int(float(r.get("y", 0)) + h / 2.0)
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

        if cx is None or cy is None:
            return True

        time.sleep(0.7)
        # If a system/permission alert opened after .click(), the click already succeeded
        try:
            with self._cm_fast_probe():
                sb_btns = self.driver.execute_script("mobile: alert", {"action": "getButtons"})
            if isinstance(sb_btns, (list, tuple)) and sb_btns:
                return True
        except Exception:
            pass
        btn_clauses = " OR ".join(
            f'name == "{b}" OR label == "{b}"' for b in self.SYSTEM_ALERT_ACCEPT_BUTTONS
        )
        btn_pred = f'type == "XCUIElementTypeButton" AND ({btn_clauses})'
        if self._cm_find_displayed(IOS_PREDICATE_BY, btn_pred) is not None:
            return True
        for alert_el in self._cm_find_all(AppiumBy.CLASS_NAME, "XCUIElementTypeAlert"):
            if self._cm_find_all(IOS_PREDICATE_BY, btn_pred, root=alert_el):
                return True

        after_title = self._cm_read_apple_card_title()
        still_clickable = False
        try:
            if btn.is_displayed():
                en = str(btn.get_attribute("enabled") or "true").lower()
                still_clickable = en != "false"
        except (StaleElementReferenceException, WebDriverException):
            still_clickable = False

        same_card = (
                            bool(
                                card_title) and after_title.strip().lower() == card_title.strip().lower()
                    ) or (not card_title and still_clickable and not after_title)
        if same_card and (
                still_clickable
                or self._cm_find_displayed(AppiumBy.CLASS_NAME, "XCUIElementTypeActivityIndicator")
                is None
        ):
            self._logger.info(
                f"[Apple Sheet] '{desc}' .click() kept card '{card_title or after_title}'; "
                f"tapping coordinates ({cx}, {cy})..."
            )
            try:
                self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
            except WebDriverException:
                pass
        return True

    def _cm_find_picker_wheel(self) -> Optional[WebElement]:
        """Locate Apple HomeUIService's XCUIElementTypePickerWheel on Room/Location cards."""
        wheels = self._cm_find_all(AppiumBy.CLASS_NAME, "XCUIElementTypePickerWheel")
        for w in wheels:
            if self._cm_is_visible(w):
                return w
        for w in wheels:
            try:
                r = w.rect
                if float(r.get("width", 0)) > 0 and float(r.get("height", 0)) > 0:
                    return w
            except (StaleElementReferenceException, WebDriverException):
                continue
        return None

    def _cm_read_picker_wheel_value(self, wheel: Optional[WebElement] = None) -> str:
        """Read normalized selected room string from XCUIElementTypePickerWheel."""
        target = wheel if wheel is not None else self._cm_find_picker_wheel()
        if target is None:
            return ""
        raw = self._cm_read_text(target, ("value", "label", "name"))
        return " ".join(raw.split()) if raw else ""

    def _cm_step_picker_wheel(self, direction: str, before_val: str) -> str:
        """Advance XCUIElementTypePickerWheel by 1 slot ('prev' = upper item, 'next' = lower item).

        Uses window-coordinate touch synthesis (adjacent-slot tap + slow dragFromToForDuration)
        before WDA selectPickerWheelValue because HomeUIService's PickerWheel is a remote XPC view.
        """
        wheel = self._cm_find_picker_wheel()
        if wheel is None:
            return ""
        cx, cy, h = 195, 619, 262.0
        try:
            r = wheel.rect
            rw = float(r.get("width", 0))
            rh = float(r.get("height", 0))
            if rw > 0 and rh > 0:
                cx = int(float(r.get("x", 0)) + rw / 2.0)
                cy = int(float(r.get("y", 0)) + rh / 2.0)
                h = rh
        except (StaleElementReferenceException, WebDriverException):
            pass

        base_methods = ["tap", "drag_small", "drag_medium", "wda_select"]
        if self._cm_picker_preferred_method in base_methods:
            methods = [self._cm_picker_preferred_method] + [
                m for m in base_methods if m != self._cm_picker_preferred_method
            ]
        else:
            methods = base_methods

        cur = before_val
        for method in methods:
            try:
                if method == "tap":
                    tap_off = max(34, min(44, int(h * 0.145)))
                    ty = cy - tap_off if direction == "prev" else cy + tap_off
                    self.driver.execute_script("mobile: tap", {"x": cx, "y": ty})
                elif method == "drag_small":
                    half = max(22, min(28, int(h * 0.095)))
                    from_y = (cy - half) if direction == "prev" else (cy + half)
                    to_y = (cy + half) if direction == "prev" else (cy - half)
                    self.driver.execute_script(
                        "mobile: dragFromToForDuration",
                        {
                            "duration": 0.30,
                            "fromX": cx,
                            "fromY": from_y,
                            "toX": cx,
                            "toY": to_y,
                        },
                    )
                elif method == "drag_medium":
                    half = max(36, min(46, int(h * 0.16)))
                    from_y = (cy - half) if direction == "prev" else (cy + half)
                    to_y = (cy + half) if direction == "prev" else (cy - half)
                    self.driver.execute_script(
                        "mobile: dragFromToForDuration",
                        {
                            "duration": 0.35,
                            "fromX": cx,
                            "fromY": from_y,
                            "toX": cx,
                            "toY": to_y,
                        },
                    )
                elif method == "wda_select":
                    w_now = self._cm_find_picker_wheel()
                    elem_id = getattr(w_now, "id", None) if w_now is not None else None
                    if not elem_id:
                        continue
                    self.driver.execute_script(
                        "mobile: selectPickerWheelValue",
                        {
                            "elementId": elem_id,
                            "order": "previous" if direction == "prev" else "next",
                            "offset": 0.15,
                        },
                    )
            except WebDriverException:
                continue

            time.sleep(0.4)
            cur = self._cm_read_picker_wheel_value()
            if cur and cur != before_val:
                self._cm_picker_preferred_method = method
                return cur

        return cur or before_val

    def _cm_select_room_on_picker_wheel(
            self, room_name: str, max_steps_per_dir: int = 25
    ) -> bool:
        """Read current PickerWheel room and scroll until `room_name` is selected."""
        target = " ".join((room_name or "").strip().split())
        if not target:
            return True

        cur = self._cm_read_picker_wheel_value()
        self._logger.info(
            f"[Apple Sheet] PickerWheel current room: '{cur}', target room: '{target}'"
        )
        if cur == target:
            self._logger.info(f"[Apple Sheet] PickerWheel already at room '{target}'.")
            return True

        directions = (
            ("prev", "next")
            if (not cur or target.lower() <= cur.lower())
            else ("next", "prev")
        )
        visited: List[str] = [cur] if cur else []

        for direction in directions:
            opposite = "next" if direction == "prev" else "prev"
            if cur == target:
                return True
            for _ in range(max_steps_per_dir):
                prev_val = cur
                cur = self._cm_step_picker_wheel(direction, prev_val)
                if not cur:
                    return False
                if cur not in visited:
                    visited.append(cur)
                if cur != prev_val:
                    self._logger.info(
                        f"[Apple Sheet] PickerWheel scrolled ({direction}): '{prev_val}' -> '{cur}'"
                    )
                if cur == target:
                    self._logger.info(
                        f"[Apple Sheet] PickerWheel selected target room '{cur}'."
                    )
                    return True
                if cur == prev_val:
                    if cur.lower() == target.lower():
                        self._logger.info(
                            f"[Apple Sheet] PickerWheel matched room '{cur}' (case-insensitive)."
                        )
                        return True
                    break
                # Previous slot matched case-insensitively and next slot wasn't an exact-case twin
                if prev_val and prev_val.lower() == target.lower() and cur.lower() != target.lower():
                    cur = self._cm_step_picker_wheel(opposite, cur)
                    self._logger.info(
                        f"[Apple Sheet] PickerWheel restored case-insensitive match '{cur}'."
                    )
                    return True
                # Fine-tune if a drag skipped 1 slot across `target` alphabetically
                if prev_val and (
                        (direction == "prev" and prev_val.lower() > target.lower() > cur.lower())
                        or (direction == "next" and prev_val.lower() < target.lower() < cur.lower())
                ):
                    nudged = self._cm_step_picker_wheel(opposite, cur)
                    if nudged == target or nudged.lower() == target.lower():
                        self._logger.info(
                            f"[Apple Sheet] PickerWheel fine-tuned to room '{nudged}'."
                        )
                        return True
                    cur = nudged

        if cur and cur.lower() == target.lower():
            return True

        self._logger.warning(
            f"[Apple Sheet] Room '{target}' not found on PickerWheel (visited={visited}); "
            f"proceeding with '{cur}'."
        )
        return False

    def _cm_read_apple_card_title(self) -> str:
        """Read the current visible Apple PRXCard title, ignoring button labels."""
        for elem in self._cm_find_all(IOS_CLASS_CHAIN_BY, self.APPLE_CARD_TITLE_CHAIN):
            if not self._cm_is_visible(elem):
                continue
            txt = self._cm_read_text(elem)
            if txt and txt.lower() not in self.APPLE_IGNORED_BUTTON_TITLES:
                return txt
        for elem in self._cm_find_all(AppiumBy.CLASS_NAME, "XCUIElementTypeTextView"):
            if not self._cm_is_visible(elem):
                continue
            txt = self._cm_read_text(elem)
            if txt and txt.lower() not in self.APPLE_IGNORED_BUTTON_TITLES:
                return txt
        return ""

    def _cm_dismiss_apple_sheet_if_open(self) -> None:
        for pred in (
                self.ALERT_OK_BTN_PREDICATE,
                'type == "XCUIElementTypeButton" AND (name IN {"Done", "Close", "Cancel"} OR label IN {"Done", "Close", "Cancel"})',
        ):
            btn = self._cm_find_displayed(IOS_PREDICATE_BY, pred)
            if btn is not None:
                self._cm_click_or_tap(btn, desc="Dismiss Apple sheet")
                time.sleep(0.8)
                return
        try:
            with self._cm_fast_probe():
                self.driver.execute_script("mobile: alert", {"action": "dismiss"})
        except Exception:
            pass

    def handle_apple_commissioning_sheet(
            self, device_name: str, room_name: str = "Attic"
    ) -> bool:
        """Handle one step of Apple's HomeUIService commissioning sheet if visible.

        Returns:
            True if an Apple sheet/system alert was active on screen, False otherwise.
        Raises:
            _GHPApiAppleSheetFailure: If Apple's Matter sheet displays an error card.
        """
        # 1. Check Apple failure card first (capture immediate locked screenshot BEFORE dismissing!)
        fail_title = self._cm_detect_apple_failure_title()
        if fail_title:
            self._logger.error(f"[Apple Sheet] Failure detected: '{fail_title}'")
            BasePage.capture_failure_screenshot(
                self.driver, reason=f"Apple sheet failure: {fail_title}", force=True, lock=True
            )
            self._cm_dismiss_apple_sheet_if_open()
            raise _GHPApiAppleSheetFailure(
                f"Apple Matter commissioning failed: '{fail_title}'", card_title=fail_title
            )

        # 2. Accept benign iOS / Apple Matter system alerts
        #    ('Additional Setup Required' -> 'OK', 'Uncertified Accessory' -> 'Add Anyway', permissions -> 'Allow')
        if self._cm_handle_apple_system_alert():
            return True

        # Re-check failure title in case SpringBoard alert probe detected an Apple failure alert
        fail_title = self._cm_detect_apple_failure_title()
        if fail_title:
            self._logger.error(f"[Apple Sheet] Failure detected on alert: '{fail_title}'")
            BasePage.capture_failure_screenshot(
                self.driver, reason=f"Apple sheet failure: {fail_title}", force=True, lock=True
            )
            self._cm_dismiss_apple_sheet_if_open()
            raise _GHPApiAppleSheetFailure(
                f"Apple Matter commissioning failed: '{fail_title}'", card_title=fail_title
            )

        if not self._cm_is_apple_proximity_card_open():
            return False

        # Read Apple card title (XCUIElementTypeTextView at top of PRXCard)
        card_title = self._cm_read_apple_card_title()
        if card_title:
            self._cm_last_apple_card_title = card_title

        is_setup_code_card = (
                "setup code" in card_title.lower()
                or self._cm_find_displayed(
            IOS_PREDICATE_BY, self.SETUP_CODE_HEADER_PREDICATE, allow_hidden=True
        )
                is not None
        )

        # 3. 'Add to “Google Home”' or 'Set Up' button
        add_to_btn = self._cm_find_displayed(
            IOS_PREDICATE_BY,
            'type == "XCUIElementTypeButton" AND ('
            'name BEGINSWITH[c] "Add to" OR label BEGINSWITH[c] "Add to" '
            'OR name == "Set Up" OR label == "Set Up")',
        )
        if add_to_btn is not None:
            btn_txt = self._cm_read_text(add_to_btn)
            self._logger.info(f"[Apple Sheet] Clicking '{btn_txt}'...")
            self._cm_click_apple_button_with_tap_fallback(
                add_to_btn, card_title=card_title, desc=btn_txt
            )
            time.sleep(1.0)
            return True

        # 4. Custom Accessory/Camera/Bridge Name card (XCUIElementTypeTextField visible, NEVER on spinning Setup Code!)
        text_fields = self._cm_find_all(AppiumBy.CLASS_NAME, "XCUIElementTypeTextField")
        visible_tf = next((tf for tf in text_fields if self._cm_is_visible(tf)), None)
        cont_btn = self._cm_find_displayed(IOS_PREDICATE_BY, self.CONTINUE_BTN_PREDICATE)
        tf_cur_val = (
            self._cm_read_text(visible_tf, ("value", "placeholderValue", "label"))
            if visible_tf is not None
            else ""
        )
        looks_like_setup_digits = bool(tf_cur_val and re.fullmatch(r"[\d\s\-]{8,}", tf_cur_val))
        is_name_card = (
                visible_tf is not None
                and not is_setup_code_card
                and not looks_like_setup_digits
                and ("name" in card_title.lower() or cont_btn is not None)
        )
        if is_name_card:
            name_card_key = (card_title or "default_name_card").strip().lower()
            if name_card_key not in self._cm_named_card_titles and device_name:
                if tf_cur_val and tf_cur_val != device_name:
                    try:
                        if not getattr(self.driver, "_ghp_commissioned_tile_name", None):
                            setattr(self.driver, "_ghp_commissioned_tile_name", tf_cur_val)
                    except Exception:
                        pass
                self._logger.info(
                    f"[Apple Sheet] Setting accessory name to '{device_name}' (card='{card_title}')..."
                )
                self._cm_click_or_tap(visible_tf, desc="Accessory Name TextField")
                time.sleep(0.3)
                try:
                    visible_tf.clear()
                except WebDriverException:
                    pass
                # Clear residual characters via clear button if present
                clr_btn = self._cm_find_displayed(
                    IOS_PREDICATE_BY,
                    'type == "XCUIElementTypeButton" AND (name == "Clear text" OR label == "Clear text")',
                )
                if clr_btn is not None:
                    self._cm_click_or_tap(clr_btn, desc="Clear text")
                try:
                    visible_tf.send_keys(device_name)
                except WebDriverException as err:
                    self._logger.warning(f"[Apple Sheet] Failed typing custom name: {err}")
                kb_done = self._cm_find_displayed(
                    IOS_PREDICATE_BY,
                    'type == "XCUIElementTypeButton" AND (name IN {"Done", "Return", "done", "return"} '
                    'OR label IN {"Done", "Return", "done", "return"})',
                )
                if kb_done is not None:
                    try:
                        r_kb = kb_done.rect
                        if r_kb.get("y", 0) > 480 and r_kb.get("width", 999) < 160:
                            self._cm_click_or_tap(kb_done, desc="Keyboard Done/Return")
                            time.sleep(0.4)
                    except WebDriverException:
                        pass
                self._cm_named_in_current_flow = True
                self._cm_named_card_titles.add(name_card_key)

            cont_btn = self._cm_find_displayed(
                IOS_PREDICATE_BY, self.CONTINUE_BTN_PREDICATE, allow_hidden=True
            )
            if cont_btn is not None:
                self._logger.info(
                    f"[Apple Sheet] Clicking 'Continue' on '{card_title or 'Name card'}'...")
                self._cm_click_apple_button_with_tap_fallback(
                    cont_btn, card_title=card_title, desc="Name Continue"
                )
                time.sleep(1.0)
                return True

        # 5. Room / Location selection card (PickerWheel on 'Bridge Location' / '<Accessory> Location', or list fallback)
        picker_wheel = self._cm_find_picker_wheel()
        if (picker_wheel is not None or cont_btn is not None) and not is_setup_code_card:
            if picker_wheel is not None:
                if room_name:
                    self._cm_select_room_on_picker_wheel(room_name)
            elif room_name:
                escaped_room = room_name.strip().replace('"', '\\"')
                room_el = self._cm_find_displayed(
                    IOS_PREDICATE_BY,
                    'type IN {"XCUIElementTypeCell", "XCUIElementTypeButton", "XCUIElementTypeStaticText"} '
                    f'AND (name == "{escaped_room}" OR label == "{escaped_room}")',
                )
                if room_el is not None:
                    self._logger.info(f"[Apple Sheet] Selecting room '{room_name}'...")
                    self._cm_click_or_tap(room_el, desc=f"Room '{room_name}'")
                    time.sleep(0.5)

            cont_btn = self._cm_find_displayed(
                IOS_PREDICATE_BY, self.CONTINUE_BTN_PREDICATE, allow_hidden=True
            )
            if cont_btn is not None:
                self._logger.info(
                    f"[Apple Sheet] Clicking 'Continue' on '{card_title or 'Location card'}'..."
                )
                self._cm_click_apple_button_with_tap_fallback(
                    cont_btn, card_title=card_title, desc="Location Continue"
                )
                time.sleep(1.0)
                return True

        # 6. Completion card ('<Accessory> was added to “Google Home”' -> 'Done' in PRXCardBottomTray)
        is_setup_help_card = (
                "setup help" in card_title.lower()
                or self._cm_find_displayed(
            IOS_PREDICATE_BY, self.ENTER_CODE_TEXTVIEW_PREDICATE, allow_hidden=True
        )
                is not None
        )
        tray_done = self._cm_find_displayed(
            IOS_CLASS_CHAIN_BY,
            '**/XCUIElementTypeOther[`name == "PRXCardBottomTray"`]/**/XCUIElementTypeButton[`name == "Done" OR label == "Done"`]',
        )
        if tray_done is None and (
                "added to" in card_title.lower() or "ready" in card_title.lower()):
            tray_done = self._cm_find_displayed(
                IOS_PREDICATE_BY,
                'type == "XCUIElementTypeButton" AND (name == "Done" OR label == "Done")',
                allow_hidden=True,
            )
        if tray_done is not None and not is_setup_help_card:
            self._logger.info(
                f"[Apple Sheet] Accessory added ('{card_title}'). Clicking 'Done'..."
            )
            self._cm_click_apple_button_with_tap_fallback(
                tray_done, card_title=card_title, desc="Apple Sheet Done"
            )
            self._cm_apple_done_clicked_at = time.time()
            time.sleep(1.2)
            return True

        # 7. Connecting / Setting Up / BLE Discovery spinner card
        self._logger.info(
            f"[Apple Sheet] Waiting for Apple Matter progress ('{card_title or 'Connecting/Setting Up'}')..."
        )
        time.sleep(1.5)
        return True

    @staticmethod
    def _cm_is_visible(elem: WebElement) -> bool:
        try:
            return bool(elem.is_displayed())
        except WebDriverException:
            return False

    # -------------------------------------------------------------------------
    # 4. GHP Camera OOBE & OOBE OTA Verification (CameraOOBEView)
    # -------------------------------------------------------------------------
    def _cm_check_oobe_error_alert(self) -> Optional[str]:
        """Detect modal OOBE/OTA error alerts (e.g. 'Stream removed / NSPOSIXErrorDomain'), screenshot, and dismiss."""
        alert_el = self._cm_find_displayed(IOS_PREDICATE_BY, self.OOBE_ERROR_ALERT_PREDICATE)
        if alert_el is None:
            return None
        alert_text = self._cm_read_text(alert_el) or "OOBE internal/stream error alert"
        self._logger.error(f"[GHP OOBE] Detected error alert: '{alert_text}'")
        BasePage.capture_failure_screenshot(
            self.driver, reason=f"GHP OOBE error alert: {alert_text}", force=True, lock=True
        )
        ok_btn = self._cm_find_displayed(IOS_PREDICATE_BY, self.ALERT_OK_BTN_PREDICATE)
        if ok_btn is not None:
            self._cm_click_or_tap(ok_btn, desc="Alert OK")
            time.sleep(0.5)
        return alert_text

    def _cm_detect_ghp_failure_text(self) -> Optional[str]:
        clauses = " OR ".join(
            f'label CONTAINS[c] "{kw}" OR name CONTAINS[c] "{kw}" OR value CONTAINS[c] "{kw}"'
            for kw in self.GHP_FAILURE_KEYWORDS
        )
        elem = self._cm_find_displayed(
            IOS_PREDICATE_BY, f'type == "XCUIElementTypeStaticText" AND ({clauses})'
        )
        return self._cm_read_text(elem) if elem is not None else None

    def _cm_capture_oobe_navbar_device_name(self) -> None:
        """Capture actual GHP device name from CameraOOBEView's NavigationBar (e.g. 'indoor cameraxx Xxxxx')."""
        ignored = {
            "home",
            "devices",
            "settings",
            "automations",
            "history",
            "search",
            "camera",
            "back",
            "oobe",
            "setup",
            "done",
        }
        for nav in self._cm_find_all(AppiumBy.CLASS_NAME, "XCUIElementTypeNavigationBar"):
            if not self._cm_is_visible(nav):
                continue
            nav_name = " ".join(self._cm_read_text(nav, ("name", "label", "value")).split())
            if not nav_name or nav_name.lower() in ignored:
                continue
            if self._cm_reset_device_name and nav_name.lower() == self._cm_reset_device_name.strip().lower():
                return
            try:
                prev = getattr(self.driver, "_ghp_commissioned_tile_name", None)
                if prev != nav_name:
                    setattr(self.driver, "_ghp_commissioned_tile_name", nav_name)
                    self._logger.info(
                        f"[GHP OOBE] Captured NavigationBar camera tile name: '{nav_name}'"
                    )
            except Exception:
                pass
            return

    def _cm_get_oobe_headline(self) -> str:
        """Inspect current GHP CameraOOBEView screen and return its active state headline, or ''."""
        all_markers = (
                self.OTA_FAILURE_KEYWORDS
                + self.OTA_KEYWORDS
                + (
                    "Setup complete!",
                    "Camera setup complete!",
                    "Setup complete",
                    "Waiting for device to be online...",
                    "Microphone Settings",
                    "Adjust your mic settings",
                )
        )
        clauses = " OR ".join(
            f'label CONTAINS[c] "{kw}" OR value CONTAINS[c] "{kw}"' for kw in all_markers
        )
        elems = self._cm_find_all(
            IOS_PREDICATE_BY, f'type == "XCUIElementTypeStaticText" AND ({clauses})'
        )
        visible_texts: List[str] = []
        for el in elems:
            if self._cm_is_visible(el):
                txt = self._cm_read_text(el)
                if txt and txt not in visible_texts:
                    visible_texts.append(txt)

        # Prioritize OTA failure -> specific OTA sub-state -> generic OTA header -> Done state -> Settings state
        for priority_group in (
                self.OTA_FAILURE_KEYWORDS,
                (
                        "Checking for update",
                        "Preparing update",
                        "Downloading update",
                        "Downloading (",
                        "Downloading",
                        "Installing update",
                        "Installing",
                        "Applying update",
                        "Update finished",
                ),
                ("Software update", "Progress:"),
                (
                        "Setup complete!",
                        "Camera setup complete!",
                        "Setup complete",
                        "Waiting for device to be online...",
                ),
                ("Microphone Settings", "Adjust your mic settings"),
        ):
            for txt in visible_texts:
                if _contains_any(txt, priority_group):
                    self._cm_capture_oobe_navbar_device_name()
                    return txt

        # Fallback for OOBE Done screen if checkmark.circle + NavigationBar 'Done' are visible
        if (
                self._cm_find_displayed(
                    IOS_PREDICATE_BY,
                    'type == "XCUIElementTypeImage" AND name CONTAINS[c] "checkmark.circle"',
                )
                is not None
                and self._cm_find_displayed(
            IOS_PREDICATE_BY,
            'type == "XCUIElementTypeButton" AND (name == "Done" OR label == "Done")',
            allow_hidden=True,
        )
                is not None
        ):
            self._cm_capture_oobe_navbar_device_name()
            return "Setup complete!"

        # Also check if OOBE Settings toolbar 'Next' button is visible (Step 2 of CameraOOBEView)
        next_btn = self._cm_find_displayed(
            IOS_PREDICATE_BY,
            'type == "XCUIElementTypeButton" AND (name == "Next" OR label == "Next")',
        )
        if next_btn is not None:
            self._cm_capture_oobe_navbar_device_name()
            return "Camera OOBE Settings"

        return ""

    def _cm_read_ota_progress_percent(self) -> Tuple[Optional[int], str]:
        """Read OTA percentage from GHP OtaDownloadView (e.g. 'Progress: 45%' -> (45, 'Progress: 45%'))."""
        preferred: List[Tuple[int, str]] = []
        fallback: List[Tuple[int, str]] = []
        for elem in self._cm_find_all(IOS_PREDICATE_BY, self.OTA_PERCENT_PREDICATE):
            if not self._cm_is_visible(elem):
                continue
            try:
                r = elem.rect
                if isinstance(r, dict):
                    y = r.get("y", 100)
                    h = r.get("height", 20)
                    if isinstance(y, (int, float)) and 0 <= y < 55 and h < 45:
                        continue
            except Exception:
                pass
            for attr in ("label", "value", "name"):
                txt = self._cm_read_text(elem, (attr,))
                if not txt:
                    continue
                low = txt.lower()
                if "battery" in low or "charging" in low or "scroll bar" in low:
                    continue
                for m in re.finditer(r"(?<![\d.])(\d{1,3})(?:\.(\d+))?\s*%", txt):
                    whole = int(m.group(1))
                    frac = m.group(2) or ""
                    val = float(f"{whole}.{frac}") if frac else float(whole)
                    if not (0.0 <= val <= 100.0):
                        continue
                    pct = 0 if val == 0.0 else max(1, int(round(val)))
                    if "progress" in low or "download" in low or "updat" in low:
                        preferred.append((pct, txt))
                    else:
                        fallback.append((pct, txt))
        if preferred:
            return preferred[0]
        if fallback:
            return fallback[0]
        return None, ""

    def handle_ota_update(
            self,
            device_name: str,
            initial_headline: str = "",
            deadline: Optional[float] = None,
            zero_percent_timeout: Optional[float] = None,
    ) -> bool:
        """Monitor and verify GHP CameraOOBEView OTA update step (`HANDLE_OTA_UPDATE` on failure).

        Fails immediately if:
        - `OtaDownloadView` displays 'There may be a problem' or an OTA error alert,
        - OTA progress stays stuck at 0% ('Progress: 0%') longer than `zero_percent_timeout` (default 20s),
        - Overall OTA `deadline` expires while the camera is not online.
        """
        page = GHPCommissioningPageObject._resolve_page(self)
        page._cm_reset_device_name = device_name
        zero_limit = float(
            zero_percent_timeout
            if zero_percent_timeout is not None
            else getattr(
                constants, "OTA_ZERO_PERCENT_TIMEOUT_SECONDS", page.CM_OTA_ZERO_PERCENT_TIMEOUT
            )
        )
        ota_deadline = (
            deadline
            if deadline is not None
            else time.time()
                 + float(getattr(constants, "OTA_TIMEOUT_SECONDS", page.CM_OTA_DEFAULT_TIMEOUT))
        )
        start_label = initial_headline or page._cm_get_oobe_headline() or "Checking for update"
        page._logger.info(
            f"[GHP OTA] Entering OOBE OTA verification on '{start_label}' "
            f"(0% stuck threshold: {zero_limit:.0f}s)..."
        )
        zero_pct_since: Optional[float] = None
        last_zero_text = "Progress: 0%"
        empty_count = 0

        while time.time() < ota_deadline:
            alert_text = page._cm_check_oobe_error_alert()
            if alert_text:
                raise AssertionError(
                    page._cm_recover(
                        f"GHP OOBE OTA failed with alert '{alert_text}'",
                        remove_paired_device=True,
                    )
                )

            headline = page._cm_get_oobe_headline()
            if not headline:
                empty_count += 1
                if empty_count >= page.CM_OTA_EMPTY_HEADLINE_TOLERANCE:
                    page._logger.info("[GHP OTA] OTA screen cleared; returning to OOBE flow.")
                    return True
                time.sleep(page.CM_OTA_POLL_INTERVAL)
                continue
            empty_count = 0

            if _contains_any(headline, page.OTA_FAILURE_KEYWORDS) or _contains_any(
                    headline, page.GHP_FAILURE_KEYWORDS
            ):
                page._logger.error(f"[GHP OTA] Failure state detected during OTA: '{headline}'")
                BasePage.capture_failure_screenshot(
                    page.driver, reason=f"GHP OTA failed: {headline}", force=True, lock=True
                )
                raise AssertionError(
                    page._cm_recover(
                        f"GHP OOBE OTA update failed with state '{headline}'",
                        remove_paired_device=True,
                    )
                )

            if not _contains_any(headline, page.OTA_KEYWORDS):
                page._logger.info(
                    f"[GHP OTA] OOBE OTA step completed; transitioned to '{headline}'."
                )
                return True

            if _contains_any(
                    headline,
                    ("Update finished", "Installing update", "Installing", "Applying update")
            ):
                zero_pct_since = None
                page._logger.info(
                    f"[GHP OTA] OTA state: '{headline}' (waiting for reboot/transition)...")
                time.sleep(page.CM_OTA_POLL_INTERVAL)
                continue

            pct, pct_text = page._cm_read_ota_progress_percent()
            now = time.time()
            if pct is not None and pct > 0:
                zero_pct_since = None
                page._logger.info(
                    f"[GHP OTA] State: '{headline}' | Progress: {pct}% ('{pct_text}')"
                )
            elif pct == 0:
                if zero_pct_since is None:
                    zero_pct_since = now
                last_zero_text = pct_text or "Progress: 0%"
                stuck_sec = now - zero_pct_since
                page._logger.info(
                    f"[GHP OTA] State: '{headline}' | Progress: 0% ('{last_zero_text}') "
                    f"| At 0% for {stuck_sec:.1f}s / {zero_limit:.0f}s"
                )
                if stuck_sec > zero_limit:
                    reason = (
                        f"GHP OOBE OTA stuck at 0% ('{last_zero_text}') for {stuck_sec:.1f}s "
                        f"(>{zero_limit:.0f}s) on '{headline}'"
                    )
                    page._logger.error(f"[GHP OTA] {reason}")
                    BasePage.capture_failure_screenshot(
                        page.driver, reason=reason, force=True, lock=True
                    )
                    raise AssertionError(
                        page._cm_recover(reason, remove_paired_device=True)
                    )
            else:
                page._logger.info(f"[GHP OTA] Waiting on OTA state: '{headline}'...")

            time.sleep(page.CM_OTA_POLL_INTERVAL)

        last_state = page._cm_get_oobe_headline() or start_label
        timeout_reason = f"GHP OOBE OTA timed out on '{last_state}'"
        page._logger.error(f"[GHP OTA] {timeout_reason}")
        BasePage.capture_failure_screenshot(
            page.driver, reason=timeout_reason, force=False, lock=False
        )
        status = page._cm_check_device_status_on_devices_tab(device_name)
        if status == "online":
            page._logger.warning(
                f"[GHP OTA] '{device_name}' is ONLINE on GHP Devices tab after OTA timeout; continuing flow..."
            )
            BasePage.reset_failure_screenshot_state(page.driver, remove_existing=True)
            try:
                setattr(page.driver, "_commissioned_via_timeout_online", True)
            except Exception:
                pass
            return True
        if status == "offline":
            BasePage.capture_failure_screenshot(
                page.driver,
                reason=f"{timeout_reason} (device offline on Devices tab)",
                force=True,
                lock=True,
            )
            raise AssertionError(page._cm_recover(timeout_reason, remove_paired_device=True))
        raise AssertionError(page._cm_recover(timeout_reason, remove_paired_device=False))

    def _cm_handle_oobe_settings_step(self) -> bool:
        """Enable Microphone / Audio Recording toggles if off on CameraOOBEView Step 2 and tap 'Next'."""
        switches = self._cm_find_all(AppiumBy.CLASS_NAME, "XCUIElementTypeSwitch")
        if not switches:
            # Give CameraSettingsViewModel up to 1.5s to finish initializing oobeSections toggles
            time.sleep(1.5)
            switches = self._cm_find_all(AppiumBy.CLASS_NAME, "XCUIElementTypeSwitch")
        for sw in switches:
            if not self._cm_is_visible(sw):
                continue
            label = self._cm_read_text(sw, ("label", "name"))
            val = self._cm_read_text(sw, ("value",)).lower()
            if _contains_any(label, ("Microphone", "Audio Recording", "Record audio",
                                     "audio")) and val in ("0", "off"):
                self._logger.info(f"[GHP OOBE] Enabling toggle '{label}'...")
                self._cm_tap_switch_knob(sw, desc=label)
                time.sleep(0.5)

        if self._cm_find_displayed(IOS_PREDICATE_BY, self.OOBE_ERROR_ALERT_PREDICATE) is not None:
            return False

        next_btn = self._cm_find_displayed(
            IOS_PREDICATE_BY,
            'type == "XCUIElementTypeButton" AND (name == "Next" OR label == "Next")',
        )
        if next_btn is not None:
            self._logger.info("[GHP OOBE] Clicking 'Next' on Camera OOBE Settings...")
            self._cm_click_or_tap(next_btn, desc="Camera OOBE Next")
            time.sleep(1.2)
            return True
        return False

    def _cm_handle_oobe_done_step(self) -> bool:
        """Wait for camera online on CameraOOBEView Done step ('Setup complete!' / 'Camera setup complete!') and tap 'Done'."""
        self._cm_capture_oobe_navbar_device_name()
        waiting_txt = self._cm_find_displayed(
            IOS_PREDICATE_BY,
            'type == "XCUIElementTypeStaticText" AND label CONTAINS[c] "Waiting for device to be online"',
        )
        if waiting_txt is not None:
            self._logger.info("[GHP OOBE] Waiting for device to be online on OOBE Done screen...")
            time.sleep(1.5)
            return False

        done_btn = self._cm_find_displayed(
            IOS_PREDICATE_BY,
            'type == "XCUIElementTypeButton" AND (name == "Done" OR label == "Done")',
            allow_hidden=True,
        )
        if done_btn is None:
            done_btn = self._cm_find_displayed(
                IOS_PREDICATE_BY,
                'type == "XCUIElementTypeOther" AND (name == "Done" OR label == "Done")',
                allow_hidden=True,
            )

        if done_btn is None:
            return False

        enabled_attr = str(done_btn.get_attribute("enabled") or "true").lower()
        if enabled_attr == "false":
            self._logger.info(
                "[GHP OOBE] 'Done' button not yet enabled; waiting for camera online...")
            time.sleep(1.5)
            return False

        cx: Optional[int] = None
        cy: Optional[int] = None
        try:
            r = done_btn.rect
            w = float(r.get("width", 0))
            h = float(r.get("height", 0))
            if w > 0 and h > 0:
                cx = int(float(r.get("x", 0)) + w / 2.0)
                cy = int(float(r.get("y", 0)) + h / 2.0)
        except (StaleElementReferenceException, WebDriverException):
            pass

        self._logger.info("[GHP OOBE] Setup complete! Clicking 'Done'...")
        self._cm_click_or_tap(done_btn, desc="Camera OOBE Done")
        time.sleep(1.2)

        done_screen_pred = (
            'type == "XCUIElementTypeStaticText" AND ('
            'label CONTAINS[c] "setup complete" OR value CONTAINS[c] "setup complete")'
        )
        if self._cm_find_displayed(IOS_PREDICATE_BY, done_screen_pred) is not None:
            tap_x, tap_y = (cx, cy) if (cx is not None and cy is not None) else (337, 85)
            self._logger.info(
                f"[GHP OOBE] 'Setup complete!' still visible after .click(); "
                f"tapping NavigationBar 'Done' coordinates ({tap_x}, {tap_y})..."
            )
            try:
                self.driver.execute_script("mobile: tap", {"x": tap_x, "y": tap_y})
            except WebDriverException:
                pass
            time.sleep(1.5)

        return self._cm_find_displayed(IOS_PREDICATE_BY, done_screen_pred) is None

    def _cm_check_device_status_on_devices_tab(self, device_name: str) -> str:
        """Restart GHP and check whether `device_name` is 'online', 'offline', or 'missing'."""
        bundle_id = get_ghp_bundle_id()
        try:
            self.driver.terminate_app(bundle_id)
            time.sleep(1.5)
            self.driver.activate_app(bundle_id)
            time.sleep(3.0)
        except Exception:
            pass
        try:
            return GHPDevicePage._resolve_page(self).check_device_online_status(device_name,
                                                                                max_scrolls=6)
        except Exception as err:
            self._logger.warning(
                f"[Commissioning] Failed checking device status on Devices tab: {err}")
            return "missing"

    def _cm_recover(self, reason: str, remove_paired_device: bool = False) -> str:
        """Capture immediate locked failure screenshot and clean up paired camera if needed."""
        BasePage.capture_failure_screenshot(self.driver, reason=reason, force=False, lock=True)
        session = getattr(self, "session", None)
        removed_note = ""
        if remove_paired_device and session and hasattr(session,
                                                        "_emergency_recover_and_remove_device"):
            self._logger.warning(
                f"[Commissioning Recovery] Removing partially commissioned device '{self._cm_reset_device_name}'..."
            )
            ok = session._emergency_recover_and_remove_device()
            removed_note = f" | Emergency Decommission: {'SUCCESS' if ok else 'FAILED'}"
        else:
            # Dismiss any leftover modal sheet so post-test cleanup starts cleanly
            self._cm_dismiss_apple_sheet_if_open()
        return f"{reason}{removed_note}"

    def complete_commissioning_and_pairing_flow(
            self, device_name: str, room_name: str = "Attic", timeout: float = 600.0
    ) -> bool:
        """Complete Apple Matter sheets and GHP CameraOOBEView (OTA + Settings + Done)."""
        page = GHPCommissioningPageObject._resolve_page(self)
        page._logger.info(
            f"[Commissioning] Starting GHP commissioning & OOBE flow for '{device_name}' (timeout {int(timeout)}s)..."
        )
        page._cm_reset_device_name = device_name
        page._cm_resolved_tile_name = device_name
        page._cm_named_in_current_flow = False
        page._cm_named_card_titles = set()
        page._cm_picker_preferred_method = ""
        page._cm_apple_done_clicked_at = 0.0
        page._cm_last_apple_card_title = ""
        page._cm_springboard_failure_title = ""
        try:
            setattr(page.driver, "_commissioned_via_timeout_online", False)
            setattr(page.driver, "_ghp_commissioned_tile_name", None)
        except Exception:
            pass

        start_time = time.time()
        apple_sheet_seen = False

        try:
            while time.time() - start_time < timeout:
                # 1. Handle Apple Matter system sheets while open
                if page.handle_apple_commissioning_sheet(device_name, room_name=room_name):
                    apple_sheet_seen = True
                    continue

                if apple_sheet_seen and page._cm_apple_done_clicked_at == 0.0:
                    page._cm_apple_done_clicked_at = time.time()

                # 2. Check GHP / OOBE error alerts & snackbar failures
                alert_err = page._cm_check_oobe_error_alert()
                if alert_err:
                    raise AssertionError(
                        page._cm_recover(
                            f"GHP Camera OOBE failed with error alert: '{alert_err}'",
                            remove_paired_device=True,
                        )
                    )

                ghp_fail = page._cm_detect_ghp_failure_text()
                if ghp_fail:
                    BasePage.capture_failure_screenshot(
                        page.driver, reason=ghp_fail, force=True, lock=True
                    )
                    raise AssertionError(
                        page._cm_recover(
                            f"GHP commissioning failed: '{ghp_fail}'",
                            remove_paired_device=False,
                        )
                    )

                # 3. Inspect GHP CameraOOBEView state
                headline = page._cm_get_oobe_headline()
                if headline:
                    page._logger.info(
                        f"[{int(time.time() - start_time)}s] GHP OOBE State: '{headline}'"
                    )
                    if _contains_any(headline, page.OTA_KEYWORDS) or _contains_any(
                            headline, page.OTA_FAILURE_KEYWORDS
                    ):
                        page.handle_ota_update(
                            device_name=device_name,
                            initial_headline=headline,
                            deadline=start_time + timeout,
                        )
                        if getattr(page.driver, "_commissioned_via_timeout_online", False):
                            return True
                        continue

                    if _contains_any(
                            headline,
                            ("Setup complete", "Camera setup complete",
                             "Waiting for device to be online"),
                    ):
                        if page._cm_handle_oobe_done_step():
                            page._logger.info("[Commissioning] GHP Camera OOBE completed!")
                            return True
                        continue

                    if _contains_any(
                            headline,
                            ("Microphone Settings", "Adjust your mic settings",
                             "Camera OOBE Settings"),
                    ):
                        page._cm_handle_oobe_settings_step()
                        continue

                # 4. Also check if CameraOOBEView 'Done' screen ('Setup complete!') is directly visible
                if (
                        page._cm_find_displayed(
                            IOS_PREDICATE_BY,
                            'type == "XCUIElementTypeStaticText" AND ('
                            'label CONTAINS[c] "setup complete" OR value CONTAINS[c] "setup complete")',
                        )
                        is not None
                ):
                    if page._cm_handle_oobe_done_step():
                        page._logger.info("[Commissioning] GHP Camera OOBE completed!")
                        return True

                # 5. Fallback for builds where Apple 'Done' returns directly to GHP Devices tab
                if (
                        page._cm_apple_done_clicked_at > 0
                        and (time.time() - page._cm_apple_done_clicked_at)
                        >= page.CM_POST_APPLE_OOBE_GRACE_SECONDS
                ):
                    dev_page = GHPDevicePage._resolve_page(page)
                    if dev_page._is_tab_bar_visible():
                        hit = dev_page._locate_device_tile_with_scroll(device_name, max_scrolls=4)
                        if hit is not None:
                            _tile, found_title, found_status = hit
                            if not any(
                                    kw in found_status.lower() for kw in
                                    dev_page.OFFLINE_STATUS_KEYWORDS
                            ):
                                page._logger.info(
                                    f"[Commissioning] '{found_title}' is present on GHP Devices tab "
                                    f"(status='{found_status}'). Commissioning complete!"
                                )
                                return True

                time.sleep(page.CM_POLL_INTERVAL)

            # Overall commissioning timeout -> inspect Devices tab just like GHA
            timeout_reason = f"GHP Commissioning timed out after {int(timeout)}s"
            page._logger.error(f"[Commissioning] {timeout_reason}")
            BasePage.capture_failure_screenshot(
                page.driver, reason=timeout_reason, force=False, lock=False
            )
            dev_status = page._cm_check_device_status_on_devices_tab(device_name)
            if dev_status == "online":
                page._logger.warning(
                    f"[Commissioning] '{device_name}' is ONLINE on GHP Devices tab after {int(timeout)}s timeout; "
                    "continuing test flow..."
                )
                BasePage.reset_failure_screenshot_state(page.driver, remove_existing=True)
                try:
                    setattr(page.driver, "_commissioned_via_timeout_online", True)
                except Exception:
                    pass
                return True
            if dev_status == "offline":
                BasePage.capture_failure_screenshot(
                    page.driver,
                    reason=f"{timeout_reason} (device offline on Devices tab)",
                    force=True,
                    lock=True,
                )
                raise AssertionError(page._cm_recover(timeout_reason, remove_paired_device=True))
            raise AssertionError(page._cm_recover(timeout_reason, remove_paired_device=False))

        except _GHPApiAppleSheetFailure as apple_exc:
            raise AssertionError(
                page._cm_recover(apple_exc.reason, remove_paired_device=False)
            ) from None
        except AssertionError:
            raise
        except Exception as exc:
            page._logger.error(f"[Commissioning] Unexpected exception: {exc}")
            msg = page._cm_recover(
                f"GHP Commissioning failed with unexpected exception: {exc}",
                remove_paired_device=apple_sheet_seen,
            )
            raise AssertionError(msg) from exc

    # -------------------------------------------------------------------------
    # 5. Smart Plug Power-Cycle (Must Enter Plug Detail Page to Toggle Switch!)
    # -------------------------------------------------------------------------
    def _cm_tap_switch_knob(self, switch_elem: WebElement, desc: str = "Switch") -> bool:
        """Tap the actual UISwitch thumb on the right side of a SwiftUI Toggle row."""
        try:
            rect = switch_elem.rect
            width = rect.get("width", 0)
            height = rect.get("height", 29)
            if width > 110:
                knob_x = int(rect["x"] + width - 31)
            else:
                knob_x = int(rect["x"] + width / 2)
            knob_y = int(rect["y"] + height / 2)
            self.driver.execute_script("mobile: tap", {"x": knob_x, "y": knob_y})
            return True
        except WebDriverException as err:
            self._logger.debug(f"Knob coordinate tap failed on {desc} ({err}); trying click()...")
            try:
                switch_elem.click()
                return True
            except WebDriverException:
                return False

    def _cm_ensure_devices_tab_ready(self) -> bool:
        """Ensure iOS screen is unlocked and GHP is in the foreground on the Devices tab."""
        bundle_id = get_ghp_bundle_id()
        try:
            if hasattr(self.driver, "is_locked") and self.driver.is_locked() is True:
                self._unlock_device_if_locked()
        except Exception:
            pass
        try:
            if hasattr(self.driver, "query_app_state") and self.driver.query_app_state(
                    bundle_id) != 4:
                self.driver.activate_app(bundle_id)
                time.sleep(2.0)
        except Exception:
            pass
        GHPDevicePage._resolve_page(self).go_to_tab("Devices")
        return True

    @staticmethod
    def _cm_build_plug_predicate(keywords: Sequence[str]) -> str:
        clauses: List[str] = []
        seen = set()
        for kw in keywords:
            clean = kw.strip().replace('"', '\\"')
            if not clean or clean.lower() in seen:
                continue
            seen.add(clean.lower())
            clauses.append(f'name CONTAINS[c] "{clean}" OR label CONTAINS[c] "{clean}"')
        filt = " OR ".join(
            clauses) if clauses else 'name CONTAINS[c] "Plug" OR label CONTAINS[c] "Plug"'
        return f'type == "XCUIElementTypeButton" AND ({filt})'

    def _cm_discover_plugs(self, keywords: Sequence[str], max_scrolls: int = 4) -> List[str]:
        """Discover unique plug tile names on the GHP Devices tab matching `keywords`."""
        dev_page = GHPDevicePage._resolve_page(self)
        predicate = self._cm_build_plug_predicate(keywords)
        found: List[str] = []

        for step in range(max_scrolls + 1):
            for btn in self._cm_find_all(IOS_PREDICATE_BY, predicate):
                if not self._cm_is_visible(btn):
                    continue
                try:
                    r = btn.rect
                    if r.get("y", 0) < 80 or r.get("y", 0) >= 750:
                        continue
                except WebDriverException:
                    continue
                title, _status = dev_page._split_tile_name_and_status(btn)
                if title and _contains_any(title, keywords) and title not in found:
                    found.append(title)
            if found or step == max_scrolls:
                break
            dev_page._scroll_devices_list("down")
        return found

    def _cm_find_plug_detail_switches(self) -> Tuple[Optional[WebElement], Optional[WebElement]]:
        """Return (outer_switch, inner_knob_switch) on the GHP Plug Detail Page."""
        switches = self._cm_find_all(AppiumBy.CLASS_NAME, "XCUIElementTypeSwitch")
        outer: Optional[WebElement] = None
        inner_knob: Optional[WebElement] = None
        for sw in switches:
            try:
                r = sw.rect
                w = r.get("width", 0)
            except WebDriverException:
                w = 0
            label = self._cm_read_text(sw, ("label", "name"))
            if w > 110 or label.lower().startswith("switch"):
                if outer is None:
                    outer = sw
            else:
                if inner_knob is None:
                    inner_knob = sw
        if outer is None and switches:
            outer = switches[0]
        return outer, inner_knob

    def _cm_read_plug_detail_switch_state(self) -> Optional[str]:
        """Read 'on' or 'off' from the Switch control inside the GHP Plug Detail Page."""
        outer, inner = self._cm_find_plug_detail_switches()
        for candidate in (outer, inner):
            if candidate is None:
                continue
            val = self._cm_read_text(candidate, ("value",)).lower()
            if val in ("1", "true", "on"):
                return "on"
            if val in ("0", "false", "off"):
                return "off"
            lbl = self._cm_read_text(candidate, ("label", "name")).lower()
            if lbl.endswith(", on") or lbl == "on":
                return "on"
            if lbl.endswith(", off") or lbl == "off":
                return "off"
        return None

    def _cm_open_plug_detail_page(self, plug_name: str) -> bool:
        """Locate `plug_name` on the Devices tab, tap it, and verify the Plug Detail Page opens."""
        dev_page = GHPDevicePage._resolve_page(self)
        hit = dev_page._locate_device_tile_with_scroll(plug_name, max_scrolls=6)
        if hit is None:
            self._logger.warning(
                f"[PowerCycle] Could not find plug tile '{plug_name}' on Devices tab.")
            return False

        tile, title, status = hit
        tile = dev_page._ensure_tile_in_safe_tap_zone(tile, title)
        for attempt in range(1, 3):
            self._logger.info(
                f"[PowerCycle] Entering detail page for plug '{title}' (status='{status}', attempt {attempt}/2)..."
            )
            self._cm_click_or_tap(tile, desc=f"Plug tile '{title}'")
            deadline = time.time() + 6.0
            while time.time() < deadline:
                if self._cm_read_plug_detail_switch_state() is not None:
                    return True
                time.sleep(0.4)
            fresh = dev_page._find_visible_tile_for_name(title)
            if fresh is not None:
                tile = fresh[0]
        self._logger.error(
            f"[PowerCycle] Plug detail page (Switch control) did not open for '{plug_name}'.")
        return False

    def _cm_toggle_plug_detail_switch(self, plug_name: str, target_off: bool) -> bool:
        """Toggle the `Switch` inside the Plug Detail Page to OFF or ON and verify state flipped."""
        expected = "off" if target_off else "on"
        target_label = "OFF" if target_off else "ON"

        for attempt in range(1, 4):
            current = self._cm_read_plug_detail_switch_state()
            if current == expected:
                self._logger.info(
                    f"[PowerCycle] '{plug_name}' detail Switch confirmed {target_label}!"
                )
                return True

            outer, inner = self._cm_find_plug_detail_switches()
            target_sw = inner if (inner is not None and attempt == 1) else (outer or inner)
            if target_sw is None:
                self._logger.warning(
                    f"[PowerCycle] Switch control missing on '{plug_name}' detail page.")
                return False

            self._logger.info(
                f"[PowerCycle] Toggling '{plug_name}' detail Switch -> {target_label} (attempt {attempt}/3)..."
            )
            if attempt <= 2:
                self._cm_tap_switch_knob(outer or target_sw, desc=f"{plug_name} Switch")
            else:
                self._cm_click_or_tap(target_sw, desc=f"{plug_name} Switch")
            time.sleep(1.5)

        final_state = self._cm_read_plug_detail_switch_state()
        if final_state == expected:
            self._logger.info(f"[PowerCycle] '{plug_name}' detail Switch confirmed {target_label}!")
            return True
        self._logger.warning(
            f"[PowerCycle] '{plug_name}' detail Switch state is '{final_state}' after 3 attempts (expected {target_label})."
        )
        return False

    def _cm_exit_plug_detail_page(self) -> None:
        """Click '< Home' (`BackButton`) on the Plug Detail Page to return to the Devices tab."""
        back_btn = self._cm_find_displayed(
            IOS_PREDICATE_BY,
            'type == "XCUIElementTypeButton" AND ('
            'name == "BackButton" OR label == "Home" OR name == "Back" OR label == "Back" '
            'OR name == "Done" OR label == "Done")',
        )
        if back_btn is not None:
            self._cm_click_or_tap(back_btn, desc="Plug Detail BackButton")
            time.sleep(1.0)
        GHPDevicePage._resolve_page(self).go_to_tab("Devices")

    def _cm_power_cycle_one_plug(self, plug_name: str, off_wait: float, on_wait: float) -> bool:
        """Open `plug_name` detail page, toggle Switch OFF -> wait -> ON -> wait, then go back."""
        if not self._cm_ensure_devices_tab_ready():
            return False
        if not self._cm_open_plug_detail_page(plug_name):
            return False

        try:
            initial = self._cm_read_plug_detail_switch_state()
            self._logger.info(
                f"[PowerCycle] '{plug_name}' detail Switch initial state: '{initial}'")
            if initial != "off":
                self._logger.info(
                    f"[PowerCycle] Switching OFF '{plug_name}' and waiting {off_wait:.1f}s..."
                )
                if not self._cm_toggle_plug_detail_switch(plug_name, target_off=True):
                    return False
                time.sleep(off_wait)

            self._logger.info(
                f"[PowerCycle] Switching ON '{plug_name}' and waiting {on_wait:.1f}s for boot..."
            )
            if not self._cm_toggle_plug_detail_switch(plug_name, target_off=False):
                return False
            time.sleep(on_wait)
            return True
        finally:
            self._cm_exit_plug_detail_page()

    def power_cycle_smart_plug(
            self,
            keywords: Optional[Sequence[str]] = None,
            off_wait: float = 5.0,
            on_wait: float = 8.0,
    ) -> bool:
        """Restart GHP, discover smart plugs, and power-cycle each by entering its detail page."""
        page = GHPCommissioningPageObject._resolve_page(self)
        bundle_id = get_ghp_bundle_id()
        search_keywords = tuple(keywords or page.DEFAULT_PLUG_KEYWORDS)

        page._logger.info(
            f"[PowerCycle] Restarting GHP Sample App ('{bundle_id}') and navigating to Devices tab..."
        )
        try:
            page.driver.terminate_app(bundle_id)
            time.sleep(1.5)
        except Exception:
            pass
        try:
            page.driver.activate_app(bundle_id)
            time.sleep(3.0)
        except Exception as err:
            page._logger.error(f"[PowerCycle] Failed to relaunch GHP Sample App: {err}")
            return False

        page._cm_ensure_devices_tab_ready()
        plugs = page._cm_discover_plugs(search_keywords)
        if not plugs:
            page._logger.error(
                f"[PowerCycle] No smart plug found on GHP Devices tab matching {list(search_keywords)}."
            )
            return False

        page._logger.info(
            f"[PowerCycle] Found {len(plugs)} smart plug(s) {plugs}. Entering each plug's detail page to toggle OFF -> ON..."
        )
        results: List[bool] = []
        for idx, plug_name in enumerate(plugs, start=1):
            page._logger.info(f"[PowerCycle] [{idx}/{len(plugs)}] Power-cycling '{plug_name}'...")
            results.append(
                page._cm_power_cycle_one_plug(plug_name, off_wait=off_wait, on_wait=on_wait))

        page._logger.info(
            f"[PowerCycle] Completed: {sum(results)}/{len(plugs)} smart plug(s) power-cycled."
        )
        return all(results)
