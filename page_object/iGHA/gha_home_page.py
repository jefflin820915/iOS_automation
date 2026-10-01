"""Page object for handling GHA (Google Home App) bottom tab navigation on iOS."""
import time
from contextlib import contextmanager
from typing import Iterator, List, Optional, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from common import constants
from common.base_page import BasePage, PageNotPresentException
from utils import logging_utils


class GHAHomePage(BasePage):
    """Class for handling GHA bottom navigation tab interactions on iOS.
    NOTE: Private helpers are prefixed with `_home_` to avoid name collisions in GHASession.
    """
    SHEET_ROOT_ID = "BottomSheetPresentationViewController"
    SHEET_SCROLL_ID = "bottomSheetContentScrollView"
    SHEET_CLOSE_ID = "bottomSheetTopHandleViewContainer"
    SHEET_CLOSE_PREDICATE = 'label == "Close popup" OR name == "bottomSheetTopHandleViewContainer"'
    SHEET_CONTENT_VIEW_CHAIN = '**/XCUIElementTypeOther[`name == "bottomSheetContentView"`]'
    SHEET_LOADING_CHAIN = (
        f'{SHEET_CONTENT_VIEW_CHAIN}/**/*[`type == "XCUIElementTypeActivityIndicator" '
        f'OR type == "XCUIElementTypeProgressIndicator"`]'
    )
    SHEET_CONTENT_TEXT_CHAIN = (
        '**/XCUIElementTypeScrollView[`name == "bottomSheetContentScrollView"`]'
        '/**/*[`type == "XCUIElementTypeStaticText" OR type == "XCUIElementTypeButton"`]'
    )
    SHEET_MIN_CONTENT_TEXTS = 2
    SHEET_POLL_INTERVAL_S = 0.5
    SHEET_LOG_INTERVAL_S = 5.0

    def _home_find_element(self, by: AppiumBy, locator_value: str) -> Optional[WebElement]:
        """Find an element using specified locator strategy with explicit wait."""
        try:
            return WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((by, locator_value))
            )
        except TimeoutException:
            self._logger.error(f"Timed out waiting for element: by={by}, value='{locator_value}'")
            return None
    def _home_find_by_accessibility_id(self, accessibility_id: str) -> Optional[WebElement]:
        """Convenient helper to find an element by ACCESSIBILITY_ID."""
        return self._home_find_element(AppiumBy.ACCESSIBILITY_ID, accessibility_id)
    def _home_find_by_class_chain(self, class_chain: str) -> Optional[WebElement]:
        """Convenient helper to find an element by IOS_CLASS_CHAIN."""
        return self._home_find_element(AppiumBy.IOS_CLASS_CHAIN, class_chain)
    @contextmanager
    def _home_no_implicit_wait(self) -> Iterator[None]:
        """Temporarily disable implicit wait so absent-element checks return instantly."""
        default_wait = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
        try:
            self.driver.implicitly_wait(0)
            yield
        finally:
            try:
                self.driver.implicitly_wait(default_wait)
            except WebDriverException:
                pass
    def _home_quick_find_all(self, by: str, value: str) -> List[WebElement]:
        """find_elements without implicit wait; never raises."""
        try:
            with self._home_no_implicit_wait():
                return self.driver.find_elements(by, value)
        except WebDriverException:
            return []

    def _home_get_devices_tab(self) -> Optional[WebElement]:
        """Get the 'Devices' tab WebElement."""
        return self._home_find_by_class_chain(constants.GHA_DEVICE_TAB_CLASS_CHAIN)
    def _home_get_favorites_tab(self) -> Optional[WebElement]:
        """Get the 'Favorites' tab WebElement."""
        return self._home_find_by_class_chain(constants.GHA_FAVORITES_TAB_CLASS_CHAIN)
    def _home_get_cameras_tab(self) -> Optional[WebElement]:
        """Get the 'Cameras' tab WebElement."""
        return self._home_find_by_class_chain(constants.GHA_CAMERAS_TAB_CLASS_CHAIN)
    def _home_get_lights_tab(self) -> Optional[WebElement]:
        """Get the 'Lights' tab WebElement."""
        return self._home_find_by_class_chain(constants.GHA_LIGHTS_TAB_CLASS_CHAIN)
    def _home_get_add_devices_btn(self) -> Optional[WebElement]:
        """Get the 'Add Devices' button using ACCESSIBILITY_ID."""
        return self._home_find_by_accessibility_id(constants.GHA_ADD_DEVICES_BTN_ACCESSIBILITY_ID)
    def _home_switch_to_tab(self, tab_element: Optional[WebElement], tab_name: str) -> bool:
        """Helper method to check tab selection state and click if not selected."""
        if not tab_element:
            self._logger.error(f"Cannot switch to '{tab_name}' tab: element not found.")
            return False
        try:
            is_selected = tab_element.get_attribute("value") == "1" or tab_element.is_selected()
            if not is_selected:
                self._logger.info(f"Clicking '{tab_name}' tab to switch...")
                tab_element.click()
            else:
                self._logger.info(f"'{tab_name}' tab is already selected.")
            return True
        except WebDriverException as e:
            self._logger.error(f"Failed to switch to '{tab_name}' tab: {e}")
            return False

    def _home_sheet_ready_labels(self) -> Tuple[str, ...]:
        """Option labels that prove the sheet finished loading (configurable in constants)."""
        labels = getattr(constants, "GHA_ADD_DEVICE_SHEET_READY_LABELS", ())
        if isinstance(labels, str):
            labels = (labels,)
        return tuple(l for l in labels if l)
    def _home_sheet_state(self) -> str:
        """Return 'ABSENT', 'LOADING' or 'READY' for the add-device bottom sheet."""
        root = self._home_quick_find_all(AppiumBy.ACCESSIBILITY_ID, self.SHEET_ROOT_ID)
        scroll = root or self._home_quick_find_all(AppiumBy.ACCESSIBILITY_ID, self.SHEET_SCROLL_ID)
        if not scroll:
            return "ABSENT"
        for label in self._home_sheet_ready_labels():
            chain = f'{self.SHEET_CONTENT_VIEW_CHAIN}/**/*[`label == "{label}" OR name == "{label}"`]'
            if self._home_quick_find_all(AppiumBy.IOS_CLASS_CHAIN, chain):
                return "READY"
        if self._home_quick_find_all(AppiumBy.IOS_CLASS_CHAIN, self.SHEET_LOADING_CHAIN):
            return "LOADING"
        meaningful = 0
        for el in self._home_quick_find_all(AppiumBy.IOS_CLASS_CHAIN, self.SHEET_CONTENT_TEXT_CHAIN)[:10]:
            try:
                text = (el.get_attribute("label") or el.get_attribute("name") or "").strip()
            except WebDriverException:
                continue
            if text and "loading" not in text.lower():
                meaningful += 1
                if meaningful >= self.SHEET_MIN_CONTENT_TEXTS:
                    return "READY"
        return "LOADING"
    def _home_wait_add_device_sheet(self, load_timeout_s: float, appear_timeout_s: float) -> str:
        """Poll until the sheet is READY; give up early if it never appears."""
        start = time.time()
        last_log = start
        state = "ABSENT"
        while time.time() - start < load_timeout_s:
            state = self._home_sheet_state()
            elapsed = time.time() - start
            if state == "READY":
                return state
            if state == "ABSENT" and elapsed >= appear_timeout_s:
                return state
            if time.time() - last_log >= self.SHEET_LOG_INTERVAL_S:
                self._logger.info(f"Waiting for add-device sheet... state={state} ({elapsed:.0f}s)")
                last_log = time.time()
            time.sleep(self.SHEET_POLL_INTERVAL_S)
        return state
    def _home_close_sheet(self) -> None:
        """Dismiss a stuck add-device sheet via its 'Close popup' handle."""
        targets = (
                self._home_quick_find_all(AppiumBy.ACCESSIBILITY_ID, self.SHEET_CLOSE_ID)
                or self._home_quick_find_all(AppiumBy.IOS_PREDICATE, self.SHEET_CLOSE_PREDICATE)
        )
        try:
            if targets:
                targets[0].click()
                self._logger.info("Closed stuck add-device sheet via 'Close popup'.")
            else:
                self._logger.warning("'Close popup' not found; leaving sheet as-is.")
        except WebDriverException as e:
            self._logger.warning(f"Failed to close add-device sheet: {e}")
        time.sleep(1.5)
    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def navigate_to_devices_tab(self) -> bool:
        """Ensure the 'Devices' tab is selected in GHA."""
        tab = self._home_get_devices_tab()
        return self._home_switch_to_tab(tab, "Devices")
    def navigate_to_favorites_tab(self) -> bool:
        """Ensure the 'Favorites' tab is selected in GHA."""
        tab = self._home_get_favorites_tab()
        return self._home_switch_to_tab(tab, "Favorites")
    def navigate_to_cameras_tab(self) -> bool:
        """Ensure the 'Cameras' tab is selected in GHA."""
        tab = self._home_get_cameras_tab()
        return self._home_switch_to_tab(tab, "Cameras")
    def navigate_to_lights_tab(self) -> bool:
        """Ensure the 'Lights' tab is selected in GHA."""
        tab = self._home_get_lights_tab()
        return self._home_switch_to_tab(tab, "Lights")
    def click_add_devices_button(self) -> bool:
        """Click the 'Add Devices' (+) button and wait until the bottom sheet content has loaded.
        Retries (close sheet + click again) if the sheet never appears or stays loading.
        """
        attempts = int(getattr(constants, "GHA_ADD_DEVICE_SHEET_ATTEMPTS", 2))
        load_timeout = float(getattr(constants, "GHA_ADD_DEVICE_SHEET_LOAD_TIMEOUT_S", 45.0))
        appear_timeout = float(getattr(constants, "GHA_ADD_DEVICE_SHEET_APPEAR_TIMEOUT_S", 8.0))
        for attempt in range(1, attempts + 1):
            state = self._home_sheet_state()
            if state == "READY":
                self._logger.info("Add-device sheet is already open and loaded.")
                return True
            if state == "ABSENT":
                btn = self._home_get_add_devices_btn()
                if not btn:
                    self._logger.error("Cannot click 'Add Devices' button: element not found.")
                    return False
                try:
                    self._logger.info(f"Clicking 'Add Devices' button (attempt {attempt}/{attempts})...")
                    btn.click()
                except WebDriverException as e:
                    self._logger.error(f"Failed to click 'Add Devices' button: {e}")
                    continue
            start = time.time()
            state = self._home_wait_add_device_sheet(load_timeout, appear_timeout)
            elapsed = time.time() - start
            if state == "READY":
                self._logger.info(f"Add-device sheet loaded in {elapsed:.1f}s.")
                return True
            self._logger.warning(
                f"Add-device sheet not ready after {elapsed:.1f}s (state={state}, attempt {attempt}/{attempts})."
            )
            if state == "LOADING":
                self._home_close_sheet()
        self._logger.error("Add-device sheet failed to load after all attempts.")
        return False