"""Page object for handling Matter device commissioning and iOS system sheets with StaleElement resilience."""
import time
from typing import Optional, List
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import (
    WebDriverException,
    StaleElementReferenceException,
    NoSuchElementException,
    TimeoutException
)
from appium.webdriver.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from common import constants
from common.base_page import BasePage
from page_object.iGHA.gha_where_is_this_device_page import GHAWhereIsThisDevicePage
from page_object.iGHA.gha_device_connected_page import GHADeviceConnectedPage
from page_object.iGHA.gha_camera_activated_page import GHACameraActivatedPage
from page_object.iGHA.gha_you_should_now_see_live_video_page import GHAYouShouldNowSeeLiveVideoPage
from page_object.iGHA.gha_watch_setup_video_page import GHAWatchSetupVideoPage
from page_object.iGHA.gha_connect_device_to_google_account_page import GHAConnectDeviceToGoogleAccountPage


class GHACommissioningPageObject(BasePage):
    """Unified handler for Apple Matter system sheets and Google Home App commissioning steps."""

    HEADLINE_LOCATOR = (AppiumBy.ACCESSIBILITY_ID, constants.GHA_CONNECTING_TITLE_ACCESSIBILITY_ID)

    APPLE_OVERLAY_WINDOW_CHAIN = '**/XCUIElementTypeWindow[`name == "SBTransientOverlayWindow" AND visible == 1`]'

    APPLE_CARD_TITLE_CHAIN = (
        '**/XCUIElementTypeWindow[`name == "SBTransientOverlayWindow" AND visible == 1`]/**/XCUIElementTypeTextView[`visible == 1`]'
    )

    APPLE_TEXT_FIELD_CHAIN = (
        '**/XCUIElementTypeWindow[`name == "SBTransientOverlayWindow" AND visible == 1`]/**/XCUIElementTypeTextField[`visible == 1`]'
    )

    def is_apple_sheet_present(self) -> bool:
        """Check if Apple's native Matter commissioning sheet (SBTransientOverlayWindow) is currently visible."""
        try:
            self.driver.implicitly_wait(0)
            windows = self.driver.find_elements(AppiumBy.IOS_CLASS_CHAIN, self.APPLE_OVERLAY_WINDOW_CHAIN)
            for w in windows:
                try:
                    if w.is_displayed():
                        return True
                except (StaleElementReferenceException, WebDriverException):
                    continue
        except Exception:
            pass
        return False

    def _get_gha_headline(self) -> str:
        """Fetch the current GHA page headline text via HeaderView_headlineLabel."""
        try:
            self.driver.implicitly_wait(0)
            elements = self.driver.find_elements(*self.HEADLINE_LOCATOR)
            for elem in elements:
                try:
                    if elem.is_displayed():
                        text = elem.get_attribute("value") or elem.get_attribute("label") or elem.text
                        if text and text.strip():
                            return text.strip()
                except (StaleElementReferenceException, WebDriverException):
                    continue
        except Exception:
            pass
        return ""

    def _click_if_visible(self, by: AppiumBy, value: str) -> bool:
        """Safely click an element if it exists and is displayed."""
        try:
            self.driver.implicitly_wait(0)
            elements = self.driver.find_elements(by=by, value=value)
            for elem in elements:
                try:
                    if elem.is_displayed():
                        elem.click()
                        return True
                except (StaleElementReferenceException, WebDriverException):
                    continue
        except Exception:
            pass
        return False

    def _click_apple_sheet_button(self, name_or_label: str) -> bool:
        """Click a button located specifically within SBTransientOverlayWindow."""
        chain = (
            f'**/XCUIElementTypeWindow[`name == "SBTransientOverlayWindow" AND visible == 1`]/**/'
            f'XCUIElementTypeButton[`name == "{name_or_label}" OR label == "{name_or_label}"`]'
        )
        try:
            self.driver.implicitly_wait(0)
            buttons = self.driver.find_elements(AppiumBy.IOS_CLASS_CHAIN, chain)
            for btn in buttons:
                try:
                    if btn.is_displayed():
                        btn.click()
                        return True
                except (StaleElementReferenceException, WebDriverException):
                    continue
        except Exception:
            pass
        return False

    def handle_system_alert(self) -> bool:
        """Handle iOS system alerts like 'Uncertified Accessory', 'Bridge Accessories Can Automatically Add'."""
        try:
            self.driver.implicitly_wait(0)
            alerts = self.driver.find_elements(AppiumBy.CLASS_NAME, constants.GHA_COMMISSION_WINDOW_ALERT)
            if alerts and alerts[0].is_displayed():
                self._logger.warning("Detected iOS System Alert dialog!")
                for btn_text in ["Add Anyway", "Set up anyway", "OK", "Allow"]:
                    if self._click_if_visible(AppiumBy.ACCESSIBILITY_ID, btn_text):
                        self._logger.info(f"Dismissed system alert via '{btn_text}'.")
                        return True
        except Exception:
            pass
        return False

    def _get_apple_card_title(self) -> str:
        """Safely fetch Apple sheet card title strictly from inside SBTransientOverlayWindow."""
        for _ in range(3):
            try:
                self.driver.implicitly_wait(0)
                titles = self.driver.find_elements(AppiumBy.IOS_CLASS_CHAIN, self.APPLE_CARD_TITLE_CHAIN)
                for t in titles:
                    try:
                        if t.is_displayed():
                            name = t.get_attribute("name") or t.get_attribute("label") or t.text or ""
                            if name.strip():
                                return name.strip()
                    except (StaleElementReferenceException, WebDriverException):
                        break
            except (StaleElementReferenceException, WebDriverException):
                pass
                time.sleep(0.4)
        return ""

    def _find_element(self, by: AppiumBy, locator_value: str) -> Optional[WebElement]:
        """Find an element using specified locator strategy with explicit wait."""
        try:
            return WebDriverWait(self.driver, 3.0).until(
                EC.presence_of_element_located((by, locator_value))
            )
        except TimeoutException:
            self._logger.error(f"Timed out waiting for element: by={by}, value='{locator_value}'")
            return None

    def _click_if_exists(self, by: AppiumBy, value: str) -> bool:
        """Safely find and click an element if it exists and is displayed (Never throws)."""
        try:
            elements = self.driver.find_elements(by=by, value=value)
            if elements and elements[0].is_displayed():
                elements[0].click()
                return True
        except (NoSuchElementException, StaleElementReferenceException, WebDriverException):
            pass
        return False

    def _dismiss_commissioning_and_go_to_devices(self) -> None:
        """Dismisses any error dialogs/sheets and returns GHA to the Devices or Home tab."""
        self._logger.info("[Recovery] Attempting to dismiss commissioning failure screens and return to Devices tab...")
        exit_predicates = [
            'label == "Exit setup" OR name == "Exit setup"',
            'label == "Exit" OR name == "Exit"',
            'label == "Cancel" OR name == "Cancel"',
            'label == "Close" OR name == "Close"',
            'label == "Done" OR name == "Done"'
        ]
        for _ in range(3):
            found_btn = False
            for pred in exit_predicates:
                try:
                    btns = self.driver.find_elements(AppiumBy.IOS_PREDICATE, pred)
                    for btn in btns:
                        if btn.is_displayed():
                            btn_text = btn.text or btn.get_attribute("label") or "Exit"
                            self._logger.info(f"[Recovery] Clicking exit/cancel button: '{btn_text}'")
                            btn.click()
                            time.sleep(1.5)
                            found_btn = True
                            break
                except Exception:
                    pass
                if found_btn:
                    break
            if not found_btn:
                break
        # Handle "Exit setup?" confirmation alert if presented
        try:
            confirm_btns = self.driver.find_elements(
                AppiumBy.XPATH,
                '//XCUIElementTypeButton[@name="Exit setup" or @name="Exit" or @name="Leave"]'
            )
            for b in confirm_btns:
                if b.is_displayed():
                    b.click()
                    time.sleep(1.5)
        except Exception:
            pass
        try:
            dismiss_btns = self.driver.find_elements(
                AppiumBy.XPATH,
                '//XCUIElementTypeButton[@name="Dismiss" or @name="Cancel" or @name="好"]'
            )
            for b in dismiss_btns:
                if b.is_displayed():
                    b.click()
                    time.sleep(1.0)
        except Exception:
            pass
        time.sleep(1.5)
        try:
            device_tabs = self.driver.find_elements(
                AppiumBy.XPATH,
                '//XCUIElementTypeTabBar//XCUIElementTypeButton[@name="Devices" or @label="Devices"]'
            )
            for tab in device_tabs:
                if tab.is_displayed():
                    self._logger.info("[Recovery] Tapping Devices tab...")
                    tab.click()
                    time.sleep(2.0)
                    break
        except Exception as e:
            self._logger.warning(f"[Recovery] Could not tap Devices tab: {e}")

    def power_cycle_smart_plug(
            self,
            keywords: Optional[List[str]] = None,
            off_wait: float = 5.0,
            on_wait: float = 8.0
    ) -> bool:
        """Locates a device tile containing 'plug' or 'outlet' in its name/label
        and cycles power: OFF -> wait -> ON -> wait.
        """
        if keywords is None:
            keywords = ["plug", "outlet", "插頭"]
        self._logger.info(f"[PowerCycle] Searching for smart plug/outlet device with keywords: {keywords}...")

        def is_plug_match(elem) -> bool:
            lbl = (elem.get_attribute("label") or "").lower()
            val = (elem.get_attribute("value") or "").lower()
            name = (elem.get_attribute("name") or "").lower()
            return any(kw.lower() in lbl or kw.lower() in val or kw.lower() in name for kw in keywords)
        target_btn = None
        target_label = ""
        for attempt in range(2):
            try:
                device_tiles = self.driver.find_elements(AppiumBy.NAME, "deviceTile")
                for tile in device_tiles:
                    if is_plug_match(tile):
                        target_btn = tile
                        target_label = tile.get_attribute("label") or tile.get_attribute("name") or "Smart Plug"
                        break
            except Exception as e:
                self._logger.warning(f"[PowerCycle] Error scanning deviceTile buttons: {e}")
            if target_btn:
                break
            try:
                cells = self.driver.find_elements(AppiumBy.XPATH, '//XCUIElementTypeCell[contains(@name, "deviceTileCell")]')
                for cell in cells:
                    if is_plug_match(cell):
                        inner_btns = cell.find_elements(AppiumBy.NAME, "deviceTile")
                        target_btn = inner_btns[0] if inner_btns else cell
                        target_label = cell.get_attribute("label") or "Smart Plug"
                        break
            except Exception as e:
                self._logger.warning(f"[PowerCycle] Error scanning cells: {e}")
            if target_btn:
                break
            if attempt == 0:
                self._logger.info("[PowerCycle] Plug not found on top fold, scrolling down...")
                try:
                    self.driver.execute_script("mobile: scroll", {"direction": "down"})
                    time.sleep(1.5)
                except Exception:
                    pass
        if not target_btn:
            self._logger.error(f"[PowerCycle] FAILED to find any smart plug/outlet matching keywords: {keywords}")
            return False
        self._logger.info(f"[PowerCycle] Found target plug device: '{target_label}'")
        current_val = (target_btn.get_attribute("value") or "").strip().lower()
        is_on = current_val in ["on", "1", "true"]
        self._logger.info(f"[PowerCycle] Initial power state of '{target_label}': value='{current_val}' (is_on={is_on})")
        try:
            if is_on or current_val not in ["off", "0", "false"]:
                self._logger.info(f"[PowerCycle] Tapping to turn OFF '{target_label}'...")
                target_btn.click()
                self._logger.info(f"[PowerCycle] Plug turned OFF. Waiting {off_wait}s to fully discharge camera...")
                time.sleep(off_wait)
                self._logger.info("[PowerCycle] Re-locating plug button to turn back ON...")
                turn_on_btn = None
                for tile in self.driver.find_elements(AppiumBy.NAME, "deviceTile"):
                    if is_plug_match(tile):
                        turn_on_btn = tile
                        break
                if turn_on_btn:
                    self._logger.info(f"[PowerCycle] Tapping to turn ON '{target_label}'...")
                    turn_on_btn.click()
                else:
                    self._logger.warning("[PowerCycle] Re-locating by name failed, trying fallback click...")
                    target_btn.click()
                self._logger.info(f"[PowerCycle] Plug turned ON! Waiting {on_wait}s for camera boot & Matter advertising...")
                time.sleep(on_wait)
            else:
                self._logger.info(f"[PowerCycle] Plug is currently OFF. Tapping to turn ON...")
                target_btn.click()
                self._logger.info(f"[PowerCycle] Plug turned ON! Waiting {on_wait}s for camera boot...")
                time.sleep(on_wait)
            self._logger.info(f"[PowerCycle] Successfully power-cycled smart plug '{target_label}'.")
            return True
        except Exception as e:
            self._logger.error(f"[PowerCycle] Error during power-cycling plug: {e}")
            return False

    def handle_apple_commissioning_sheet(self, device_name: str) -> bool:
        """Observe and act on foreground Apple Matter ProxCard sheet.
        Returns:
            bool: True if Apple sheet was present and handled, False if not present.
        """
        try:
            if self.handle_system_alert():
                time.sleep(1.0)
                return True
            if not self.is_apple_sheet_present():
                return False
            card_title = self._get_apple_card_title()
            if not card_title:
                return True
            self._logger.info(f"Active Apple Commissioning Sheet: '{card_title}'")
            if "Added to" in card_title or "added to" in card_title.lower():
                self._logger.info("Apple sheet: Device successfully added! Clicking 'Done' inside sheet...")
                done_id = getattr(constants, "GHA_DONE_BTN_ACCESSIBILITY_ID", "Done")
                if self._click_apple_sheet_button(done_id) or self._click_apple_sheet_button("Done"):
                    time.sleep(1.5)
                    return True
            if "Unable to Add Accessory" in card_title or "unable to add accessory" in card_title.lower():
                self._logger.error(f"Apple sheet reported failure: '{card_title}'")
                ok_id = getattr(constants, "GHA_DONE_BTN_ACCESSIBILITY_ID", "OK")
                self._click_apple_sheet_button(ok_id) or self._click_apple_sheet_button("OK")
                time.sleep(1.5)
                # Dismiss and execute power cycle immediately
                self._dismiss_commissioning_and_go_to_devices()
                cycle_ok = self.power_cycle_smart_plug()
                raise AssertionError(
                    f"FATAL: Apple sheet failed with '{card_title}'. "
                    f"Smart plug power-cycle: {'SUCCESS' if cycle_ok else 'FAILED'}."
                )
            if "Bridge Name" in card_title:
                self._logger.info(f"Apple sheet: Detected naming step '{card_title}'. Updating device name to '{device_name}'...")
                try:
                    self._logger.info("Detected 'Bridge Name' step. Edit the device name...")
                    self._find_element(AppiumBy.CLASS_NAME, constants.GHA_TEXT_EDIT_VIEW_CLASS_NAME).clear()
                    time.sleep(1)
                    self._find_element(AppiumBy.CLASS_NAME, constants.GHA_TEXT_EDIT_VIEW_CLASS_NAME).send_keys(device_name)
                    time.sleep(1)
                    if self._click_apple_sheet_button("Continue") or self._click_if_visible(AppiumBy.ACCESSIBILITY_ID, "Continue"):
                        self._logger.info("Submitted custom device name on Apple sheet.")
                        time.sleep(2.0)
                        return True
                except (StaleElementReferenceException, WebDriverException) as e:
                    self._logger.debug(f"Naming step element transition: {e}")
                    return True
            add_chain = (
                '**/XCUIElementTypeWindow[`name == "SBTransientOverlayWindow" AND visible == 1`]/**/'
                'XCUIElementTypeButton[`name CONTAINS "Add to" OR label CONTAINS "Add to"`]'
            )
            try:
                add_buttons = self.driver.find_elements(AppiumBy.IOS_CLASS_CHAIN, add_chain)
                for btn in add_buttons:
                    try:
                        if btn.is_displayed():
                            btn.click()
                            self._logger.info("Clicked 'Add to Google Home' on Apple sheet.")
                            time.sleep(1.0)
                            return True
                    except (StaleElementReferenceException, WebDriverException):
                        continue
            except Exception:
                pass
            self._logger.info(f"Apple sheet in progress: '{card_title}'... Waiting.")
            time.sleep(2.0)
            return True
        except AssertionError:
            raise
        except (StaleElementReferenceException, WebDriverException) as e:
            self._logger.debug(f"Apple sheet transition in progress ({e.__class__.__name__}). Retrying next cycle...")
            time.sleep(1.0)
            return True

    def complete_commissioning_and_pairing_flow(
            self, device_name: str, room_name: str = "Attic", timeout: float = 300
    ) -> bool:
        """Unified State Machine handling Apple system sheets, GHA loading, room setup, and completion.
        Args:
            device_name (str): Desired device name to fill in Apple sheet.
            room_name (str): Target room to assign in 'Where is this device?'.
            timeout (float): Total timeout in seconds for complete pairing. Defaults to 300s.
        Returns:
            bool: True if device connected successfully, False otherwise.
        """
        self._logger.info(f"Starting Commissioning & Pairing Flow for '{device_name}' (Timeout: {int(timeout)}s)...")
        start_time = time.time()
        apple_sheet_active = False
        failure_keywords = [
            "Can’t connect", "Can't connect", "Something went wrong", "Unable to connect",
            "Check your connection", "Device not found", "Setup failed", "Could not connect",
            "Couldn't connect"
        ]
        try:
            while time.time() - start_time < timeout:
                elapsed = int(time.time() - start_time)
                if self.handle_apple_commissioning_sheet(device_name):
                    apple_sheet_active = True
                    continue
                if apple_sheet_active:
                    self._logger.info("Apple Commissioning Sheet dismissed. Back in GHA foreground.")
                    apple_sheet_active = False
                    time.sleep(1.0)
                headline = self._get_gha_headline()
                if not headline:
                    time.sleep(1.5)
                    continue
                self._logger.info(f"[{elapsed}s] GHA Headline: '{headline}'")
                if any(fail.lower() in headline.lower() for fail in failure_keywords):
                    self._logger.error(f"[Commissioning] Failure headline detected: '{headline}'")
                    self._dismiss_commissioning_and_go_to_devices()
                    cycle_ok = self.power_cycle_smart_plug()
                    raise AssertionError(
                        f"FATAL: Commissioning failed with headline: '{headline}'. "
                        f"Smart plug power-cycle: {'SUCCESS' if cycle_ok else 'FAILED'}."
                    )
                if any(status in headline for status in [
                    "Adding device", "Getting your device ready", "Next, your device will be added", "Connecting",
                    "Setting up", "Activating camera", "Downloading update", "Update finished"
                ]):
                    self._logger.info(f"Waiting for GHA background progress: '{headline}'...")
                    time.sleep(2.5)
                    continue
                if "Watch setup video" in headline:
                    self._logger.info("Detected 'Watch setup video'. Clicking Next/Done...")
                    GHAWatchSetupVideoPage(self.driver).handle_watch_setup_video_page_process()
                    time.sleep(1.0)
                    continue
                if "Connect this device to your Google Account" in headline:
                    self._logger.info("Detected 'Connect device to Google Account'. Clicking I agree...")
                    GHAConnectDeviceToGoogleAccountPage(self.driver).click_i_agree_btn()
                    time.sleep(1.0)
                    continue
                if "Where is this device" in headline:
                    self._logger.info("Reached room selection. Delegating to GHAWhereIsThisDevicePage instance...")
                    try:
                        GHAWhereIsThisDevicePage(self.driver).select_room_or_add_custom(room_name=room_name)
                    except Exception as e:
                        self._logger.warning(f"select_room_or_add_custom error: {e}. Executing fallback cell selection...")
                        cells = self.driver.find_elements(AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeCell[`visible == 1`]')
                        if cells:
                            cells[0].click()
                        self._click_if_visible(AppiumBy.ACCESSIBILITY_ID, constants.GHA_NEXT_BTN_ACCESSIBILITY_ID)
                    time.sleep(1.0)
                    continue
                if "Device connected" in headline or "Device added" in headline:
                    self._logger.info("Device connected! Delegating to GHADeviceConnectedPage.click_done_btn...")
                    try:
                        GHADeviceConnectedPage(self.driver).click_done_btn()
                    except Exception:
                        self._click_if_visible(AppiumBy.ACCESSIBILITY_ID, constants.GHA_DONE_BTN_ACCESSIBILITY_ID)
                    continue
                if "Camera activated" in headline:
                    self._logger.info(f"Device paired and transitioned directly to '{headline}'!")
                    GHACameraActivatedPage(self.driver).handle_camera_activated_page_process()
                    continue
                if "You should now see live video" in headline:
                    self._logger.info(f"Device paired and transitioned directly to '{headline}'!")
                    GHAYouShouldNowSeeLiveVideoPage(self.driver).handle_you_should_now_see_live_video_page_process()
                    return True
                if "Uncertified" in headline or "Service failure" in headline:
                    self._logger.warning(f"Encountered warning: '{headline}'. Clicking Set up anyway...")
                    if not self._click_if_visible(AppiumBy.ACCESSIBILITY_ID, "Set up anyway"):
                        self._click_if_visible(AppiumBy.ACCESSIBILITY_ID, "Exit")
                    time.sleep(2.0)
                    continue
                time.sleep(1.5)
            self._logger.error(f"[Commissioning] Flow timed out after {int(timeout)}s!")
            self._dismiss_commissioning_and_go_to_devices()
            cycle_ok = self.power_cycle_smart_plug()
            raise AssertionError(
                f"FATAL: Commissioning timed out after {int(timeout)}s. "
                f"Smart plug power-cycle: {'SUCCESS' if cycle_ok else 'FAILED'}."
            )
        except AssertionError:
            raise
        except Exception as e:
            self._logger.error(f"[Commissioning] Unexpected exception during pairing flow: {e}")
            try:
                self._dismiss_commissioning_and_go_to_devices()
                self.power_cycle_smart_plug()
            except Exception as recovery_err:
                self._logger.warning(f"[Commissioning] Recovery power cycle error: {recovery_err}")
            raise AssertionError(f"Commissioning flow failed with unexpected exception: {e}") from e