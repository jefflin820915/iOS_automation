"""Page object for the 'Your camera device is ready' page on iOS."""
import time
from contextlib import contextmanager
from typing import Iterator, Optional, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException
from common import constants
from common.base_page import BasePage

Locator = Tuple[str, str]


class GHAYourCameraDeviceIsReadyPage(BasePage):
    """Handles the final 'Your camera device is ready' page and its 'Done' button.
    NOTE: Private helpers are prefixed with `_ready_` to avoid MRO name collisions in GHASession.
    """
    READY_HEADLINE: Locator = (
        AppiumBy.IOS_PREDICATE,
        'type == "XCUIElementTypeStaticText" AND label BEGINSWITH "Your camera device is ready"',
    )
    READY_DONE_BTN: Locator = (
        AppiumBy.IOS_PREDICATE,
        'type == "XCUIElementTypeButton" AND (name == "{0}" OR label == "Done")'.format(
            getattr(constants, "GHA_DONE_BTN_ACCESSIBILITY_ID", "Done")
        ),
    )
    READY_PAGE_TIMEOUT = 120.0
    READY_BTN_SETTLE_TIMEOUT = 5.0
    READY_LEAVE_TIMEOUT = 8.0
    READY_MAX_ATTEMPTS = 3
    READY_POLL_INTERVAL = 0.3

    @contextmanager
    def _ready_no_implicit_wait(self) -> Iterator[None]:
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
    def _ready_no_idle_wait(self) -> Iterator[None]:
        """Temporarily disable WDA wait-for-idle so the tap is not delayed by animations."""
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

    def _ready_find_displayed(self, locator: Locator) -> Optional[WebElement]:
        """Return the first displayed element immediately, or None."""
        with self._ready_no_implicit_wait():
            try:
                for elem in self.driver.find_elements(*locator):
                    if elem.is_displayed():
                        return elem
            except WebDriverException:
                pass
        return None

    def _ready_wait_for(self, locator: Locator, timeout: float) -> Optional[WebElement]:
        deadline = time.time() + timeout
        while True:
            elem = self._ready_find_displayed(locator)
            if elem is not None or time.time() >= deadline:
                return elem
            time.sleep(self.READY_POLL_INTERVAL)

    def _ready_wait_gone(self, locator: Locator, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._ready_find_displayed(locator) is None:
                return True
            time.sleep(self.READY_POLL_INTERVAL)
        return False

    def _ready_wait_done_clickable(self) -> Optional[WebElement]:
        """Wait until 'Done' is enabled and its rect stops changing (transition finished)."""
        deadline = time.time() + self.READY_BTN_SETTLE_TIMEOUT
        last_rect = None
        btn = None
        while time.time() < deadline:
            btn = self._ready_find_displayed(self.READY_DONE_BTN)
            if btn is not None:
                try:
                    rect = btn.rect
                    if btn.is_enabled() and rect == last_rect:
                        return btn
                    last_rect = rect
                except WebDriverException:
                    last_rect = None
            time.sleep(self.READY_POLL_INTERVAL)
        return btn

    def _ready_tap(self, btn: WebElement, use_coordinates: bool) -> None:
        with self._ready_no_idle_wait():
            if use_coordinates:
                rect = btn.rect
                self.driver.execute_script("mobile: tap", {
                    "x": int(rect["x"] + rect["width"] / 2),
                    "y": int(rect["y"] + rect["height"] / 2),
                })
            else:
                btn.click()

    def is_your_camera_device_is_ready_page(self, timeout: float = 0) -> bool:
        return self._ready_wait_for(self.READY_HEADLINE, timeout) is not None
    def click_done_btn(self) -> bool:
        """Wait for the 'Your camera device is ready' page, tap 'Done', and verify the page closed.
        Returns:
            True if the page was left successfully, False otherwise.
        """
        self._logger.info("[CameraReady] Waiting for 'Your camera device is ready' page...")
        if self._ready_wait_for(self.READY_HEADLINE, self.READY_PAGE_TIMEOUT) is None:
            self._logger.error(
                f"[CameraReady] Page did not appear within {self.READY_PAGE_TIMEOUT:.0f}s."
            )
            return False
        for attempt in range(1, self.READY_MAX_ATTEMPTS + 1):
            btn = self._ready_wait_done_clickable()
            if btn is None:
                if not self.is_your_camera_device_is_ready_page():
                    self._logger.info("[CameraReady] Page already closed.")
                    return True
                self._logger.error("[CameraReady] 'Done' button not found.")
                return False
            use_coordinates = attempt > 1
            self._logger.info(
                f"[CameraReady] Clicking 'Done' ({'coordinate tap' if use_coordinates else 'click'}, "
                f"attempt {attempt}/{self.READY_MAX_ATTEMPTS})..."
            )
            try:
                self._ready_tap(btn, use_coordinates)
            except WebDriverException as e:
                self._logger.warning(f"[CameraReady] Tap on 'Done' failed: {e}")
            if self._ready_wait_gone(self.READY_HEADLINE, self.READY_LEAVE_TIMEOUT):
                self._logger.info("[CameraReady] Left 'Your camera device is ready' page.")
                return True
            self._logger.warning("[CameraReady] Still on page after tapping 'Done'. Retrying...")
        self._logger.error("[CameraReady] Failed to leave 'Your camera device is ready' page.")
        return False