"""Page object for handling GHA bottom tab navigation, category chips, and active tab detection on iOS."""
import time
from typing import Optional, Union, List
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
    StaleElementReferenceException
)
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from common import constants
from common.base_page import BasePage
from utils import logging_utils


class GHATabPage(BasePage):
    """Class for managing bottom navigation tabs, chips, and settings navigation in iOS GHA."""
    TAB_BAR_CONTAINER = "homeViewTabBarAccessibilityID"
    HOME_TAB_BTN = "homeTabBarButtonAccessibilityID"
    ACTIVITY_TAB_BTN = "activityTabBarButtonAccessibilityID"
    AUTOMATIONS_TAB_BTN = "automationTabBarButtonAccessibilityID"
    CHIPS_CONTAINER = "HomeRootViewController.AccessibilityID.categoryChips"
    SETTINGS_NAV_BAR = '**/XCUIElementTypeNavigationBar[`name == "Settings" OR name == "Home settings"`]'

    def _find_element(self, by: AppiumBy, locator_value: str, timeout: float = 2.0) -> Optional[WebElement]:
        """Find an element using specified locator strategy with explicit wait."""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, locator_value))
            )
        except TimeoutException:
            self._logger.debug(f"Timed out waiting for element: by={by}, value='{locator_value}'")
            return None
        except Exception as e:
            self._logger.debug(f"Error finding element: {e}")
            return None

    def _find_elements(self, by: AppiumBy, value: str, timeout: float = 1.0) -> List[WebElement]:
        """Find all elements matching locator strategy with explicit wait."""
        try:
            elems = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_all_elements_located((by, value))
            )
            return elems if elems else []
        except TimeoutException:
            return []
        except Exception as e:
            self._logger.debug(f"Error finding elements: {e}")
            return []

    def _get_element_safe(self, by: AppiumBy, value: str, timeout: float = 1.0) -> Optional[WebElement]:
        """Safely find a visible element without throwing exceptions."""
        try:
            elems = self._find_elements(by, value, timeout=timeout)
            for elem in elems:
                if elem and elem.is_displayed():
                    return elem
        except Exception:
            pass
        return None

    def _click_element_with_fallback(self, element: WebElement, description: str = "element") -> bool:
        """Click an element, falling back to coordinate tap if standard click fails."""
        try:
            element.click()
            time.sleep(1.5)
            self._logger.info(f"Successfully clicked {description}.")
            return True
        except (WebDriverException, StaleElementReferenceException) as e:
            self._logger.warning(f"Standard click on {description} failed ({e}). Trying coordinate tap...")
            try:
                rect = element.rect
                tap_x = rect["x"] + (rect["width"] // 2)
                tap_y = rect["y"] + (rect["height"] // 2)
                self.driver.execute_script("mobile: tap", {"x": tap_x, "y": tap_y})
                time.sleep(1.5)
                self._logger.info(f"Successfully coordinate-tapped {description} at ({tap_x}, {tap_y}).")
                return True
            except Exception as coord_err:
                self._logger.error(f"Coordinate tap failed for {description}: {coord_err}")
                return False

    def _find_home_settings_button(self, timeout: float = 2.0) -> Optional[WebElement]:
        """Locate 'Home settings' button in the account dialog using prioritized locators."""
        locators = [
            (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "Home settings" OR label == "Home settings"`]'),
            (AppiumBy.ACCESSIBILITY_ID, getattr(constants, "GHA_SETTING_PAGE_ACCESSIBILITY_ID", "Home settings")),
            (AppiumBy.XPATH, '//XCUIElementTypeButton[@name="Home settings" or @label="Home settings"]'),
            (AppiumBy.IOS_CLASS_CHAIN, getattr(constants, "GHA_SETTING_PAGE_CLASS_CHAIN", '**/XCUIElementTypeStaticText[`name == "Home settings"`]')),
        ]
        for by, val in locators:
            try:
                elem = self._get_element_safe(by, val, timeout=timeout)
                if elem:
                    return elem
            except Exception:
                continue
        return None

    def enter_home_settings_page(self) -> bool:
        """Open Settings page by clicking the top-right account avatar, with recovery resilience."""
        self._logger.info("Opening Settings page from account avatar...")
        time.sleep(1.0)
        home_settings_btn = self._find_home_settings_button(timeout=1.5)
        if home_settings_btn:
            self._logger.info("Account menu is already open on screen. Clicking 'Home settings' directly...")
            return self._click_element_with_fallback(home_settings_btn, "'Home settings' button")
        account_icon = self._get_element_safe(
            AppiumBy.ACCESSIBILITY_ID,
            constants.GHA_ACCOUNT_PARTICLE_BTN_ACCESSIBILITY_ID,
            timeout=5.0
        )
        if not account_icon:
            self._logger.warning("AccountParticleButton not found. Attempting to dismiss modal or navigate back...")
            self._dismiss_modal_or_go_back()
            account_icon = self._get_element_safe(
                AppiumBy.ACCESSIBILITY_ID,
                constants.GHA_ACCOUNT_PARTICLE_BTN_ACCESSIBILITY_ID,
                timeout=3.0
            )
        if not account_icon:
            self._logger.error("Could not find AccountParticleButton on current screen.")
            return False
        if not self._click_element_with_fallback(account_icon, "AccountParticleButton"):
            return False
        time.sleep(1.5)
        home_settings_btn = self._find_home_settings_button(timeout=5.0)
        if not home_settings_btn:
            self._logger.info("'Home settings' not immediately visible, swiping up slightly...")
            self._swipe_up_slightly()
            home_settings_btn = self._find_home_settings_button(timeout=3.0)
        if not home_settings_btn:
            self._logger.error("Failed to find 'Home settings' button in account menu.")
            return False
        return self._click_element_with_fallback(home_settings_btn, "'Home settings' button")

    def _swipe_up_slightly(self) -> None:
        """Perform a gentle swipe up to reveal content below the fold in dialogs."""
        try:
            size = self.driver.get_window_size()
            start_x = size["width"] // 2
            start_y = int(size["height"] * 0.7)
            end_y = int(size["height"] * 0.4)
            self.driver.swipe(start_x, start_y, start_x, end_y, duration=300)
            time.sleep(1.0)
        except Exception as e:
            self._logger.debug(f"Swipe up failed: {e}")

    def _dismiss_modal_or_go_back(self) -> None:
        """Try clicking Done, Back, or Close if stuck on an unexpected screen."""
        dismiss_locators = [
            (AppiumBy.ACCESSIBILITY_ID, "Done"),
            (AppiumBy.ACCESSIBILITY_ID, "Back"),
            (AppiumBy.ACCESSIBILITY_ID, "Close"),
            (AppiumBy.ACCESSIBILITY_ID, "close"),
        ]
        for by, val in dismiss_locators:
            try:
                elem = self._get_element_safe(by, val, timeout=0.8)
                if elem:
                    elem.click()
                    time.sleep(1.0)
                    return
            except Exception:
                pass

    def get_active_tab(self) -> Optional[constants.TAB]:
        """Return the currently active tab (FAVORITES, DEVICES, AUTOMATIONS, ACTIVITY, SETTINGS, etc.).

        Returns:
            Optional[constants.TAB]: Enum value representing the active tab, or None if unknown.
        """
        try:
            settings_bar = self._find_elements(AppiumBy.IOS_CLASS_CHAIN, self.SETTINGS_NAV_BAR, timeout=0.8)
            if settings_bar and settings_bar[0].is_displayed():
                self._logger.info("Active Tab: SETTINGS")
                return constants.TAB.SETTINGS
        except Exception:
            pass
        try:
            home_btn = self._get_element_safe(AppiumBy.ACCESSIBILITY_ID, self.HOME_TAB_BTN)
            if home_btn and str(home_btn.get_attribute("value") or "0") == "1":
                active_chip = self._get_active_chip_under_home()
                if active_chip == constants.CHIP.FAVORITES:
                    self._logger.info("Active Tab: FAVORITES (Home Chip)")
                    return constants.TAB.FAVORITES
                elif active_chip == constants.CHIP.DEVICES:
                    self._logger.info("Active Tab: DEVICES (Home Chip)")
                    return constants.TAB.DEVICES
                else:
                    self._logger.info("Active Tab: HOME")
                    return constants.TAB.HOME
            activity_btn = self._get_element_safe(AppiumBy.ACCESSIBILITY_ID, self.ACTIVITY_TAB_BTN)
            if activity_btn and str(activity_btn.get_attribute("value") or "0") == "1":
                self._logger.info("Active Tab: ACTIVITY")
                return constants.TAB.ACTIVITY
            automations_btn = self._get_element_safe(AppiumBy.ACCESSIBILITY_ID, self.AUTOMATIONS_TAB_BTN)
            if automations_btn and str(automations_btn.get_attribute("value") or "0") == "1":
                self._logger.info("Active Tab: AUTOMATIONS")
                return constants.TAB.AUTOMATIONS
        except Exception as e:
            self._logger.debug(f"Error querying active tab state: {e}")
            return None
        self._logger.info("Active Tab: UNKNOWN")
        return None

    def _get_active_chip_under_home(self) -> Optional[constants.CHIP]:
        """Check which chip under Home tab is currently selected."""
        try:
            for chip_enum in [constants.CHIP.FAVORITES, constants.CHIP.DEVICES, constants.CHIP.CAMERAS, constants.CHIP.LIGHTS]:
                chip_btn = self._get_element_safe(
                    AppiumBy.IOS_CLASS_CHAIN,
                    f'**/XCUIElementTypeButton[`name == "{chip_enum.value}" AND visible == 1`]'
                )
                if chip_btn:
                    val = str(chip_btn.get_attribute("value") or "0")
                    is_selected = chip_btn.is_selected() or val in ("1", "true")
                    if is_selected:
                        return chip_enum
        except Exception:
            pass
        return None

    def go_to_tab(self, tab: constants.TAB) -> bool:
        """Navigate to a specified GHA tab (HOME, FAVORITES, DEVICES, AUTOMATIONS, ACTIVITY, SETTINGS).
        Args:
            tab (TAB): The target tab enum.
        Returns:
            bool: True if navigated successfully, False otherwise.
        """
        active_tab = self.get_active_tab()
        if active_tab == tab:
            self._logger.info(f"Already on tab: {tab.value}")
            return True
        current_tab_name = active_tab.value if active_tab and hasattr(active_tab, "value") else "UNKNOWN"
        self._logger.info(f"Navigating from {current_tab_name} to {tab.value}...")
        if active_tab == constants.TAB.SETTINGS:
            self._close_settings_page()
        match tab:
            case constants.TAB.HOME:
                return self._click_bottom_tab(self.HOME_TAB_BTN, "Home")
            case constants.TAB.FAVORITES:
                self._click_bottom_tab(self.HOME_TAB_BTN, "Home")
                return self.enter_chip_under_home_tab(constants.CHIP.FAVORITES)
            case constants.TAB.DEVICES:
                self._click_bottom_tab(self.HOME_TAB_BTN, "Home")
                return self.enter_chip_under_home_tab(constants.CHIP.DEVICES)
            case constants.TAB.AUTOMATIONS:
                return self._click_bottom_tab(self.AUTOMATIONS_TAB_BTN, "Automations")
            case constants.TAB.ACTIVITY:
                return self._click_bottom_tab(self.ACTIVITY_TAB_BTN, "Activity")
            case constants.TAB.SETTINGS:
                return self.enter_home_settings_page()
            case _:
                self._logger.error(f"Tab '{tab}' is not supported.")
                return False

    def enter_chip_under_home_tab(self, chip: Union[constants.CHIP, str]) -> bool:
        """Click on a specific category chip (Favorites, All devices, Cameras, Lights) under Home tab.
        Args:
            chip (CHIP or str): Target chip to click.
        Returns:
            bool: True if clicked successfully, False otherwise.
        """
        chip_label = chip.value if isinstance(chip, constants.CHIP) else str(chip)
        self._logger.info(f"Selecting chip: '{chip_label}' under Home tab...")
        locators = [
            f'**/XCUIElementTypeButton[`name == "{chip_label}" AND visible == 1`]',
            f'**/XCUIElementTypeButton[`label CONTAINS "{chip_label}" AND visible == 1`]',
            f'**/XCUIElementTypeStaticText[`name == "{chip_label}" AND visible == 1`]',
        ]
        for loc in locators:
            try:
                elems = self._find_elements(AppiumBy.IOS_CLASS_CHAIN, loc)
                if elems and elems[0].is_displayed():
                    elems[0].click()
                    time.sleep(1.5)
                    self._logger.info(f"Successfully selected chip '{chip_label}'.")
                    return True
            except Exception:
                pass
        self._logger.error(f"Failed to find chip '{chip_label}' under Home tab.")
        return False

    def _click_bottom_tab(self, accessibility_id: str, tab_name: str) -> bool:
        """Click on a bottom navigation bar button by accessibility ID."""
        try:
            btn = self._get_element_safe(AppiumBy.ACCESSIBILITY_ID, accessibility_id)
            if btn and btn.is_displayed():
                btn.click()
                time.sleep(1.5)
                self._logger.info(f"Switched to '{tab_name}' tab.")
                return True
        except WebDriverException as e:
            self._logger.error(f"Failed to click '{tab_name}' tab: {e}")
        return False

    def _close_settings_page(self) -> None:
        """Dismiss settings page by clicking the top-left close (X) or back button."""
        close_locators = [
            (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeNavigationBar[`name == "Settings" OR name == "Home settings"`]/**/XCUIElementTypeButton[1]'),
            (AppiumBy.ACCESSIBILITY_ID, "close"),
            (AppiumBy.ACCESSIBILITY_ID, "Close"),
            (AppiumBy.ACCESSIBILITY_ID, "Back"),
            (AppiumBy.ACCESSIBILITY_ID, "Done"),
        ]
        for by, val in close_locators:
            try:
                elems = self._find_elements(by, val, timeout=0.8)
                if elems and elems[0].is_displayed():
                    elems[0].click()
                    time.sleep(1.5)
                    return
            except Exception:
                pass