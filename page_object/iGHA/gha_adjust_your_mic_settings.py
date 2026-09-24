"""Page object for handling the 'Adjust your mic settings' page on iOS."""
import time
from contextlib import contextmanager
from typing import Iterator, Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from common import constants
from common.base_page import BasePage


class OOBEInternalErrorException(Exception):
    """Raised when GHA displays 'Internal error encountered.' modal during post-commissioning OOBE."""

class GHAAdjustYourMicSettingsPage(BasePage):
    """Class for managing microphone and audio recording toggles on the mic settings page."""
    MICROPHONE_SWITCH_CLASS_CHAIN = '**/XCUIElementTypeCell[`label == "Microphone"`]/**/XCUIElementTypeSwitch'
    AUDIO_RECORDING_SWITCH_CLASS_CHAIN = '**/XCUIElementTypeCell[`label == "Audio recording"`]/**/XCUIElementTypeSwitch'
    PAGE_INDICATOR_PREDICATE = (
        'type == "XCUIElementTypeCell" AND (label == "Microphone" OR label == "Audio recording")'
    )
    NEXT_BTN_PREDICATE = 'label == "Next" OR name == "actionBarPrimaryButton"'
    LOADING_PREDICATE = 'type == "XCUIElementTypeActivityIndicator" AND visible == 1'
    INTERNAL_ERROR_PREDICATE = 'label == "Internal error encountered." OR name == "Internal error encountered."'
    ALERT_OK_PREDICATE = 'label == "OK" OR name == "OK"'
    SWITCH_ON_VALUES = ("1", "true")
    IDLE_TIMEOUT = 20.0          # Max wait for loading spinner to disappear / Next to be enabled
    LEAVE_PAGE_TIMEOUT = 8.0     # Max wait for page transition after tapping Next
    MAX_NEXT_ATTEMPTS = 3
    POLL_INTERVAL = 0.5

    @contextmanager
    def _no_implicit_wait(self) -> Iterator[None]:
        """Temporarily disable implicit wait so quick existence checks return immediately."""
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

    def _find_element(self, by: str, locator_value: str) -> Optional[WebElement]:
        """Find an element using specified locator strategy with explicit wait."""
        try:
            return WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((by, locator_value))
            )
        except TimeoutException:
            self._logger.error(f"Timed out waiting for element: by={by}, value='{locator_value}'")
            return None

    def _quick_find(self, by: str, locator_value: str) -> Optional[WebElement]:
        """Return the first matching element immediately (no waiting), or None."""
        with self._no_implicit_wait():
            try:
                elements = self.driver.find_elements(by, locator_value)
                return elements[0] if elements else None
            except WebDriverException:
                return None

    def _get_next_btn(self) -> Optional[WebElement]:
        """Get the 'Next' button using ACCESSIBILITY_ID or predicate."""
        next_id = getattr(constants, "GHA_NEXT_BTN_ACCESSIBILITY_ID", "Next")
        return (
                self._quick_find(AppiumBy.ACCESSIBILITY_ID, next_id)
                or self._quick_find(AppiumBy.IOS_PREDICATE, self.NEXT_BTN_PREDICATE)
        )

    def _is_on_mic_settings_page(self) -> bool:
        """Check whether the mic settings cells are still on screen."""
        return self._quick_find(AppiumBy.IOS_PREDICATE, self.PAGE_INDICATOR_PREDICATE) is not None

    def _is_loading(self) -> bool:
        return self._quick_find(AppiumBy.IOS_PREDICATE, self.LOADING_PREDICATE) is not None

    def _wait_until_page_idle(self, timeout: float = IDLE_TIMEOUT) -> bool:
        """Wait until no loading spinner is visible and the Next button is enabled."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._check_for_internal_error()
            btn = self._get_next_btn()
            try:
                next_enabled = btn is not None and btn.is_enabled()
            except WebDriverException:
                next_enabled = False
            if next_enabled and not self._is_loading():
                return True
            time.sleep(self.POLL_INTERVAL)
        self._logger.warning(f"[MicSettings] Page still busy after {timeout:.0f}s.")
        return False

    def _wait_until_left_page(self, timeout: float = LEAVE_PAGE_TIMEOUT) -> bool:
        """Wait until the mic settings page is gone (page transition completed)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._check_for_internal_error()
            if not self._is_on_mic_settings_page():
                return True
            time.sleep(self.POLL_INTERVAL)
        return False

    def _check_for_internal_error(self) -> None:
        """Dismiss 'Internal error encountered.' alert if present and raise.
        Raises:
            OOBEInternalErrorException: If the internal error alert is displayed.
        """
        if not self._quick_find(AppiumBy.IOS_PREDICATE, self.INTERNAL_ERROR_PREDICATE):
            return
        self._logger.warning("[MicSettings] Detected 'Internal error encountered.' alert dialog!")
        try:
            ok_btn = WebDriverWait(self.driver, 2.0).until(
                EC.element_to_be_clickable((AppiumBy.IOS_PREDICATE, self.ALERT_OK_PREDICATE))
            )
            ok_btn.click()
            self._logger.info("[MicSettings] Clicked 'OK' on internal error alert.")
        except Exception as dismiss_err:
            self._logger.warning(f"[MicSettings] Failed to click OK on alert: {dismiss_err}")
        raise OOBEInternalErrorException("GHA displayed 'Internal error encountered.' during Mic settings.")

    def _is_switch_on(self, switch_element: WebElement) -> bool:
        return str(switch_element.get_attribute("value") or "0") in self.SWITCH_ON_VALUES

    def _turn_on_switch(self, switch_element: WebElement, switch_name: str) -> bool:
        """Turn the switch ON if it is currently OFF, then wait for the backend save to finish."""
        try:
            if self._is_switch_on(switch_element):
                self._logger.info(f"'{switch_name}' is already ON.")
                return True
            self._logger.info(f"'{switch_name}' is OFF. Clicking to turn ON...")
            switch_element.click()
            time.sleep(1.0)
            if not self._is_switch_on(switch_element):
                self._logger.warning(f"Click on '{switch_name}' did not change state. Trying tap fallback...")
                self.driver.execute_script("mobile: tap", {"elementId": switch_element.id})
                time.sleep(1.0)
            is_on = self._is_switch_on(switch_element)
            if is_on:
                self._logger.info(f"Successfully turned ON '{switch_name}'.")
            else:
                self._logger.warning(f"Failed to turn ON '{switch_name}'.")
            self._wait_until_page_idle()
            return is_on
        except WebDriverException as e:
            self._logger.error(f"Failed to toggle '{switch_name}': {e}")
            return False

    def _find_switch(self, class_chain: str, fallback_index: int) -> Optional[WebElement]:
        """Find a switch by class chain, falling back to index among all switches."""
        switch = self._find_element(AppiumBy.IOS_CLASS_CHAIN, class_chain)
        if switch:
            return switch
        with self._no_implicit_wait():
            switches = self.driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeSwitch")
        return switches[fallback_index] if len(switches) > fallback_index else None

    def _turn_on_all_mic_toggles(self) -> bool:
        """Turn ON both 'Microphone' and 'Audio recording' switches.
        Returns:
            True if both switches are ON, False otherwise.
        """
        self._logger.info("Starting to enable all mic settings toggles...")
        results = []
        for name, class_chain, index in (
                ("Microphone", self.MICROPHONE_SWITCH_CLASS_CHAIN, 0),
                ("Audio recording", self.AUDIO_RECORDING_SWITCH_CLASS_CHAIN, 1),
        ):
            switch = self._find_switch(class_chain, index)
            if switch is None:
                self._logger.warning(f"'{name}' switch element not found.")
                results.append(False)
                continue
            results.append(self._turn_on_switch(switch, name))
        return all(results)

    def _tap_next(self, btn: WebElement) -> None:
        try:
            btn.click()
        except WebDriverException as e:
            self._logger.warning(f"Direct click failed: {e}. Trying tap fallback...")
            self.driver.execute_script("mobile: tap", {"elementId": btn.id})

    def _click_next_btn(self) -> bool:
        """Click 'Next' and verify the page actually transitioned, retrying if the tap was swallowed.
        Returns:
            True if the page left the mic settings screen, False otherwise.
        Raises:
            OOBEInternalErrorException: If internal error dialog appears.
        """
        for attempt in range(1, self.MAX_NEXT_ATTEMPTS + 1):
            self._wait_until_page_idle()
            btn = self._get_next_btn()
            if btn is None:
                if not self._is_on_mic_settings_page():
                    self._logger.info("Already left mic settings page.")
                    return True
                self._logger.error("Cannot click 'Next': Button element not found.")
                return False
            self._logger.info(f"Clicking 'Next' button (attempt {attempt}/{self.MAX_NEXT_ATTEMPTS})...")
            try:
                self._tap_next(btn)
            except WebDriverException as tap_err:
                self._logger.warning(f"Failed to tap 'Next': {tap_err}")
            if self._wait_until_left_page():
                self._logger.info("Successfully left mic settings page.")
                return True
            self._logger.warning(
                f"[Attempt {attempt}/{self.MAX_NEXT_ATTEMPTS}] Still on mic settings page after tapping 'Next' "
                f"(tap likely swallowed during loading). Retrying..."
            )
        self._logger.error("Failed to leave mic settings page after all 'Next' attempts.")
        return False

    def enable_all_mic_settings_and_proceed(self) -> bool:
        """Turn ON all mic settings toggles and click Next.
        Returns:
            True if the page transitioned successfully, False otherwise.
        """
        self._turn_on_all_mic_toggles()
        return self._click_next_btn()