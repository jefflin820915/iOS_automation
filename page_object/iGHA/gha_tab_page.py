"""Page object for handling GHA bottom tab navigation, category chips, and active tab detection on iOS."""
import time
from contextlib import contextmanager
from typing import Iterator, List, Optional, Tuple, Union
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException
from common import constants
from common.base_page import BasePage

Locator = Tuple[str, str]


class GHATabPage(BasePage):
    """Manage bottom navigation tabs, chips, and settings navigation in iOS GHA.
    NOTE: GHASession inherits many page classes, so all private helpers are prefixed
    with `_tab_` to avoid being shadowed via MRO by same-named methods of other pages.
    """
    TAB_BAR_CONTAINER = "homeViewTabBarAccessibilityID"
    HOME_TAB_BTN = "homeTabBarButtonAccessibilityID"
    ACTIVITY_TAB_BTN = "activityTabBarButtonAccessibilityID"
    AUTOMATIONS_TAB_BTN = "automationTabBarButtonAccessibilityID"
    CHIPS_CONTAINER = "HomeRootViewController.AccessibilityID.categoryChips"
    SETTINGS_NAV_BAR: Locator = (
        AppiumBy.IOS_CLASS_CHAIN,
        '**/XCUIElementTypeNavigationBar[`name == "Settings" OR name == "Home settings"`]',
    )
    # Prefer tappable containers; StaticText inside a cell does not forward taps
    HOME_SETTINGS_BTN_LOCATORS: List[Locator] = [
        (AppiumBy.IOS_PREDICATE,
         'type IN {"XCUIElementTypeCell", "XCUIElementTypeButton"} AND '
         '(name == "Home settings" OR label == "Home settings")'),
        (AppiumBy.IOS_PREDICATE,
         'type == "XCUIElementTypeStaticText" AND (name == "Home settings" OR label == "Home settings")'),
    ]
    # Elements only present on the account menu sheet
    ACCOUNT_MENU_MARKER: Locator = (
        AppiumBy.IOS_PREDICATE,
        '(type == "XCUIElementTypeButton" AND name == "Done") OR label == "Manage your Google Account"',
    )
    DISMISS_BTN: Locator = (
        AppiumBy.IOS_PREDICATE,
        'type == "XCUIElementTypeButton" AND name IN {"Done", "Back", "Close", "close"}',
    )
    SETTINGS_CLOSE_LOCATORS: List[Locator] = [
        (AppiumBy.IOS_CLASS_CHAIN,
         '**/XCUIElementTypeNavigationBar[`name == "Settings" OR name == "Home settings"`]'
         '/**/XCUIElementTypeButton[1]'),
        (AppiumBy.IOS_PREDICATE, 'type == "XCUIElementTypeButton" AND name IN {"close", "Close", "Back", "Done"}'),
    ]
    TAB_POLL_INTERVAL = 0.3
    TAB_ACTION_SETTLE = 1.0
    TAB_MENU_OPEN_TIMEOUT = 5.0
    TAB_MENU_SETTLE_TIMEOUT = 3.0
    TAB_MENU_LEAVE_TIMEOUT = 5.0
    TAB_MAX_HOME_SETTINGS_ATTEMPTS = 3

    @contextmanager
    def _tab_no_implicit_wait(self) -> Iterator[None]:
        """Temporarily disable implicit wait so missing elements return immediately."""
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

    @contextmanager
    def _tab_no_idle_wait(self) -> Iterator[None]:
        """Temporarily disable WDA wait-for-idle so taps are not delayed during animations."""
        previous = None
        try:
            previous = self.driver.get_settings().get("waitForIdleTimeout")
            self.driver.update_settings({"waitForIdleTimeout": 0})
        except Exception:
            pass
        try:
            yield
        finally:
            if previous is not None:
                try:
                    self.driver.update_settings({"waitForIdleTimeout": previous})
                except Exception:
                    pass

    def _tab_find_displayed_now(self, by: str, value: str) -> Optional[WebElement]:
        """Return the first displayed element immediately, or None."""
        with self._tab_no_implicit_wait():
            try:
                for elem in self.driver.find_elements(by, value):
                    if elem.is_displayed():
                        return elem
            except WebDriverException:
                pass
        return None

    def _tab_wait_displayed(self, by: str, value: str, timeout: float = 1.0) -> Optional[WebElement]:
        """Poll until a displayed element appears or timeout expires."""
        deadline = time.time() + timeout
        while True:
            elem = self._tab_find_displayed_now(by, value)
            if elem is not None or time.time() >= deadline:
                return elem
            time.sleep(self.TAB_POLL_INTERVAL)

    def _tab_wait_any(self, locators: List[Locator], timeout: float = 1.0) -> Optional[WebElement]:
        """Poll multiple locators (in priority order) until any displayed element appears."""
        deadline = time.time() + timeout
        while True:
            for by, value in locators:
                elem = self._tab_find_displayed_now(by, value)
                if elem is not None:
                    return elem
            if time.time() >= deadline:
                return None
            time.sleep(self.TAB_POLL_INTERVAL)

    def _tab_wait_rect_stable(self, locators: List[Locator], timeout: float) -> Optional[WebElement]:
        """Wait until the element exists and its rect stops changing (animation finished)."""
        deadline = time.time() + timeout
        last_rect = None
        elem = None
        while time.time() < deadline:
            elem = self._tab_wait_any(locators, timeout=0)
            if elem is not None:
                try:
                    rect = elem.rect
                except WebDriverException:
                    rect = None
                if rect is not None and rect == last_rect:
                    return elem
                last_rect = rect
            time.sleep(self.TAB_POLL_INTERVAL)
        return elem

    def _tab_tap_center(self, element: WebElement) -> None:
        """Coordinate tap at the element center."""
        rect = element.rect
        self.driver.execute_script("mobile: tap", {
            "x": int(rect["x"] + rect["width"] / 2),
            "y": int(rect["y"] + rect["height"] / 2),
        })

    def _tab_click(self, element: WebElement, description: str = "element") -> bool:
        """Click an element, falling back to a coordinate tap."""
        try:
            element.click()
            time.sleep(self.TAB_ACTION_SETTLE)
            self._logger.info(f"Successfully clicked {description}.")
            return True
        except WebDriverException as e:
            self._logger.warning(f"Standard click on {description} failed ({e}). Trying coordinate tap...")
        try:
            self._tab_tap_center(element)
            time.sleep(self.TAB_ACTION_SETTLE)
            self._logger.info(f"Successfully coordinate-tapped {description}.")
            return True
        except WebDriverException as coord_err:
            self._logger.error(f"Coordinate tap failed for {description}: {coord_err}")
            return False

    def _tab_is_value_selected(self, element: Optional[WebElement]) -> bool:
        if element is None:
            return False
        try:
            return str(element.get_attribute("value") or "0") in ("1", "true") or element.is_selected()
        except WebDriverException:
            return False

    def _tab_swipe_up_slightly(self) -> None:
        """Gentle swipe up to reveal content below the fold in dialogs."""
        try:
            size = self.driver.get_window_size()
            x = size["width"] // 2
            self.driver.swipe(x, int(size["height"] * 0.7), x, int(size["height"] * 0.4), duration=300)
            time.sleep(self.TAB_ACTION_SETTLE)
        except WebDriverException as e:
            self._logger.debug(f"Swipe up failed: {e}")

    def _tab_dismiss_modal_or_go_back(self) -> None:
        """Click Done/Back/Close if stuck on an unexpected screen."""
        elem = self._tab_find_displayed_now(*self.DISMISS_BTN)
        if elem is not None:
            self._tab_click(elem, f"dismiss button '{elem.get_attribute('name')}'")

    def _tab_is_account_menu_open(self) -> bool:
        return self._tab_find_displayed_now(*self.ACCOUNT_MENU_MARKER) is not None

    def _tab_click_home_settings_and_verify(self) -> bool:
        """Tap 'Home settings' in the account menu and verify the menu closed."""
        for attempt in range(1, self.TAB_MAX_HOME_SETTINGS_ATTEMPTS + 1):
            btn = self._tab_wait_rect_stable(self.HOME_SETTINGS_BTN_LOCATORS, self.TAB_MENU_SETTLE_TIMEOUT)
            if btn is None:
                self._logger.info("'Home settings' not visible yet, swiping up slightly...")
                self._tab_swipe_up_slightly()
                btn = self._tab_wait_rect_stable(self.HOME_SETTINGS_BTN_LOCATORS, self.TAB_MENU_SETTLE_TIMEOUT)
            if btn is None:
                self._logger.error("Failed to find 'Home settings' in account menu.")
                return False
            use_coordinates = attempt > 1
            self._logger.info(
                f"Clicking 'Home settings' ({'coordinate tap' if use_coordinates else 'click'}, "
                f"attempt {attempt}/{self.TAB_MAX_HOME_SETTINGS_ATTEMPTS})..."
            )
            try:
                with self._tab_no_idle_wait():
                    if use_coordinates:
                        self._tab_tap_center(btn)
                    else:
                        btn.click()
            except WebDriverException as e:
                self._logger.warning(f"Tap on 'Home settings' failed: {e}")
            deadline = time.time() + self.TAB_MENU_LEAVE_TIMEOUT
            while time.time() < deadline:
                if not self._tab_is_account_menu_open():
                    self._logger.info("Entered Home settings page (account menu closed).")
                    time.sleep(self.TAB_ACTION_SETTLE)
                    return True
                time.sleep(self.TAB_POLL_INTERVAL)
            self._logger.warning("Account menu still open after tapping 'Home settings'. Retrying...")
        self._logger.error("Failed to enter Home settings page from account menu.")
        return False

    def enter_home_settings_page(self) -> bool:
        """Open Home settings via the top-right account avatar and verify navigation."""
        self._logger.info("Opening Settings page from account avatar...")
        if self._tab_is_account_menu_open():
            self._logger.info("Account menu already open.")
            return self._tab_click_home_settings_and_verify()
        account_id = constants.GHA_ACCOUNT_PARTICLE_BTN_ACCESSIBILITY_ID
        account_icon = self._tab_wait_displayed(AppiumBy.ACCESSIBILITY_ID, account_id, timeout=5.0)
        if account_icon is None:
            self._logger.warning("AccountParticleButton not found. Trying to dismiss modal / go back...")
            self._tab_dismiss_modal_or_go_back()
            account_icon = self._tab_wait_displayed(AppiumBy.ACCESSIBILITY_ID, account_id, timeout=3.0)
        if account_icon is None:
            self._logger.error("Could not find AccountParticleButton on current screen.")
            return False
        with self._tab_no_idle_wait():
            if not self._tab_click(account_icon, "AccountParticleButton"):
                return False
        if self._tab_wait_displayed(*self.ACCOUNT_MENU_MARKER, timeout=self.TAB_MENU_OPEN_TIMEOUT) is None:
            self._logger.error("Account menu did not open after tapping avatar.")
            return False
        return self._tab_click_home_settings_and_verify()

    def _tab_close_settings_page(self) -> None:
        """Dismiss settings page via the top-left close / back button."""
        elem = self._tab_wait_any(self.SETTINGS_CLOSE_LOCATORS, timeout=1.0)
        if elem is not None:
            self._tab_click(elem, "Settings close button")

    def get_active_tab(self) -> Optional[constants.TAB]:
        """Return the currently active tab, or None if unknown."""
        if self._tab_find_displayed_now(*self.SETTINGS_NAV_BAR) is not None:
            self._logger.info("Active Tab: SETTINGS")
            return constants.TAB.SETTINGS
        home_btn = self._tab_find_displayed_now(AppiumBy.ACCESSIBILITY_ID, self.HOME_TAB_BTN)
        if self._tab_is_value_selected(home_btn):
            active_chip = self._tab_get_active_chip_under_home()
            if active_chip == constants.CHIP.FAVORITES:
                self._logger.info("Active Tab: FAVORITES (Home Chip)")
                return constants.TAB.FAVORITES
            if active_chip == constants.CHIP.DEVICES:
                self._logger.info("Active Tab: DEVICES (Home Chip)")
                return constants.TAB.DEVICES
            self._logger.info("Active Tab: HOME")
            return constants.TAB.HOME
        for tab_id, tab_enum in (
                (self.ACTIVITY_TAB_BTN, constants.TAB.ACTIVITY),
                (self.AUTOMATIONS_TAB_BTN, constants.TAB.AUTOMATIONS),
        ):
            if self._tab_is_value_selected(self._tab_find_displayed_now(AppiumBy.ACCESSIBILITY_ID, tab_id)):
                self._logger.info(f"Active Tab: {tab_enum.name}")
                return tab_enum
        self._logger.info("Active Tab: UNKNOWN")
        return None

    def _tab_get_active_chip_under_home(self) -> Optional[constants.CHIP]:
        """Return which chip under Home tab is currently selected."""
        for chip_enum in (constants.CHIP.FAVORITES, constants.CHIP.DEVICES,
                          constants.CHIP.CAMERAS, constants.CHIP.LIGHTS):
            chip_btn = self._tab_find_displayed_now(
                AppiumBy.IOS_CLASS_CHAIN,
                f'**/XCUIElementTypeButton[`name == "{chip_enum.value}" AND visible == 1`]',
            )
            if self._tab_is_value_selected(chip_btn):
                return chip_enum
        return None

    def go_to_tab(self, tab: constants.TAB) -> bool:
        """Navigate to the specified GHA tab.
        Args:
            tab: Target tab enum (HOME, FAVORITES, DEVICES, AUTOMATIONS, ACTIVITY, SETTINGS).
        Returns:
            True if navigated successfully, False otherwise.
        """
        active_tab = self.get_active_tab()
        if active_tab == tab:
            self._logger.info(f"Already on tab: {tab.value}")
            return True
        current = active_tab.value if active_tab is not None else "UNKNOWN"
        self._logger.info(f"Navigating from {current} to {tab.value}...")
        if active_tab == constants.TAB.SETTINGS:
            self._tab_close_settings_page()
        match tab:
            case constants.TAB.HOME:
                return self._tab_click_bottom_tab(self.HOME_TAB_BTN, "Home")
            case constants.TAB.FAVORITES:
                self._tab_click_bottom_tab(self.HOME_TAB_BTN, "Home")
                return self.enter_chip_under_home_tab(constants.CHIP.FAVORITES)
            case constants.TAB.DEVICES:
                self._tab_click_bottom_tab(self.HOME_TAB_BTN, "Home")
                return self.enter_chip_under_home_tab(constants.CHIP.DEVICES)
            case constants.TAB.AUTOMATIONS:
                return self._tab_click_bottom_tab(self.AUTOMATIONS_TAB_BTN, "Automations")
            case constants.TAB.ACTIVITY:
                return self._tab_click_bottom_tab(self.ACTIVITY_TAB_BTN, "Activity")
            case constants.TAB.SETTINGS:
                return self.enter_home_settings_page()
            case _:
                self._logger.error(f"Tab '{tab}' is not supported.")
                return False

    def enter_chip_under_home_tab(self, chip: Union[constants.CHIP, str]) -> bool:
        """Click a category chip (Favorites, All devices, Cameras, Lights) under Home tab."""
        chip_label = chip.value if isinstance(chip, constants.CHIP) else str(chip)
        self._logger.info(f"Selecting chip: '{chip_label}' under Home tab...")
        locators: List[Locator] = [
            (AppiumBy.IOS_CLASS_CHAIN, f'**/XCUIElementTypeButton[`name == "{chip_label}" AND visible == 1`]'),
            (AppiumBy.IOS_CLASS_CHAIN, f'**/XCUIElementTypeButton[`label CONTAINS "{chip_label}" AND visible == 1`]'),
            (AppiumBy.IOS_CLASS_CHAIN, f'**/XCUIElementTypeStaticText[`name == "{chip_label}" AND visible == 1`]'),
        ]
        elem = self._tab_wait_any(locators, timeout=3.0)
        if elem is not None and self._tab_click(elem, f"chip '{chip_label}'"):
            return True
        self._logger.error(f"Failed to find chip '{chip_label}' under Home tab.")
        return False

    def _tab_click_bottom_tab(self, accessibility_id: str, tab_name: str) -> bool:
        """Click a bottom navigation bar button by accessibility ID."""
        btn = self._tab_wait_displayed(AppiumBy.ACCESSIBILITY_ID, accessibility_id, timeout=3.0)
        if btn is None:
            self._logger.error(f"'{tab_name}' tab button not found.")
            return False
        if self._tab_click(btn, f"'{tab_name}' tab"):
            self._logger.info(f"Switched to '{tab_name}' tab.")
            return True
        return False