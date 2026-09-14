"""Page object for handling the 'Adjust your mic settings' page on iOS."""
import time
from typing import List, Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from common import constants
from common.base_page import BasePage, PageNotPresentException
from utils import logging_utils


class GHAAdjustYourMicSettingsPage(BasePage):

    """Class for managing microphone and audio recording toggles on the mic settings page."""
    MICROPHONE_CELL_CLASS_CHAIN = '**/XCUIElementTypeCell[`label == "Microphone"`]/**/XCUIElementTypeSwitch'
    AUDIO_RECORDING_CELL_CLASS_CHAIN = '**/XCUIElementTypeCell[`label == "Audio recording"`]/**/XCUIElementTypeSwitch'


    def _find_element(self, by: AppiumBy, locator_value: str) -> Optional[WebElement]:
        """Find an element using specified locator strategy with explicit wait."""
        try:
            return WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((by, locator_value))
            )
        except TimeoutException:
            self._logger.error(f"Timed out waiting for element: by={by}, value='{locator_value}'")
            return None

    def _get_next_btn(self) -> Optional[WebElement]:
        """Get the 'Next' button using ACCESSIBILITY_ID or predicate."""
        btn = self._find_element(AppiumBy.ACCESSIBILITY_ID, getattr(constants, "GHA_NEXT_BTN_ACCESSIBILITY_ID", "Next"))
        if not btn:
            btn = self._find_element(AppiumBy.IOS_PREDICATE, 'label == "Next" OR name == "actionBarPrimaryButton"')
        return btn

    def _turn_on_switch(self, switch_element: WebElement, switch_name: str) -> bool:
        """Helper method to check switch state and click to turn ON if currently OFF."""
        try:
            value = str(switch_element.get_attribute("value") or "0")
            is_on = value in ("1", "true")
            if not is_on:
                self._logger.info(f"'{switch_name}' is OFF (value={value}). Clicking to turn ON...")
                switch_element.click()
                time.sleep(1.0)
                new_value = str(switch_element.get_attribute("value") or "0")
                if new_value in ("1", "true"):
                    self._logger.info(f"Successfully turned ON '{switch_name}'.")
                    return True
                else:
                    self._logger.warning(f"Click on '{switch_name}' failed to change state. Trying tap fallback...")
                    self.driver.execute_script("mobile: tap", {"elementId": switch_element.id})
                    time.sleep(1.0)
                    return str(switch_element.get_attribute("value") or "0") in ("1", "true")
            else:
                self._logger.info(f"'{switch_name}' is already ON.")
                return True
        except WebDriverException as e:
            self._logger.error(f"Failed to toggle '{switch_name}': {e}")
            return False

    def _turn_on_all_mic_toggles(self) -> bool:
        """Turn ON both 'Microphone' and 'Audio recording' switches on the page.
        Returns:
            bool: True if switches were enabled successfully, False otherwise.
        """
        self._logger.info("Starting to enable all mic settings toggles...")
        mic_switch = self._find_element(AppiumBy.IOS_CLASS_CHAIN, self.MICROPHONE_CELL_CLASS_CHAIN)
        if not mic_switch:
            self._logger.info("Executing flow: Turn ON/OFF all mic toggles...")
            switches = self.driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeSwitch")
            if switches:
                mic_switch = switches[0]
        if mic_switch:
            self._turn_on_switch(mic_switch, "Microphone")
            time.sleep(3.0)
        else:
            self._logger.warning("Microphone switch element not found.")
        audio_switch = self._find_element(AppiumBy.IOS_CLASS_CHAIN, self.AUDIO_RECORDING_CELL_CLASS_CHAIN)
        if not audio_switch:
            switches = self.driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeSwitch")
            if len(switches) > 1:
                audio_switch = switches[1]
        if audio_switch:
            self._turn_on_switch(audio_switch, "Audio recording")
            time.sleep(3.0)
        else:
            self._logger.warning("Audio recording switch element not found.")
        return True

    def _click_next_btn(self) -> bool:
        """Click the 'Next' button to proceed to the next step.
        Returns:
            bool: True if clicked successfully, False otherwise.
        """
        time.sleep(3.0)
        btn = self._get_next_btn()
        if not btn:
            self._logger.error("Cannot click 'Next': Button element not found.")
            return False
        try:
            self._logger.info("Clicking 'Next' button...")
            btn.click()
            time.sleep(1.0)
            return True
        except WebDriverException as e:
            self._logger.warning(f"Direct click failed: {e}. Trying tap fallback...")
            try:
                self.driver.execute_script("mobile: tap", {"elementId": btn.id})
                time.sleep(1.0)
                return True
            except Exception as tap_err:
                self._logger.error(f"Failed to click 'Next' button: {tap_err}")
                return False

    def enable_all_mic_settings_and_proceed(self) -> bool:
        """Convenient method to turn ON all mic settings toggles and click Next.
        Returns:
            bool: True if all actions succeeded, False otherwise.
        """
        self._turn_on_all_mic_toggles()
        return self._click_next_btn()