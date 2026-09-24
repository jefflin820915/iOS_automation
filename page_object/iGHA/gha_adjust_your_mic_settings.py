"""Page object for handling the 'Adjust your mic settings' page on iOS.
NOTE: GHASession inherits from many page classes, so every private helper / constant here
is prefixed with `_mic_` / `MIC_` to avoid being shadowed via MRO by same-named members
of other pages (e.g. `_click_next_btn` of the live video page).
"""
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from common import constants
from common.base_page import BasePage


class OOBEInternalErrorException(Exception):
    """Raised when GHA displays 'Internal error encountered.' modal during post-commissioning OOBE."""


class GHAAdjustYourMicSettingsPage(BasePage):
    """Class for managing microphone and audio recording toggles on the mic settings page."""
    MIC_MICROPHONE_SWITCH_CLASS_CHAIN = '**/XCUIElementTypeCell[`label == "Microphone"`]/**/XCUIElementTypeSwitch'
    MIC_AUDIO_RECORDING_SWITCH_CLASS_CHAIN = '**/XCUIElementTypeCell[`label == "Audio recording"`]/**/XCUIElementTypeSwitch'
    MIC_PAGE_INDICATOR_PREDICATE = (
        '(type == "XCUIElementTypeStaticText" AND label == "Adjust your mic settings") OR '
        '(type == "XCUIElementTypeCell" AND (label == "Microphone" OR label == "Audio recording"))'
    )
    MIC_NEXT_BTN_PREDICATE = 'label == "Next" OR name == "actionBarPrimaryButton"'
    MIC_LOADING_PREDICATE = 'type == "XCUIElementTypeActivityIndicator" AND visible == 1'
    MIC_INTERNAL_ERROR_PREDICATE = 'label == "Internal error encountered." OR name == "Internal error encountered."'
    MIC_ALERT_OK_PREDICATE = 'label == "OK" OR name == "OK"'
    MIC_SWITCH_ON_VALUES = ("1", "true")
    MIC_IDLE_TIMEOUT = 20.0          # Max wait for page to become idle
    MIC_IDLE_STABLE_SECONDS = 1.5    # Idle state must hold this long before tapping Next
    MIC_LEAVE_PAGE_TIMEOUT = 8.0     # Max wait for page transition after tapping Next
    MIC_SWITCH_LOCATE_TIMEOUT = 5.0
    MIC_SWITCH_STATE_TIMEOUT = 3.0
    MIC_MAX_NEXT_ATTEMPTS = 3
    MIC_POLL_INTERVAL = 0.5

    @contextmanager
    def _mic_no_implicit_wait(self) -> Iterator[None]:
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

    @contextmanager
    def _mic_no_idle_wait(self) -> Iterator[None]:
        """Temporarily disable WDA's wait-for-app-idle so taps are not delayed ~10s during loading."""
        previous: Any = None
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

    def _mic_quick_find(self, by: str, locator_value: str) -> Optional[WebElement]:
        """Return the first matching element immediately (no waiting), or None."""
        with self._mic_no_implicit_wait():
            try:
                elements = self.driver.find_elements(by, locator_value)
                return elements[0] if elements else None
            except WebDriverException:
                return None

    def _mic_tap_element_center(self, element: WebElement) -> None:
        """Coordinate tap at the element's center (avoids stale elementId references)."""
        rect = element.rect
        self.driver.execute_script("mobile: tap", {
            "x": int(rect["x"] + rect["width"] / 2),
            "y": int(rect["y"] + rect["height"] / 2),
        })

    def _mic_get_next_btn(self) -> Optional[WebElement]:
        next_id = getattr(constants, "GHA_NEXT_BTN_ACCESSIBILITY_ID", "Next")
        return (
                self._mic_quick_find(AppiumBy.ACCESSIBILITY_ID, next_id)
                or self._mic_quick_find(AppiumBy.IOS_PREDICATE, self.MIC_NEXT_BTN_PREDICATE)
        )

    def _mic_is_on_page(self) -> bool:
        return self._mic_quick_find(AppiumBy.IOS_PREDICATE, self.MIC_PAGE_INDICATOR_PREDICATE) is not None

    def _mic_is_idle_now(self) -> bool:
        """Next button is enabled and no loading spinner is visible."""
        if self._mic_quick_find(AppiumBy.IOS_PREDICATE, self.MIC_LOADING_PREDICATE):
            return False
        btn = self._mic_get_next_btn()
        try:
            return btn is not None and btn.is_enabled()
        except WebDriverException:
            return False

    def _mic_wait_until_idle(self, timeout: float = MIC_IDLE_TIMEOUT) -> bool:
        """Wait until the page stays idle for MIC_IDLE_STABLE_SECONDS continuously."""
        deadline = time.time() + timeout
        idle_since: Optional[float] = None
        while time.time() < deadline:
            self._mic_check_for_internal_error()
            if self._mic_is_idle_now():
                idle_since = idle_since or time.time()
                if time.time() - idle_since >= self.MIC_IDLE_STABLE_SECONDS:
                    return True
            else:
                idle_since = None
            time.sleep(self.MIC_POLL_INTERVAL)
        self._logger.warning(f"[MicSettings] Page still busy after {timeout:.0f}s.")
        return False

    def _mic_wait_until_left_page(self, timeout: float = MIC_LEAVE_PAGE_TIMEOUT) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._mic_check_for_internal_error()
            if not self._mic_is_on_page():
                return True
            time.sleep(self.MIC_POLL_INTERVAL)
        return False

    def _mic_check_for_internal_error(self) -> None:
        """Dismiss 'Internal error encountered.' alert if present and raise.
        Raises:
            OOBEInternalErrorException: If the internal error alert is displayed.
        """
        if not self._mic_quick_find(AppiumBy.IOS_PREDICATE, self.MIC_INTERNAL_ERROR_PREDICATE):
            return
        self._logger.warning("[MicSettings] Detected 'Internal error encountered.' alert dialog!")
        try:
            ok_btn = WebDriverWait(self.driver, 2.0).until(
                EC.element_to_be_clickable((AppiumBy.IOS_PREDICATE, self.MIC_ALERT_OK_PREDICATE))
            )
            ok_btn.click()
            self._logger.info("[MicSettings] Clicked 'OK' on internal error alert.")
        except Exception as dismiss_err:
            self._logger.warning(f"[MicSettings] Failed to click OK on alert: {dismiss_err}")
        raise OOBEInternalErrorException("GHA displayed 'Internal error encountered.' during Mic settings.")

    def _mic_locate_switch(self, class_chain: str, fallback_index: int) -> Optional[WebElement]:
        switch = self._mic_quick_find(AppiumBy.IOS_CLASS_CHAIN, class_chain)
        if switch:
            return switch
        with self._mic_no_implicit_wait():
            try:
                switches = self.driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeSwitch")
            except WebDriverException:
                return None
        return switches[fallback_index] if len(switches) > fallback_index else None

    def _mic_read_switch_state(self, class_chain: str, fallback_index: int) -> Optional[bool]:
        """Return True (ON) / False (OFF), or None if the switch cannot be read."""
        for _ in range(3):
            switch = self._mic_locate_switch(class_chain, fallback_index)
            if switch is None:
                return None
            try:
                return str(switch.get_attribute("value") or "0") in self.MIC_SWITCH_ON_VALUES
            except WebDriverException:
                time.sleep(0.3)
        return None

    def _mic_wait_for_switch_state(self, class_chain: str, fallback_index: int, expected: bool) -> bool:
        deadline = time.time() + self.MIC_SWITCH_STATE_TIMEOUT
        while time.time() < deadline:
            if self._mic_read_switch_state(class_chain, fallback_index) is expected:
                return True
            time.sleep(self.MIC_POLL_INTERVAL)
        return False

    def _mic_tap_switch(self, class_chain: str, fallback_index: int, use_coordinates: bool) -> bool:
        switch = self._mic_locate_switch(class_chain, fallback_index)
        if switch is None:
            return False
        try:
            with self._mic_no_idle_wait():
                if use_coordinates:
                    self._mic_tap_element_center(switch)
                else:
                    switch.click()
            return True
        except WebDriverException as e:
            self._logger.debug(f"Tap on switch failed: {e}")
            return False

    def _mic_turn_on_switch(self, switch_name: str, class_chain: str, fallback_index: int) -> bool:
        """Turn the switch ON if it is currently OFF, then wait for the backend save to finish."""
        deadline = time.time() + self.MIC_SWITCH_LOCATE_TIMEOUT
        state = self._mic_read_switch_state(class_chain, fallback_index)
        while state is None and time.time() < deadline:
            time.sleep(self.MIC_POLL_INTERVAL)
            state = self._mic_read_switch_state(class_chain, fallback_index)
        if state is None:
            self._logger.warning(f"'{switch_name}' switch element not found.")
            return False
        if state:
            self._logger.info(f"'{switch_name}' is already ON.")
            return True
        self._logger.info(f"'{switch_name}' is OFF. Clicking to turn ON...")
        for use_coordinates in (False, True):
            if use_coordinates:
                self._logger.warning(f"'{switch_name}' still OFF after click. Trying coordinate tap...")
            if self._mic_tap_switch(class_chain, fallback_index, use_coordinates) and \
                    self._mic_wait_for_switch_state(class_chain, fallback_index, expected=True):
                self._logger.info(f"Successfully turned ON '{switch_name}'.")
                self._mic_wait_until_idle()
                return True
        self._logger.error(f"Failed to turn ON '{switch_name}'.")
        return False

    def _mic_turn_on_all_toggles(self) -> bool:
        self._logger.info("Starting to enable all mic settings toggles...")
        results = [
            self._mic_turn_on_switch("Microphone", self.MIC_MICROPHONE_SWITCH_CLASS_CHAIN, 0),
            self._mic_turn_on_switch("Audio recording", self.MIC_AUDIO_RECORDING_SWITCH_CLASS_CHAIN, 1),
        ]
        return all(results)

    def _mic_tap_next(self, btn: WebElement) -> None:
        with self._mic_no_idle_wait():
            try:
                btn.click()
            except WebDriverException as e:
                self._logger.warning(f"Direct click failed: {e}. Trying coordinate tap fallback...")
                fresh_btn = self._mic_get_next_btn()
                if fresh_btn is not None:
                    self._mic_tap_element_center(fresh_btn)

    def _mic_click_next_and_verify(self) -> bool:
        """Click 'Next' and verify the page actually transitioned, retrying if the tap was swallowed.
        Raises:
            OOBEInternalErrorException: If internal error dialog appears.
        """
        for attempt in range(1, self.MIC_MAX_NEXT_ATTEMPTS + 1):
            self._mic_wait_until_idle()
            btn = self._mic_get_next_btn()
            if btn is None:
                if not self._mic_is_on_page():
                    self._logger.info("[MicSettings] Already left mic settings page.")
                    return True
                self._logger.error("[MicSettings] Cannot click 'Next': Button element not found.")
                return False
            self._logger.info(
                f"[MicSettings] Clicking 'Next' button (attempt {attempt}/{self.MIC_MAX_NEXT_ATTEMPTS})..."
            )
            try:
                self._mic_tap_next(btn)
            except WebDriverException as tap_err:
                self._logger.warning(f"[MicSettings] Failed to tap 'Next': {tap_err}")
            if self._mic_wait_until_left_page():
                self._logger.info("[MicSettings] Successfully left mic settings page.")
                return True
            self._logger.warning(
                f"[MicSettings] [Attempt {attempt}/{self.MIC_MAX_NEXT_ATTEMPTS}] Still on mic settings page "
                f"after tapping 'Next' (tap likely swallowed during loading). Retrying..."
            )
        self._logger.error("[MicSettings] Failed to leave mic settings page after all 'Next' attempts.")
        return False

    def enable_all_mic_settings_and_proceed(self) -> bool:
        """Turn ON all mic settings toggles and click Next.
        Returns:
            True if the page transitioned successfully, False otherwise.
        """
        self._mic_turn_on_all_toggles()
        return self._mic_click_next_and_verify()