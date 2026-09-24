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
from page_object.iGHA.gha_connect_device_to_google_account_page import GHAConnectDeviceToGoogleAccountPage
from page_object.iGHA.gha_device_connected_page import GHADeviceConnectedPage
from page_object.iGHA.gha_tab_page import GHATabPage
from page_object.iGHA.gha_watch_setup_video_page import GHAWatchSetupVideoPage
from page_object.iGHA.gha_where_is_this_device_page import GHAWhereIsThisDevicePage
from page_object.iGHA.gha_you_should_now_see_live_video_page import GHAYouShouldNowSeeLiveVideoPage


Locator = Tuple[str, str]
HeadlineHandler = Callable[[str], bool]

def _contains_any(text: str, keywords: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(kw.lower() in lowered for kw in keywords)

class GHACommissioningPageObject(BasePage):
    """Unified handler for Apple Matter system sheets and Google Home App commissioning steps.
    NOTE: Private helpers are prefixed with `_cm_` to avoid MRO name collisions in GHASession.
    """
    HEADLINE_LOCATOR: Locator = (AppiumBy.ACCESSIBILITY_ID, constants.GHA_CONNECTING_TITLE_ACCESSIBILITY_ID)
    APPLE_OVERLAY_WINDOW_CHAIN = '**/XCUIElementTypeWindow[`name == "SBTransientOverlayWindow" AND visible == 1`]'
    APPLE_CARD_TITLE_CHAIN = f'{APPLE_OVERLAY_WINDOW_CHAIN}/**/XCUIElementTypeTextView[`visible == 1`]'
    APPLE_TEXT_FIELD_CHAIN = f'{APPLE_OVERLAY_WINDOW_CHAIN}/**/XCUIElementTypeTextField[`visible == 1`]'
    APPLE_ADD_BTN_CHAIN = (
        f'{APPLE_OVERLAY_WINDOW_CHAIN}/**/'
        'XCUIElementTypeButton[`name CONTAINS "Add to" OR label CONTAINS "Add to"`]'
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
    DEVICE_TILE_CELL: Locator = (AppiumBy.IOS_PREDICATE, 'type == "XCUIElementTypeCell" AND name CONTAINS "deviceTileCell"')
    SYSTEM_ALERT_BUTTONS = ("Add Anyway", "Set up anyway", "OK", "Allow")
    FAILURE_KEYWORDS = (
        "Can’t connect", "Can't connect", "Couldn't connect", "Could not connect", "Unable to connect",
        "Something went wrong", "Check your connection", "Device not found", "Setup failed",
    )
    PROGRESS_KEYWORDS = (
        "Adding device", "Getting your device ready", "Next, your device will be added", "Connecting",
        "Setting up", "Activating camera", "Downloading update", "Update finished",
    )
    DEFAULT_PLUG_KEYWORDS = ("plug", "outlet")
    PLUG_ON_VALUES = ("on", "1", "true")
    PLUG_OFF_VALUES = ("off", "0", "false")
    CM_POLL_INTERVAL = 1.5
    CM_PROGRESS_INTERVAL = 2.5

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

    def _cm_find_all(self, by: str, value: str, root: Optional[WebElement] = None) -> List[WebElement]:
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
            return self.driver.query_app_state(constants.GHA_BUNDLE_ID) == constants.APP_STATE_FOREGROUND
        except WebDriverException as e:
            self._logger.error(f"Failed to query GHA app state: {e}")
            return False
    def stop_gha(self) -> bool:
        """Terminate the GHA application."""
        try:
            if self.driver.query_app_state(constants.GHA_BUNDLE_ID) == constants.APP_STATE_NOT_RUNNING:
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
        return self._cm_find_displayed(AppiumBy.IOS_CLASS_CHAIN, self.APPLE_OVERLAY_WINDOW_CHAIN) is not None

    def handle_system_alert(self) -> bool:
        """Dismiss iOS system alerts like 'Uncertified Accessory'."""
        if self._cm_find_displayed(AppiumBy.CLASS_NAME, constants.GHA_COMMISSION_WINDOW_ALERT) is None:
            return False
        self._logger.warning("Detected iOS System Alert dialog!")
        for btn_text in self.SYSTEM_ALERT_BUTTONS:
            if self._cm_click_displayed(AppiumBy.ACCESSIBILITY_ID, btn_text):
                self._logger.info(f"Dismissed system alert via '{btn_text}'.")
                return True
        return False

    def _cm_get_apple_card_title(self) -> str:
        for _ in range(3):
            elem = self._cm_find_displayed(AppiumBy.IOS_CLASS_CHAIN, self.APPLE_CARD_TITLE_CHAIN)
            if elem is not None:
                title = self._cm_read_text(elem, ("name", "label", "value"))
                if title:
                    return title
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
        self._logger.error(f"[AppleSheet] Reported failure: '{card_title}'")
        self._cm_click_apple_sheet_button("OK", "Done")
        time.sleep(1.5)
        self._cm_recover_and_fail(f"Apple sheet failed with '{card_title}'")

    def _cm_on_apple_bridge_name(self, device_name: str) -> None:
        self._logger.info(f"[AppleSheet] Naming step detected. Setting device name to '{device_name}'...")
        field = (
                self._cm_find_displayed(AppiumBy.IOS_CLASS_CHAIN, self.APPLE_TEXT_FIELD_CHAIN)
                or self._cm_find_displayed(AppiumBy.CLASS_NAME, constants.GHA_TEXT_EDIT_VIEW_CLASS_NAME)
        )
        if field is None:
            self._logger.debug("[AppleSheet] Name field not found yet (sheet transitioning).")
            return
        try:
            field.clear()
            time.sleep(0.5)
            field.send_keys(device_name)
            time.sleep(0.5)
        except WebDriverException as e:
            self._logger.debug(f"[AppleSheet] Naming field transition: {e}")
            return
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

    def handle_apple_commissioning_sheet(self, device_name: str) -> bool:
        """Observe and act on the foreground Apple Matter sheet.
        Returns:
            True if a system alert / Apple sheet was present (and handled), False otherwise.
        Raises:
            AssertionError: If the Apple sheet reports 'Unable to Add Accessory'.
        """
        try:
            if self.handle_system_alert():
                time.sleep(1.0)
                return True
            if not self.is_apple_sheet_present():
                return False
            card_title = self._cm_get_apple_card_title()
            if not card_title:
                return True
            self._logger.info(f"[AppleSheet] Active card: '{card_title}'")
            if _contains_any(card_title, ("added to",)):
                self._cm_on_apple_added()
            elif _contains_any(card_title, ("unable to add accessory",)):
                self._cm_on_apple_failure(card_title)
            elif "Bridge Name" in card_title:
                self._cm_on_apple_bridge_name(device_name)
            elif not self._cm_click_apple_add_button():
                self._logger.info(f"[AppleSheet] In progress: '{card_title}'... Waiting.")
                time.sleep(2.0)
            return True
        except AssertionError:
            raise
        except WebDriverException as e:
            self._logger.debug(f"[AppleSheet] Transition in progress ({e.__class__.__name__}). Retrying...")
            time.sleep(1.0)
            return True

    def _cm_dismiss_commissioning_and_go_to_devices(self) -> None:
        """Dismiss error dialogs / setup screens and return GHA to the Devices tab."""
        self._logger.info("[Recovery] Dismissing commissioning screens and returning to Devices tab...")
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

    def _cm_recover_and_fail(self, reason: str) -> NoReturn:
        """Dismiss commissioning screens, power-cycle smart plugs, then raise."""
        self._cm_dismiss_commissioning_and_go_to_devices()
        cycle_ok = self.power_cycle_smart_plug()
        raise AssertionError(
            f"FATAL: {reason}. Smart plug power-cycle: {'SUCCESS' if cycle_ok else 'FAILED'}."
        )

    def _cm_tile_identity(self, tile: WebElement) -> str:
        """Human-readable device name of a tile (title text > first part of label > name)."""
        titles = self._cm_find_all(*self.DEVICE_TILE_TITLE, root=tile)
        if titles:
            title = self._cm_read_text(titles[0], ("value",))
            if title:
                return title
        label = self._cm_read_text(tile, ("label",))
        return label.split(",")[0].strip() if label else self._cm_read_text(tile, ("name",))

    def _cm_is_plug(self, elem: WebElement, keywords: Sequence[str]) -> bool:
        text = " ".join(self._cm_read_text(elem, (attr,)) for attr in ("label", "value", "name"))
        return _contains_any(text, keywords)

    def _cm_discover_plugs(self, keywords: Sequence[str]) -> List[str]:
        """Collect unique names of plug/outlet tiles on the Devices tab (scrolls once if needed)."""
        found: List[str] = []
        for attempt in range(2):
            candidates = self._cm_find_all(*self.DEVICE_TILE) + self._cm_find_all(*self.DEVICE_TILE_CELL)
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
        """Freshly locate a plug tile by name (avoids stale references)."""
        target = target_name.lower()
        for tile in self._cm_find_all(*self.DEVICE_TILE):
            try:
                if target in self._cm_tile_identity(tile).lower() or \
                        target in self._cm_read_text(tile, ("label",)).lower():
                    return tile
            except WebDriverException:
                continue
        for cell in self._cm_find_all(*self.DEVICE_TILE_CELL):
            if target in self._cm_read_text(cell, ("label",)).lower():
                inner = self._cm_find_all(*self.DEVICE_TILE, root=cell)
                return inner[0] if inner else cell
        return None

    def _cm_power_cycle_one(self, plug_name: str, off_wait: float, on_wait: float) -> bool:
        """Turn a plug OFF (if not already), wait, then turn it back ON."""
        tile = self._cm_locate_plug_tile(plug_name)
        if tile is None:
            self._logger.warning(f"[PowerCycle] Could not locate '{plug_name}'. Skipping.")
            return False
        state = self._cm_read_text(tile, ("value",)).lower()
        self._logger.info(f"[PowerCycle] '{plug_name}' initial state: '{state or 'unknown'}'")
        try:
            if state not in self.PLUG_OFF_VALUES:
                self._logger.info(f"[PowerCycle] Turning OFF '{plug_name}', waiting {off_wait}s...")
                tile.click()
                time.sleep(off_wait)
                tile = self._cm_locate_plug_tile(plug_name) or tile
            self._logger.info(f"[PowerCycle] Turning ON '{plug_name}', waiting {on_wait}s for boot...")
            tile.click()
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
            self._logger.error(f"[PowerCycle] No smart plug/outlet found matching {list(keywords)}.")
            return False
        self._logger.info(f"[PowerCycle] Found {len(plugs)} plug(s): {plugs}. Power-cycling sequentially...")
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
            self._logger.warning(f"select_room_or_add_custom error: {e}. Falling back to first visible cell...")
            cells = self._cm_find_all(AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeCell[`visible == 1`]')
            if cells:
                cells[0].click()
            self._cm_click_displayed(AppiumBy.ACCESSIBILITY_ID, constants.GHA_NEXT_BTN_ACCESSIBILITY_ID)
        time.sleep(1.0)
        return False

    def _cm_on_device_connected(self, _headline: str) -> bool:
        self._logger.info("Device connected! Clicking Done...")
        try:
            GHADeviceConnectedPage(self.driver).click_done_btn()
        except Exception:
            self._cm_click_displayed(AppiumBy.ACCESSIBILITY_ID, constants.GHA_DONE_BTN_ACCESSIBILITY_ID)
        return False

    def _cm_on_camera_activated(self, headline: str) -> bool:
        self._logger.info(f"Device paired and transitioned to '{headline}'!")
        GHACameraActivatedPage(self.driver).handle_camera_activated_page_process()
        return False

    def _cm_on_live_video(self, headline: str) -> bool:
        self._logger.info(f"Device paired and transitioned to '{headline}'!")
        GHAYouShouldNowSeeLiveVideoPage(self.driver).handle_you_should_now_see_live_video_page_process()
        return True

    def _cm_on_uncertified_warning(self, headline: str) -> bool:
        self._logger.warning(f"Encountered warning: '{headline}'. Clicking 'Set up anyway'...")
        if not self._cm_click_displayed(AppiumBy.ACCESSIBILITY_ID, "Set up anyway"):
            self._cm_click_displayed(AppiumBy.ACCESSIBILITY_ID, "Exit")
        time.sleep(2.0)
        return False

    def _cm_build_headline_handlers(self, room_name: str) -> List[Tuple[Tuple[str, ...], HeadlineHandler]]:
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
            self, device_name: str, room_name: str = "Attic", timeout: float = 300
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
                (after dismissing screens and power-cycling smart plugs).
        """
        self._logger.info(f"[Commissioning] Starting flow for '{device_name}' (timeout {int(timeout)}s)...")
        handlers = self._cm_build_headline_handlers(room_name)
        start_time = time.time()
        apple_sheet_active = False
        try:
            while time.time() - start_time < timeout:
                if self.handle_apple_commissioning_sheet(device_name):
                    apple_sheet_active = True
                    continue
                if apple_sheet_active:
                    self._logger.info("[Commissioning] Apple sheet dismissed. Back in GHA foreground.")
                    apple_sheet_active = False
                    time.sleep(1.0)
                headline = self._cm_get_headline()
                if not headline:
                    time.sleep(self.CM_POLL_INTERVAL)
                    continue
                self._logger.info(f"[{int(time.time() - start_time)}s] GHA Headline: '{headline}'")
                if _contains_any(headline, self.FAILURE_KEYWORDS):
                    self._logger.error(f"[Commissioning] Failure headline detected: '{headline}'")
                    self._cm_recover_and_fail(f"Commissioning failed with headline '{headline}'")
                if _contains_any(headline, self.PROGRESS_KEYWORDS):
                    self._logger.info(f"Waiting for GHA background progress: '{headline}'...")
                    time.sleep(self.CM_PROGRESS_INTERVAL)
                    continue
                handler = next((h for kws, h in handlers if _contains_any(headline, kws)), None)
                if handler is None:
                    time.sleep(self.CM_POLL_INTERVAL)
                    continue
                if handler(headline):
                    self._logger.info("[Commissioning] Flow completed successfully.")
                    return True
            self._logger.error(f"[Commissioning] Flow timed out after {int(timeout)}s!")
            self._cm_recover_and_fail(f"Commissioning timed out after {int(timeout)}s")
        except AssertionError:
            raise
        except Exception as e:
            self._logger.error(f"[Commissioning] Unexpected exception: {e}")
            try:
                self._cm_dismiss_commissioning_and_go_to_devices()
                self.power_cycle_smart_plug()
            except Exception as recovery_err:
                self._logger.warning(f"[Commissioning] Recovery error: {recovery_err}")
            raise AssertionError(f"Commissioning flow failed with unexpected exception: {e}") from e