"""Page object for handling GHA Choose Whether You Want To Turn On Video History page on iOS.
NOTE: GHASession.__getattr__ returns the FIRST registered page that has a given attribute, so every
private helper / constant here is prefixed with `_vh_` / `VH_` to avoid being shadowed by same-named
members of other pages (e.g. `_click_next_btn` of the live video page).
"""
import time
from contextlib import contextmanager
from typing import Iterator, Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException
from common import constants
from common.base_page import BasePage
from page_object.iGHA.gha_exceptions import OOBEInternalErrorException


class GHAChooseWhetherYouWantToTurnOnVideoPage(BasePage):
    """Class for handling GHA Video History toggle and setup on iOS."""
    VH_NEXT_BTN_PREDICATE = 'label == "Next" OR name == "actionBarPrimaryButton"'
    # Locators for internal / offline / stream-removed error dialogs
    VH_INTERNAL_ERROR_PREDICATE = (
        'label == "Internal error encountered." OR name == "Internal error encountered." '
        'OR label CONTAINS[c] "Internal error encountered" OR name CONTAINS[c] "Internal error encountered" '
        'OR label == "The Internet connection appears to be offline." '
        'OR name == "The Internet connection appears to be offline." '
        'OR label CONTAINS[c] "Internet connection appears to be offline" '
        'OR name CONTAINS[c] "Internet connection appears to be offline" '
        'OR label CONTAINS[c] "Stream removed" OR name CONTAINS[c] "Stream removed" '
        'OR label CONTAINS[c] "NSPOSIXErrorDomain" OR name CONTAINS[c] "NSPOSIXErrorDomain" '
        'OR label CONTAINS[c] "Socket is not connected" OR name CONTAINS[c] "Socket is not connected"'
    )
    VH_ALERT_OK_PREDICATE = 'label == "OK" OR name == "OK"'
    VH_LOADING_PREDICATE = 'type == "XCUIElementTypeActivityIndicator" AND visible == 1'
    VH_SWITCH_ON_VALUES = ("1", "true")
    VH_PAGE_TIMEOUT = 20.0  # Max wait for the page (title + toggle) to appear
    VH_SPINNER_WAIT_TIMEOUT = 15.0  # Max wait for an active loading spinner to clear
    VH_TOGGLE_SETTLE_SECONDS = 1.5  # Watch for the internal error alert after tapping the toggle
    VH_LEAVE_PAGE_TIMEOUT = 10.0  # Max wait for the page transition after tapping Next
    VH_MAX_NEXT_ATTEMPTS = 3
    VH_POLL_INTERVAL = 0.5

    @contextmanager
    def _vh_no_implicit_wait(self) -> Iterator[None]:
        """Temporarily disable implicit wait so existence checks return immediately."""
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

    def _vh_quick_find(self, by: str, value: str) -> Optional[WebElement]:
        """Return the first matching element immediately (no waiting), or None."""
        with self._vh_no_implicit_wait():
            try:
                elements = self.driver.find_elements(by, value)
                return elements[0] if elements else None
            except WebDriverException:
                return None

    def _vh_get_toggle(self) -> Optional[WebElement]:
        """Get the 'Video history' switch element (XCUIElementTypeSwitch)."""
        return self._vh_quick_find(AppiumBy.ACCESSIBILITY_ID, constants.GHA_TOGGLE_ACCESSIBILITY_ID)

    def _vh_get_title(self) -> Optional[WebElement]:
        """Get the 'Video history' title element (also used as the page indicator)."""
        return self._vh_quick_find(AppiumBy.ACCESSIBILITY_ID,
                                   constants.GHA_VIDEO_HISTORY_ACCESSIBILITY_ID)

    def _vh_get_next_btn(self) -> Optional[WebElement]:
        """Get the 'Next' button using ACCESSIBILITY_ID or predicate fallback."""
        return (
                self._vh_quick_find(AppiumBy.ACCESSIBILITY_ID,
                                    constants.GHA_NEXT_BTN_ACCESSIBILITY_ID)
                or self._vh_quick_find(AppiumBy.IOS_PREDICATE, self.VH_NEXT_BTN_PREDICATE)
        )

    def _vh_is_on_page(self) -> bool:
        return self._vh_get_title() is not None

    def _vh_check_for_internal_error(self) -> None:
        """If the 'Internal error encountered.' or 'The Internet connection appears to be offline.' alert is shown, click OK and raise.
        Raises:
            OOBEInternalErrorException: If the error alert is displayed.
        """
        alert_elem = self._vh_quick_find(AppiumBy.IOS_PREDICATE, self.VH_INTERNAL_ERROR_PREDICATE)
        if alert_elem is None:
            return
        try:
            alert_text = (
                    alert_elem.get_attribute("label")
                    or alert_elem.get_attribute("name")
                    or "Internal error encountered."
            ).strip()
        except WebDriverException:
            alert_text = "Internal error encountered."
        self._logger.warning(f"[VideoHistory] Detected '{alert_text}' alert dialog!")
        if hasattr(BasePage, "capture_failure_screenshot"):
            BasePage.capture_failure_screenshot(
                self.driver,
                reason=f"GHA displayed '{alert_text}' during Video History setup.",
                force=False,
                lock=True,
            )
        for _ in range(4):
            ok_btn = self._vh_quick_find(AppiumBy.IOS_PREDICATE, self.VH_ALERT_OK_PREDICATE)
            if ok_btn is not None:
                try:
                    ok_btn.click()
                    self._logger.info("[VideoHistory] Clicked 'OK' on internal error alert.")
                    break
                except WebDriverException as e:
                    self._logger.warning(f"[VideoHistory] Failed to click OK on alert: {e}")
            time.sleep(self.VH_POLL_INTERVAL)
        raise OOBEInternalErrorException(
            f"GHA displayed '{alert_text}' during Video History setup.")

    def _vh_watch_for_internal_error(self, seconds: float) -> None:
        """Keep checking for the internal error alert for `seconds` (raises if it shows up)."""
        deadline = time.time() + seconds
        while True:
            self._vh_check_for_internal_error()
            if time.time() >= deadline:
                return
            time.sleep(self.VH_POLL_INTERVAL)

    def _vh_is_spinner_visible(self) -> bool:
        """Return True if a loading ActivityIndicator is currently displayed."""
        with self._vh_no_implicit_wait():
            try:
                spinners = self.driver.find_elements(AppiumBy.IOS_PREDICATE,
                                                     self.VH_LOADING_PREDICATE)
                return any(el.is_displayed() for el in spinners)
            except WebDriverException:
                return False

    def _vh_wait_out_spinner(self, timeout: float = VH_SPINNER_WAIT_TIMEOUT) -> bool:
        """Wait until any active loading spinner clears (checking internal error alerts along the way)."""
        deadline = time.time() + timeout
        saw_spinner = False
        while True:
            self._vh_check_for_internal_error()
            if not self._vh_is_spinner_visible():
                if saw_spinner:
                    self._logger.info("[VideoHistory] Loading spinner cleared.")
                return True
            if not saw_spinner:
                self._logger.info(
                    f"[VideoHistory] Loading spinner active; waiting up to {timeout:.0f}s before proceeding..."
                )
                saw_spinner = True
            if time.time() >= deadline:
                self._logger.warning(
                    f"[VideoHistory] Loading spinner still active after {timeout:.0f}s.")
                return False
            time.sleep(self.VH_POLL_INTERVAL)

    def _vh_wait_for_page(self, timeout: float = VH_PAGE_TIMEOUT) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._vh_check_for_internal_error()
            if self._vh_get_title() is not None and self._vh_get_toggle() is not None:
                return True
            time.sleep(self.VH_POLL_INTERVAL)
        return False

    def _vh_wait_until_left_page(self, timeout: float = VH_LEAVE_PAGE_TIMEOUT) -> bool:
        start_ts = time.time()
        deadline = start_ts + timeout
        hard_cap = start_ts + timeout + self.VH_SPINNER_WAIT_TIMEOUT
        gone_polls = 0
        logged_spinner = False
        while time.time() < deadline:
            self._vh_check_for_internal_error()
            spinning = self._vh_is_spinner_visible()
            if spinning:
                gone_polls = 0
                if not logged_spinner:
                    self._logger.info(
                        "[VideoHistory] Post-click loading spinner active; waiting for transition...")
                    logged_spinner = True
                deadline = min(hard_cap, max(deadline, time.time() + 4.0))
            elif not self._vh_is_on_page():
                gone_polls += 1
                if gone_polls >= 2:
                    return True
            else:
                gone_polls = 0
            time.sleep(self.VH_POLL_INTERVAL)
        return False

    def is_video_history_enabled(self) -> bool:
        """Check if the video history toggle is currently turned ON (value == '1').
        Returns:
            bool: True if turned ON, False otherwise.
        """
        toggle = self._vh_get_toggle()
        if toggle is None:
            self._logger.warning("Video history toggle not found on screen.")
            return False
        try:
            value = str(toggle.get_attribute("value") or "0")
        except WebDriverException:
            return False
        is_on = value in self.VH_SWITCH_ON_VALUES
        self._logger.info(
            f"Current Video History Toggle state: {'ON' if is_on else 'OFF'} (value={value})")
        return is_on

    def _vh_turn_on_toggle(self) -> bool:
        """Ensure the video history toggle is turned ON.
        Raises:
            OOBEInternalErrorException: If the internal error alert appears.
        """
        self._logger.info("Executing flow: Turn ON Video History and proceed with Next...")
        if not self._vh_wait_for_page():
            self._logger.error("Cannot turn on Video History: title / toggle not found.")
            return False
        self._vh_wait_out_spinner()
        if self.is_video_history_enabled():
            self._logger.info("Video History toggle is already ON.")
            return True
        self._logger.info("Video History toggle is OFF. Clicking to turn ON...")
        for mode in ("click", "element_tap", "coord_tap"):
            toggle = self._vh_get_toggle()  # Fresh lookup: the old element may be stale after a value change.
            if toggle is None:
                break
            try:
                if mode == "click":
                    toggle.click()
                elif mode == "element_tap":
                    self._logger.warning(
                        "Toggle click did not change state to ON. Retrying element tap...")
                    self.driver.execute_script("mobile: tap", {"elementId": toggle.id})
                else:
                    rect = toggle.rect
                    knob_x = int(rect["x"] + max(rect["width"] - 14, rect["width"] * 0.75))
                    knob_y = int(rect["y"] + rect["height"] / 2)
                    self._logger.warning(
                        f"Toggle still OFF. Retrying right-knob coordinate tap at ({knob_x}, {knob_y})..."
                    )
                    self.driver.execute_script("mobile: tap", {"x": knob_x, "y": knob_y})
            except Exception as e:
                self._logger.warning(f"Failed to interact with Video History toggle ({mode}): {e}")
            self._vh_watch_for_internal_error(self.VH_TOGGLE_SETTLE_SECONDS)
            self._vh_wait_out_spinner(timeout=8.0)
            if self.is_video_history_enabled():
                self._logger.info("Successfully turned ON Video History toggle.")
                return True
        self._logger.error("Failed to turn ON Video History toggle.")
        return False

    def _vh_tap_next(self, btn: WebElement, force_coordinates: bool = False) -> None:
        """Tap the 'Next' button normally or via screen coordinates on retry."""
        if not force_coordinates:
            try:
                btn.click()
                return
            except WebDriverException as e:
                self._logger.warning(
                    f"Direct click failed: {e}. Trying coordinate/element tap fallback...")
        try:
            rect = btn.rect
            cx = int(rect["x"] + rect["width"] / 2)
            cy = int(rect["y"] + rect["height"] / 2)
            if cx > 0 and cy > 0:
                self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                return
        except Exception:
            pass
        try:
            win = self.driver.get_window_size()
            w = int(win.get("width", 390))
            h = int(win.get("height", 844))
            self.driver.execute_script("mobile: tap", {"x": max(40, w - 55), "y": max(40, h - 58)})
            return
        except Exception:
            pass
        try:
            self.driver.execute_script("mobile: tap", {"elementId": btn.id})
        except WebDriverException as tap_err:
            self._logger.warning(f"Tap fallback failed: {tap_err}")

    def _vh_click_next_and_verify(self) -> bool:
        """Click 'Next' and verify the page transitioned, retrying if the tap was swallowed.
        Raises:
            OOBEInternalErrorException: If the internal error alert appears.
        """
        for attempt in range(1, self.VH_MAX_NEXT_ATTEMPTS + 1):
            self._vh_check_for_internal_error()
            self._vh_wait_out_spinner()
            btn = self._vh_get_next_btn()
            if btn is None:
                if not self._vh_is_on_page():
                    self._logger.info("[VideoHistory] Already left Video history page.")
                    return True
                self._logger.error("Cannot click 'Next': Button element not found.")
                return False
            use_coords = attempt >= 2
            mode_label = "coordinate tap" if use_coords else "click"
            self._logger.info(
                f"[VideoHistory] Clicking 'Next' button ({mode_label}, attempt {attempt}/{self.VH_MAX_NEXT_ATTEMPTS})..."
            )
            self._vh_tap_next(btn, force_coordinates=use_coords)
            if self._vh_wait_until_left_page():
                self._logger.info("[VideoHistory] Successfully left Video history page.")
                return True
            self._logger.warning(
                f"[VideoHistory] Still on Video history page after tapping 'Next' "
                f"(attempt {attempt}/{self.VH_MAX_NEXT_ATTEMPTS}). Retrying..."
            )
        self._logger.error(
            "[VideoHistory] Failed to leave Video history page after all 'Next' attempts.")
        return False

    def enable_video_history_and_proceed(self) -> bool:
        """Turn on the video history toggle and click Next.
        Returns:
            bool: True if both actions succeeded, False otherwise.
        Raises:
            OOBEInternalErrorException: If GHA shows 'Internal error encountered.' or 'The Internet connection appears to be offline.'.
        """
        turned_on = self._vh_turn_on_toggle()
        if not turned_on and not self._vh_is_on_page():
            self._logger.error("[VideoHistory] Not on Video history page. Skip clicking 'Next'.")
            return False
        clicked_next = self._vh_click_next_and_verify()
        return turned_on and clicked_next
