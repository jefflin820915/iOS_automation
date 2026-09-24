"""Page object for the 'Enter pairing code' page on iOS."""
import re
import time
from contextlib import contextmanager
from typing import Iterator, Optional, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException
from common import constants
from common.base_page import BasePage

Locator = Tuple[str, str]


class GHAEnterPairingCodePage(BasePage):
    """Enter the manual pairing code, verify it, and tap Continue."""
    EPC_HEADLINE: Locator = (
        AppiumBy.IOS_PREDICATE,
        'type == "XCUIElementTypeStaticText" AND label == "Enter pairing code"',
    )
    EPC_TEXT_FIELD: Locator = (
        AppiumBy.CLASS_NAME,
        getattr(constants, "GHA_TEXT_EDIT_VIEW_CLASS_NAME", "XCUIElementTypeTextField"),
    )
    EPC_CONTINUE_BTN: Locator = (
        AppiumBy.IOS_PREDICATE,
        'type == "XCUIElementTypeButton" AND (label == "Continue" OR name == "Continue")',
    )
    EPC_PAGE_TIMEOUT = 30.0
    EPC_CONTINUE_ENABLE_TIMEOUT = 10.0
    EPC_LEAVE_TIMEOUT = 15.0
    EPC_MAX_TYPE_ATTEMPTS = 3
    EPC_POLL_INTERVAL = 0.5

    @contextmanager
    def _epc_no_implicit_wait(self) -> Iterator[None]:
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

    def _epc_find_now(self, locator: Locator) -> Optional[WebElement]:
        with self._epc_no_implicit_wait():
            try:
                elements = self.driver.find_elements(*locator)
                return elements[0] if elements else None
            except WebDriverException:
                return None

    def _epc_wait_for(self, locator: Locator, timeout: float) -> Optional[WebElement]:
        deadline = time.time() + timeout
        while True:
            element = self._epc_find_now(locator)
            if element is not None or time.time() >= deadline:
                return element
            time.sleep(self.EPC_POLL_INTERVAL)

    def _epc_wait_gone(self, locator: Locator, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._epc_find_now(locator) is None:
                return True
            time.sleep(self.EPC_POLL_INTERVAL)
        return False

    @staticmethod
    def _epc_digits(text: str) -> str:
        return re.sub(r"\D", "", text or "")

    def _epc_read_field_digits(self) -> str:
        field = self._epc_find_now(self.EPC_TEXT_FIELD)
        if field is None:
            return ""
        try:
            return self._epc_digits(field.get_attribute("value") or "")
        except WebDriverException:
            return ""

    def _epc_type_code(self, expected_digits: str) -> bool:
        """Type the code and verify the field contains exactly the expected digits."""
        for attempt in range(1, self.EPC_MAX_TYPE_ATTEMPTS + 1):
            field = self._epc_wait_for(self.EPC_TEXT_FIELD, 10.0)
            if field is None:
                self._logger.error("[PairingCode] Pairing code text field not found.")
                return False
            self._logger.info(f"[PairingCode] Typing pairing code (attempt {attempt}/{self.EPC_MAX_TYPE_ATTEMPTS})...")
            try:
                field.click()
                time.sleep(0.8)
                field.clear()
                field.send_keys(expected_digits)
            except WebDriverException as e:
                self._logger.warning(f"[PairingCode] send_keys failed: {e}. Trying active element...")
                try:
                    self.driver.switch_to.active_element.send_keys(expected_digits)
                except WebDriverException as e2:
                    self._logger.warning(f"[PairingCode] Active element typing failed: {e2}")
            time.sleep(1.0)
            actual = self._epc_read_field_digits()
            if actual == expected_digits:
                self._logger.info("[PairingCode] Pairing code entered and verified.")
                return True
            self._logger.warning(
                f"[PairingCode] Field mismatch: expected {len(expected_digits)} digits, got '{actual}'. Retrying..."
            )
        return False

    def _epc_wait_continue_enabled(self) -> Optional[WebElement]:
        deadline = time.time() + self.EPC_CONTINUE_ENABLE_TIMEOUT
        while time.time() < deadline:
            btn = self._epc_find_now(self.EPC_CONTINUE_BTN)
            try:
                if btn is not None and btn.is_enabled():
                    return btn
            except WebDriverException:
                pass
            time.sleep(self.EPC_POLL_INTERVAL)
        return None

    def enter_pairing_code(self, pairing_code: str) -> bool:
        """Enter the pairing code, tap Continue, and verify the page transitioned."""
        expected_digits = self._epc_digits(str(pairing_code or ""))
        self._logger.info(f"[PairingCode] Pairing code length: {len(expected_digits)} digits.")
        if len(expected_digits) not in (11, 21):
            self._logger.error(
                f"[PairingCode] Invalid pairing code '{pairing_code}' "
                f"({len(expected_digits)} digits, expected 11 or 21)."
            )
            return False
        if self._epc_wait_for(self.EPC_HEADLINE, self.EPC_PAGE_TIMEOUT) is None:
            self._logger.error("[PairingCode] 'Enter pairing code' page did not appear.")
            return False
        time.sleep(1.0)
        if not self._epc_type_code(expected_digits):
            self._logger.error("[PairingCode] Failed to enter pairing code into the field.")
            return False
        for attempt in (1, 2):
            btn = self._epc_wait_continue_enabled()
            if btn is None:
                self._logger.error("[PairingCode] 'Continue' button stayed disabled.")
                return False
            self._logger.info(f"[PairingCode] Clicking 'Continue' (attempt {attempt}/2)...")
            try:
                btn.click()
            except WebDriverException as e:
                self._logger.warning(f"[PairingCode] Continue click failed: {e}")
            if self._epc_wait_gone(self.EPC_HEADLINE, self.EPC_LEAVE_TIMEOUT):
                self._logger.info("[PairingCode] Left 'Enter pairing code' page.")
                return True
            self._logger.warning("[PairingCode] Still on 'Enter pairing code' page. Retrying Continue...")
        self._logger.error("[PairingCode] Failed to proceed past 'Enter pairing code' page.")
        return False