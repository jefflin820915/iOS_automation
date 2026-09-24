"""Page object for the 'Add <device>' page (QR scan / Use pairing code) on iOS."""
import time
from contextlib import contextmanager
from typing import Iterator, Optional, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException
from common import constants
from common.base_page import BasePage

Locator = Tuple[str, str]


class GHAAddDevicePage(BasePage):
    """Handles the 'Use pairing code' entry on the add device (QR scan) page."""
    ADP_USE_PAIRING_CODE_BTN: Locator = (
        AppiumBy.IOS_PREDICATE,
        'type == "XCUIElementTypeButton" AND (label == "Use pairing code" OR name == "{}")'.format(
            getattr(constants, "GHA_USE_PAIRING_CODE_ACCESSIBILITY_ID", "Use pairing code")
        ),
    )
    ADP_ENTER_CODE_HEADLINE: Locator = (
        AppiumBy.IOS_PREDICATE,
        'type == "XCUIElementTypeStaticText" AND label == "Enter pairing code"',
    )
    ADP_BTN_TIMEOUT = 60.0
    ADP_TRANSITION_TIMEOUT = 10.0
    ADP_POLL_INTERVAL = 0.5
    @contextmanager

    def _adp_no_implicit_wait(self) -> Iterator[None]:
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

    def _adp_wait_for(self, locator: Locator, timeout: float) -> Optional[WebElement]:
        deadline = time.time() + timeout
        while True:
            with self._adp_no_implicit_wait():
                try:
                    elements = self.driver.find_elements(*locator)
                except WebDriverException:
                    elements = []
            if elements or time.time() >= deadline:
                return elements[0] if elements else None
            time.sleep(self.ADP_POLL_INTERVAL)

    def click_use_pairing_code_btn(self) -> bool:
        """Tap 'Use pairing code' and verify the 'Enter pairing code' page appears."""
        for attempt in (1, 2):
            btn = self._adp_wait_for(self.ADP_USE_PAIRING_CODE_BTN, self.ADP_BTN_TIMEOUT)
            if btn is None:
                if self._adp_wait_for(self.ADP_ENTER_CODE_HEADLINE, 0):
                    return True
                self._logger.error("[AddDevice] 'Use pairing code' button not found.")
                return False
            self._logger.info(f"[AddDevice] Clicking 'Use pairing code' (attempt {attempt}/2)...")
            try:
                btn.click()
            except WebDriverException as e:
                self._logger.warning(f"[AddDevice] Click failed: {e}")
            if self._adp_wait_for(self.ADP_ENTER_CODE_HEADLINE, self.ADP_TRANSITION_TIMEOUT):
                self._logger.info("[AddDevice] 'Enter pairing code' page displayed.")
                return True
            self._logger.warning("[AddDevice] 'Enter pairing code' page not shown yet. Retrying...")
        self._logger.error("[AddDevice] Failed to open 'Enter pairing code' page.")
        return False