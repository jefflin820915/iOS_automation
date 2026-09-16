"""Page object for handling GHA bottom tab navigation, category chips, and active tab detection on iOS."""
import time
from typing import Optional, Union, List
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
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
    SETTINGS_NAV_BAR = '**/XCUIElementTypeNavigationBar[`name == "Settings"`]'


    def _find_element(self, by: AppiumBy, locator_value: str) -> Optional[WebElement]:
        """Find an element using specified locator strategy with explicit wait."""
        try:
            return WebDriverWait(self.driver, 1.0).until(
                EC.presence_of_element_located((by, locator_value))
            )
        except TimeoutException:
            self._logger.error(f"Timed out waiting for element: by={by}, value='{locator_value}'")
            return None

    def _find_elements(self, by: AppiumBy, value: str) -> List[WebElement]:
        """Find an element using specified locator strategy with explicit wait."""
        try:
            return WebDriverWait(self.driver, 1.0).until(
                EC.presence_of_all_elements_located((by, value))
            )
        except TimeoutException:
            self._logger.error(f"Timed out waiting for element: by={by}, value='{value}'")
            return None

    def get_active_tab(self) -> constants.TAB:
        """Return the currently active tab (FAVORITES, DEVICES, AUTOMATIONS, ACTIVITY, SETTINGS, etc.).
        Returns:
            TAB: Enum value representing the active tab.
        """
        try:
            settings_bar = self._find_elements(AppiumBy.IOS_CLASS_CHAIN, self.SETTINGS_NAV_BAR)
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
            return False
        self._logger.info("Active Tab: UNKNOWN")
        return False

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
        self._logger.info(f"Navigating from {active_tab.value} to {tab.value}...")
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

    def enter_home_settings_page(self) -> bool:
        """Open Settings page by clicking the top-right account avatar."""
        self._logger.info("Opening Settings page from account avatar...")
        time.sleep(2)
        try:
            account_icon = self._find_element(AppiumBy.ACCESSIBILITY_ID, constants.GHA_ACCOUNT_PARTICLE_BTN_ACCESSIBILITY_ID)
            if account_icon.is_displayed():
                account_icon.click()
                time.sleep(5.0)
            home_settings_opts = self._find_element(AppiumBy.IOS_CLASS_CHAIN, constants.GHA_SETTING_PAGE_CLASS_CHAIN)
            if home_settings_opts.is_displayed():
                home_settings_opts.click()
                time.sleep(2.0)
                return True
        except Exception as e:
            self._logger.error(f"Failed to open Home Settings page: {e}")
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
        """Dismiss settings page by clicking the top-left close (X) button."""
        close_locators = [
            (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeNavigationBar[`name == "Settings"`]/**/XCUIElementTypeButton[1]'),
            (AppiumBy.ACCESSIBILITY_ID, "close"),
            (AppiumBy.ACCESSIBILITY_ID, "Close"),
        ]
        for by, val in close_locators:
            try:
                elems = self._find_elements(by, val)
                if elems and elems[0].is_displayed():
                    elems[0].click()
                    time.sleep(1.5)
                    return
            except Exception:
                pass
    def _get_element_safe(self, by: AppiumBy, value: str) -> Optional[WebElement]:
        """Safely find a visible element without throwing exceptions."""
        try:
            elems = self._find_elements(by, value)
            if elems and elems[0].is_displayed():
                return elems[0]
        except Exception:
            pass
        return None