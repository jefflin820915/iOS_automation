"""Page object for the 'Your camera device is ready' page on iOS."""
import time
from contextlib import contextmanager
from typing import Iterator, List, Optional, Sequence, Tuple
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
    READY_HEADLINE_LOCATORS: List[Locator] = [
        (
            AppiumBy.IOS_PREDICATE,
            'type == "XCUIElementTypeStaticText" AND (label BEGINSWITH "Your camera device is ready" '
            'OR name BEGINSWITH "Your camera device is ready")',
        ),
        (
            AppiumBy.XPATH,
            '//XCUIElementTypeStaticText[starts-with(@label, "Your camera device is ready") '
            'or starts-with(@name, "Your camera device is ready")]',
        ),
    ]
    READY_DONE_BTN_LOCATORS: List[Locator] = [
        (
            AppiumBy.IOS_PREDICATE,
            'type == "XCUIElementTypeButton" AND (name == "{0}" OR label == "Done" OR name == "Done" '
            'OR name == "actionBarPrimaryButton")'.format(
                getattr(constants, "GHA_DONE_BTN_ACCESSIBILITY_ID", "Done")
            ),
        ),
        (AppiumBy.ACCESSIBILITY_ID, getattr(constants, "GHA_DONE_BTN_ACCESSIBILITY_ID", "Done")),
        (AppiumBy.ACCESSIBILITY_ID, "Done"),
        (AppiumBy.ACCESSIBILITY_ID, getattr(constants, "GHA_NEXT_BTN_ACCESSIBILITY_ID", "actionBarPrimaryButton")),
        (
            AppiumBy.XPATH,
            '//XCUIElementTypeButton[@name="Done" or @label="Done" or @name="actionBarPrimaryButton"]',
        ),
    ]
    READY_HOME_GRID_LOCATOR: Locator = (AppiumBy.ACCESSIBILITY_ID, "deviceTileGridCollectionView")
    READY_FALLBACK_DONE_COORDS: Tuple[int, int] = (335, 790)
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
            previous = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
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

    def _ready_find_first(
            self, locators: Sequence[Locator], allow_hidden: bool = True
    ) -> Optional[WebElement]:
        """Find the first matching element across locators.
        Prefers `is_displayed() == True`, but falls back to present elements with non-zero rect
        when `allow_hidden=True` because XCUITest often reports `visible="false"` on GHA OOBE screens.
        """
        hidden_candidate: Optional[WebElement] = None
        with self._ready_no_implicit_wait():
            for by, val in locators:
                try:
                    elems = self.driver.find_elements(by, val)
                except WebDriverException:
                    continue
                for elem in elems:
                    try:
                        if elem.is_displayed():
                            return elem
                        if allow_hidden and hidden_candidate is None:
                            hidden_candidate = elem
                    except WebDriverException:
                        continue
        return hidden_candidate

    def _ready_wait_for(
            self, locators: Sequence[Locator], timeout: float, allow_hidden: bool = True
    ) -> Optional[WebElement]:
        deadline = time.time() + timeout
        while True:
            elem = self._ready_find_first(locators, allow_hidden=allow_hidden)
            if elem is not None or time.time() >= deadline:
                return elem
            time.sleep(self.READY_POLL_INTERVAL)

    def _ready_is_headline_in_dom(self) -> bool:
        """Return True if the 'Your camera device is ready' headline still exists in the DOM.
        If a WebDriverException occurs while querying, conservatively returns True (still on page)
        so a transient WDA hiccup is never mistaken for 'Page already closed'.
        """
        with self._ready_no_implicit_wait():
            for by, val in self.READY_HEADLINE_LOCATORS:
                try:
                    elems = self.driver.find_elements(by, val)
                    if elems:
                        return True
                except WebDriverException:
                    return True
        return False

    def _ready_wait_gone(self, timeout: float) -> bool:
        """Wait until the 'Your camera device is ready' headline leaves the DOM for 2 consecutive polls
        (or the Home device grid becomes present)."""
        deadline = time.time() + timeout
        consecutive_gone = 0
        while time.time() < deadline:
            if not self._ready_is_headline_in_dom():
                consecutive_gone += 1
                if consecutive_gone >= 2:
                    return True
                if self._ready_find_first([self.READY_HOME_GRID_LOCATOR], allow_hidden=True) is not None:
                    return True
            else:
                consecutive_gone = 0
            time.sleep(self.READY_POLL_INTERVAL)
        return False

    def _ready_wait_done_clickable(self) -> Optional[WebElement]:
        """Wait until 'Done' is present (even if XCUITest reports visible=false) and its rect stabilizes."""
        deadline = time.time() + self.READY_BTN_SETTLE_TIMEOUT
        last_rect = None
        btn = None
        while time.time() < deadline:
            btn = self._ready_find_first(self.READY_DONE_BTN_LOCATORS, allow_hidden=True)
            if btn is not None:
                try:
                    rect = btn.rect
                    is_enabled = True
                    try:
                        is_enabled = btn.is_enabled()
                    except WebDriverException:
                        pass
                    if is_enabled and rect == last_rect and rect.get("width", 0) > 0:
                        return btn
                    last_rect = rect
                except WebDriverException:
                    return btn
            time.sleep(self.READY_POLL_INTERVAL)
        return btn

    def _ready_tap_coordinates(self, x: int, y: int) -> None:
        self._logger.info(f"[CameraReady] Tapping 'Done' at coordinates ({x}, {y})...")
        self.driver.execute_script("mobile: tap", {"x": int(x), "y": int(y)})

    def _ready_tap(self, btn: Optional[WebElement], force_coordinates: bool) -> None:
        """Tap the 'Done' button via standard click or coordinate tap fallback."""
        with self._ready_no_idle_wait():
            if btn is None:
                fx, fy = self.READY_FALLBACK_DONE_COORDS
                self._ready_tap_coordinates(fx, fy)
                return
            rect = None
            try:
                rect = btn.rect
            except Exception:
                pass
            displayed = False
            try:
                displayed = btn.is_displayed()
            except Exception:
                pass
            if not force_coordinates and displayed:
                try:
                    btn.click()
                    return
                except WebDriverException as click_err:
                    self._logger.warning(
                        f"[CameraReady] Direct click() failed ({click_err}); falling back to coordinate tap..."
                    )
            if rect and rect.get("width", 0) > 0 and rect.get("height", 0) > 0:
                cx = int(rect["x"] + rect["width"] / 2)
                cy = int(rect["y"] + rect["height"] / 2)
                self._ready_tap_coordinates(cx, cy)
                return
            try:
                self.driver.execute_script("mobile: tap", {"elementId": btn.id})
                return
            except Exception:
                fx, fy = self.READY_FALLBACK_DONE_COORDS
                self._ready_tap_coordinates(fx, fy)

    def is_your_camera_device_is_ready_page(self, timeout: float = 0) -> bool:
        return self._ready_wait_for(self.READY_HEADLINE_LOCATORS, timeout, allow_hidden=True) is not None

    def click_done_btn(self) -> bool:
        """Wait for the 'Your camera device is ready' page, tap 'Done', and verify the page closed.
        Returns:
            True if the page was left successfully, False otherwise.
        """
        self._logger.info("[CameraReady] Waiting for 'Your camera device is ready' page...")
        if self._ready_wait_for(self.READY_HEADLINE_LOCATORS, self.READY_PAGE_TIMEOUT, allow_hidden=True) is None:
            self._logger.error(
                f"[CameraReady] Page did not appear within {self.READY_PAGE_TIMEOUT:.0f}s."
            )
            return False
        has_tapped_done = False
        for attempt in range(1, self.READY_MAX_ATTEMPTS + 1):
            btn = self._ready_wait_done_clickable()
            if btn is None:
                # Only allow 'Page already closed' AFTER we have actually tapped 'Done' at least once!
                if has_tapped_done and not self._ready_is_headline_in_dom():
                    self._logger.info("[CameraReady] Page already closed after previous 'Done' tap.")
                    return True
                self._logger.warning(
                    f"[CameraReady] 'Done' button element not found on attempt {attempt}/{self.READY_MAX_ATTEMPTS}; "
                    "using fallback coordinate tap..."
                )
            force_coordinates = attempt > 1 or btn is None
            self._logger.info(
                f"[CameraReady] Clicking 'Done' ({'coordinate tap' if force_coordinates else 'click'}, "
                f"attempt {attempt}/{self.READY_MAX_ATTEMPTS})..."
            )
            try:
                self._ready_tap(btn, force_coordinates=force_coordinates)
                has_tapped_done = True
            except WebDriverException as e:
                self._logger.warning(f"[CameraReady] Tap on 'Done' failed: {e}")
            if self._ready_wait_gone(self.READY_LEAVE_TIMEOUT):
                self._logger.info("[CameraReady] Left 'Your camera device is ready' page.")
                return True
            self._logger.warning("[CameraReady] Still on page after tapping 'Done'. Retrying...")
        self._logger.error("[CameraReady] Failed to leave 'Your camera device is ready' page.")
        return False