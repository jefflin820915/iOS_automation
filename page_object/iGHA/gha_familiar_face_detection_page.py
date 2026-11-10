"""Page object for handling the optional 'Familiar face detection' OOBE page on iOS.

Appears after 'Adjust your mic settings' when the Home has an active Google Home Premium /
Nest Aware subscription (`ConciergeFamiliarFaceDetectionIntroViewControllerV2`).
If present, clicks 'Skip' (`otherBarButtonItem`) and verifies the page transitions away;
if not present (e.g. GHA moves directly to 'Stay in the know' or 'Your camera device is ready'),
immediately continues to the next OOBE step without failing.

NOTE: Private helpers and constants are prefixed with `_ffd_` / `FFD_` to avoid MRO / delegation
name collisions in `GHASession.__getattr__`.
"""

from contextlib import contextmanager
import time
from typing import Any, Iterator, Optional, Sequence, Tuple

from appium.webdriver.common.appiumby import AppiumBy
from common import constants
from common.base_page import BasePage
from page_object.iGHA.gha_exceptions import OOBEInternalErrorException
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
from utils import logging_utils

Locator = Tuple[str, str]
IOS_PREDICATE_BY = getattr(AppiumBy, "IOS_PREDICATE", "-ios predicate string")
IOS_CLASS_CHAIN_BY = getattr(AppiumBy, "IOS_CLASS_CHAIN", "-ios class chain")


class GHAFamiliarFaceDetectionPage(BasePage):
    """Handles optional 'Familiar face detection' intro screen during iGHA Camera OOBE."""

    FFD_HEADLINE_LOCATORS: Tuple[Locator, ...] = (
        (
            IOS_PREDICATE_BY,
            'type IN {"XCUIElementTypeStaticText", "XCUIElementTypeOther"} AND ('
            'label == "Familiar face detection" OR name == "Familiar face detection" '
            'OR value == "Familiar face detection")',
        ),
        (
            IOS_PREDICATE_BY,
            'name IN {"setupHeaderViewTitleLabel", "HeaderView_headlineLabel", "Header_title"} AND ('
            'label CONTAINS[c] "Familiar face detection" OR value CONTAINS[c] "Familiar face detection")',
        ),
        (
            IOS_PREDICATE_BY,
            'type IN {"XCUIElementTypeStaticText", "XCUIElementTypeTextView"} AND ('
            'label CONTAINS[c] "Teach your cameras who you know" '
            'OR value CONTAINS[c] "Teach your cameras who you know")',
        ),
        (
            AppiumBy.XPATH,
            '//XCUIElementTypeStaticText[@label="Familiar face detection" or @name="Familiar face detection"]',
        ),
    )

    FFD_SELECT_CAMERAS_BTN_LOCATORS: Tuple[Locator, ...] = (
        (
            IOS_PREDICATE_BY,
            'type == "XCUIElementTypeButton" AND ('
            'label == "Select cameras" OR name == "Select cameras")',
        ),
        (AppiumBy.ACCESSIBILITY_ID, "Select cameras"),
    )

    FFD_SKIP_BTN_LOCATORS: Tuple[Locator, ...] = (
        (
            IOS_PREDICATE_BY,
            'type == "XCUIElementTypeButton" AND ('
            'label == "Skip" OR name == "Skip" OR name == "actionBarSecondaryButton")',
        ),
        (AppiumBy.ACCESSIBILITY_ID, "Skip"),
        (AppiumBy.ACCESSIBILITY_ID, "actionBarSecondaryButton"),
        (
            IOS_PREDICATE_BY,
            'type == "XCUIElementTypeStaticText" AND (label == "Skip" OR name == "Skip")',
        ),
        (
            AppiumBy.XPATH,
            '//XCUIElementTypeButton[@label="Skip" or @name="Skip" or @name="actionBarSecondaryButton"]',
        ),
    )

    # Downstream OOBE screens that indicate GHA skipped 'Familiar face detection' and moved on
    FFD_DOWNSTREAM_LOCATORS: Tuple[Locator, ...] = (
        (
            IOS_PREDICATE_BY,
            'type IN {"XCUIElementTypeStaticText", "XCUIElementTypeTextView"} AND ('
            'label BEGINSWITH[c] "Notifications from the" OR name BEGINSWITH[c] "Notifications from the" '
            'OR label CONTAINS[c] "notifications from the Google Home app" '
            'OR value CONTAINS[c] "notifications from the Google Home app" '
            'OR label CONTAINS[c] "Stay in the know" OR name CONTAINS[c] "Stay in the know" '
            'OR label CONTAINS[c] "Keep up to date" OR name CONTAINS[c] "Keep up to date" '
            'OR label BEGINSWITH "Your camera device is ready" '
            'OR name BEGINSWITH "Your camera device is ready")',
        ),
        (AppiumBy.ACCESSIBILITY_ID, "deviceTileGridCollectionView"),
    )

    FFD_LOADING_PREDICATE: str = 'type == "XCUIElementTypeActivityIndicator" AND visible == 1'

    FFD_INTERNAL_ERROR_PREDICATE: str = (
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
    FFD_ALERT_OK_PREDICATE: str = 'label == "OK" OR name == "OK"'

    FFD_PAGE_WAIT_TIMEOUT: float = 15.0
    FFD_BTN_SETTLE_TIMEOUT: float = 3.0
    FFD_LEAVE_PAGE_TIMEOUT: float = 8.0
    FFD_POST_SKIP_SETTLE_SECONDS: float = 1.5
    FFD_MAX_SKIP_ATTEMPTS: int = 3
    FFD_POLL_INTERVAL: float = 0.4

    def __init__(self, driver: Any, timeout: float = 10.0) -> None:
        if super().__init__ is object.__init__:
            self.driver = driver
            self.timeout = timeout
            self._logger = logging_utils.get_logger(__name__, "familiar_face_page")
        else:
            super().__init__(driver, timeout=timeout)

    @classmethod
    def _ffd_resolve_page(cls, ctx: Any) -> "GHAFamiliarFaceDetectionPage":
        """Resolve a GHAFamiliarFaceDetectionPage instance whether called via page, GHASession, or BaseTestCase."""
        if isinstance(ctx, cls):
            return ctx
        attr_name = cls.__name__.lower()
        existing = getattr(ctx, "__dict__", {}).get(attr_name)
        if isinstance(existing, cls):
            return existing
        session = getattr(ctx, "__dict__", {}).get("session") or getattr(ctx, "_session", None)
        if session is not None:
            sess_page = getattr(session, "__dict__", {}).get(attr_name)
            if isinstance(sess_page, cls):
                return sess_page
        page = cls(ctx.driver)
        if session is not None:
            page.session = session
        return page

    @contextmanager
    def _ffd_no_implicit_wait(self) -> Iterator[None]:
        """Temporarily disable Appium implicit wait so existence checks return immediately."""
        try:
            previous = self.driver.timeouts.implicit_wait
        except Exception:
            previous = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
        try:
            self.driver.implicitly_wait(0)
        except Exception:
            pass
        try:
            yield
        finally:
            try:
                self.driver.implicitly_wait(previous)
            except Exception:
                pass

    @contextmanager
    def _ffd_no_idle_wait(self) -> Iterator[None]:
        """Temporarily disable WDA waitForIdleTimeout so taps are not delayed by animations."""
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

    def _ffd_find_first(
            self, locators: Sequence[Locator], allow_hidden: bool = True
    ) -> Optional[Any]:
        """Find the first matching element across locators (0s implicit wait).

        Prefers `is_displayed() == True`, falling back to present elements with non-zero rect
        when `allow_hidden=True` because XCUITest can report `visible="false"` on GHA GM3 screens.
        """
        if not hasattr(self.driver, "find_elements"):
            return None
        hidden_candidate: Optional[Any] = None
        with self._ffd_no_implicit_wait():
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
                            try:
                                r = elem.rect
                                if isinstance(r, dict) and r.get("width", 0) > 0 and r.get("height",
                                                                                           0) > 0:
                                    hidden_candidate = elem
                                elif r is None:
                                    hidden_candidate = elem
                            except Exception:
                                hidden_candidate = elem
                    except (StaleElementReferenceException, WebDriverException):
                        continue
        return hidden_candidate

    def _ffd_is_on_page(self) -> bool:
        """Return True if 'Familiar face detection' intro screen is currently in the DOM."""
        if self._ffd_find_first(self.FFD_HEADLINE_LOCATORS, allow_hidden=True) is not None:
            return True
        has_select_cameras = (
                self._ffd_find_first(self.FFD_SELECT_CAMERAS_BTN_LOCATORS, allow_hidden=True)
                is not None
        )
        has_skip = (
                self._ffd_find_first(
                    ((IOS_PREDICATE_BY,
                      'type == "XCUIElementTypeButton" AND (label == "Skip" OR name == "Skip")'),),
                    allow_hidden=True,
                )
                is not None
        )
        return has_select_cameras and has_skip

    def _ffd_is_downstream_step_present(self) -> bool:
        """Return True if a subsequent OOBE screen ('Stay in the know' / 'Your camera device is ready') is visible."""
        return self._ffd_find_first(self.FFD_DOWNSTREAM_LOCATORS, allow_hidden=True) is not None

    def _ffd_check_for_internal_error(self) -> None:
        """Check for modal OOBE internal/offline error alerts, dismiss via OK, and raise OOBEInternalErrorException."""
        alert_elem = self._ffd_find_first(
            ((IOS_PREDICATE_BY, self.FFD_INTERNAL_ERROR_PREDICATE),), allow_hidden=False
        )
        if alert_elem is None:
            return
        try:
            alert_text = (
                    alert_elem.get_attribute("label")
                    or alert_elem.get_attribute("name")
                    or "Internal error encountered."
            ).strip()
        except Exception:
            alert_text = "Internal error encountered."
        self._logger.warning(f"[FamiliarFaceDetection] Detected '{alert_text}' alert dialog!")
        if hasattr(BasePage, "capture_failure_screenshot"):
            BasePage.capture_failure_screenshot(
                self.driver,
                reason=f"GHA displayed '{alert_text}' on Familiar face detection page.",
                force=False,
                lock=True,
            )
        with self._ffd_no_idle_wait():
            for _ in range(4):
                ok_btn = self._ffd_find_first(
                    ((IOS_PREDICATE_BY, self.FFD_ALERT_OK_PREDICATE),), allow_hidden=True
                )
                if ok_btn is not None:
                    try:
                        ok_btn.click()
                        self._logger.info(
                            "[FamiliarFaceDetection] Clicked 'OK' on internal error alert.")
                        break
                    except Exception:
                        try:
                            r = ok_btn.rect
                            self.driver.execute_script(
                                "mobile: tap",
                                {"x": int(r["x"] + r["width"] / 2),
                                 "y": int(r["y"] + r["height"] / 2)},
                            )
                            break
                        except Exception:
                            pass
                time.sleep(self.FFD_POLL_INTERVAL)
        raise OOBEInternalErrorException(
            f"GHA displayed '{alert_text}' during Familiar face detection step."
        )

    def _ffd_wait_for_page_or_downstream(self, timeout: float) -> str:
        """Poll until 'Familiar face detection' appears, a downstream OOBE page appears, or timeout expires.

        Returns:
            'present'    -> 'Familiar face detection' page is on screen.
            'downstream' -> A subsequent OOBE screen ('Stay in the know' / 'Your camera device is ready') is already visible.
            'timeout'    -> Neither appeared within `timeout` seconds.
        """
        if not hasattr(self.driver, "find_elements"):
            return "timeout"
        deadline = time.time() + max(0.0, timeout)
        while True:
            self._ffd_check_for_internal_error()
            if self._ffd_is_on_page():
                return "present"
            if self._ffd_is_downstream_step_present():
                return "downstream"
            if time.time() >= deadline:
                return "timeout"
            time.sleep(self.FFD_POLL_INTERVAL)

    def _ffd_fallback_skip_coords(self) -> Tuple[int, int]:
        """Compute bottom-left 'Skip' coordinates from HMEBottomBarView2 layout (left pad 16, bar height 72)."""
        try:
            win = self.driver.get_window_size()
            w = int(win.get("width", 390))
            h = int(win.get("height", 844))
            if w > 0 and h > 0:
                return (max(36, int(round(w * 0.115))), max(100, h - 70))
        except Exception:
            pass
        return (45, 774)

    def _ffd_wait_skip_clickable(self) -> Optional[Any]:
        """Wait briefly for the 'Skip' button to be enabled and its rect to stabilize."""
        deadline = time.time() + self.FFD_BTN_SETTLE_TIMEOUT
        last_rect = None
        btn = None
        while time.time() < deadline:
            self._ffd_check_for_internal_error()
            busy = (
                    self._ffd_find_first(
                        ((IOS_PREDICATE_BY, self.FFD_LOADING_PREDICATE),), allow_hidden=False
                    )
                    is not None
            )
            btn = self._ffd_find_first(self.FFD_SKIP_BTN_LOCATORS, allow_hidden=True)
            if btn is not None and not busy:
                try:
                    rect = btn.rect
                    enabled = True
                    try:
                        enabled = btn.is_enabled()
                    except WebDriverException:
                        pass
                    if enabled and rect == last_rect and isinstance(rect, dict) and rect.get(
                            "width", 0) > 0:
                        return btn
                    last_rect = rect
                except WebDriverException:
                    return btn
            time.sleep(self.FFD_POLL_INTERVAL)
        return btn

    def _ffd_tap_skip(self, btn: Optional[Any], force_coordinates: bool) -> None:
        """Tap 'Skip' via standard click or WDA coordinate tap fallback."""
        with self._ffd_no_idle_wait():
            if btn is None:
                fx, fy = self._ffd_fallback_skip_coords()
                self._logger.info(
                    f"[FamiliarFaceDetection] Tapping 'Skip' at fallback coordinates ({fx}, {fy})..."
                )
                self.driver.execute_script("mobile: tap", {"x": int(fx), "y": int(fy)})
                return

            rect = None
            try:
                rect = btn.rect
            except Exception:
                rect = None

            displayed = False
            try:
                displayed = btn.is_displayed()
            except Exception:
                displayed = False

            if not force_coordinates and displayed:
                try:
                    btn.click()
                    return
                except WebDriverException as err:
                    self._logger.warning(
                        f"[FamiliarFaceDetection] Direct click() on 'Skip' failed ({err}); "
                        "falling back to coordinate tap..."
                    )

            if isinstance(rect, dict) and rect.get("width", 0) > 0 and rect.get("height", 0) > 0:
                cx = int(rect["x"] + rect["width"] / 2)
                cy = int(rect["y"] + rect["height"] / 2)
                self._logger.info(
                    f"[FamiliarFaceDetection] Tapping 'Skip' at coordinates ({cx}, {cy})..."
                )
                self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                return

            try:
                self.driver.execute_script("mobile: tap", {"elementId": btn.id})
                return
            except Exception:
                fx, fy = self._ffd_fallback_skip_coords()
                self._logger.info(
                    f"[FamiliarFaceDetection] Tapping 'Skip' at fallback coordinates ({fx}, {fy})..."
                )
                self.driver.execute_script("mobile: tap", {"x": int(fx), "y": int(fy)})

    def _ffd_wait_until_left_page(self, timeout: float) -> bool:
        """Wait until 'Familiar face detection' leaves the DOM for 2 consecutive polls (or downstream appears)."""
        deadline = time.time() + timeout
        consecutive_gone = 0
        while time.time() < deadline:
            self._ffd_check_for_internal_error()
            if not self._ffd_is_on_page():
                consecutive_gone += 1
                if consecutive_gone >= 2 or self._ffd_is_downstream_step_present():
                    return True
            else:
                consecutive_gone = 0
            time.sleep(self.FFD_POLL_INTERVAL)
        return False

    def handle_familiar_face_detection_if_present(
            self, timeout: Optional[float] = None
    ) -> bool:
        """Check for the 'Familiar face detection' page after 'Adjust your mic settings'; click 'Skip' if shown.

        - If 'Familiar face detection' is displayed: clicks 'Skip', verifies the page closes, and returns True.
        - If 'Familiar face detection' is NOT displayed (downstream page appears or timeout expires):
          logs and returns False immediately without failing so the OOBE flow continues normally.

        Raises:
            OOBEInternalErrorException: If GHA shows an internal/offline modal error alert.
            AssertionError: If 'Familiar face detection' IS displayed on screen, but clicking 'Skip'
                fails to leave the page after all retry attempts.
        """
        page = GHAFamiliarFaceDetectionPage._ffd_resolve_page(self)
        if getattr(page.driver, "_commissioned_via_timeout_online", False):
            page._logger.info(
                "[FamiliarFaceDetection] Skipping check because device is already confirmed ONLINE "
                "on 'All devices' after timeout recovery."
            )
            return True

        wait_timeout = (
            float(timeout)
            if timeout is not None
            else float(
                getattr(
                    constants,
                    "FAMILIAR_FACE_DETECTION_WAIT_TIMEOUT_SECONDS",
                    page.FFD_PAGE_WAIT_TIMEOUT,
                )
            )
        )
        page._logger.info(
            f"[FamiliarFaceDetection] Checking if 'Familiar face detection' page is present "
            f"(up to {wait_timeout:.0f}s)..."
        )
        state = page._ffd_wait_for_page_or_downstream(wait_timeout)
        if state == "downstream":
            page._logger.info(
                "[FamiliarFaceDetection] 'Familiar face detection' not shown "
                "(next OOBE page already visible). Continuing..."
            )
            return False
        if state != "present":
            page._logger.info(
                f"[FamiliarFaceDetection] 'Familiar face detection' page did not appear within "
                f"{wait_timeout:.0f}s. Continuing to next step..."
            )
            return False

        page._logger.info(
            "[FamiliarFaceDetection] Detected 'Familiar face detection' page. Clicking 'Skip'..."
        )
        has_tapped_skip = False
        for attempt in range(1, page.FFD_MAX_SKIP_ATTEMPTS + 1):
            btn = page._ffd_wait_skip_clickable()
            if btn is None and has_tapped_skip and not page._ffd_is_on_page():
                page._logger.info(
                    "[FamiliarFaceDetection] Already left 'Familiar face detection' page."
                )
                return True

            force_coordinates = attempt > 1 or btn is None
            page._logger.info(
                f"[FamiliarFaceDetection] Clicking 'Skip' "
                f"({'coordinate tap' if force_coordinates else 'click'}, "
                f"attempt {attempt}/{page.FFD_MAX_SKIP_ATTEMPTS})..."
            )
            try:
                page._ffd_tap_skip(btn, force_coordinates=force_coordinates)
                has_tapped_skip = True
            except WebDriverException as err:
                page._logger.warning(f"[FamiliarFaceDetection] Tap on 'Skip' failed: {err}")

            if page._ffd_wait_until_left_page(page.FFD_LEAVE_PAGE_TIMEOUT):
                page._logger.info(
                    "[FamiliarFaceDetection] Successfully skipped 'Familiar face detection' page."
                )
                if page.FFD_POST_SKIP_SETTLE_SECONDS > 0:
                    time.sleep(page.FFD_POST_SKIP_SETTLE_SECONDS)
                return True

            page._logger.warning(
                f"[FamiliarFaceDetection] Still on 'Familiar face detection' page after tapping 'Skip' "
                f"(attempt {attempt}/{page.FFD_MAX_SKIP_ATTEMPTS}). Retrying..."
            )

        msg = "[FamiliarFaceDetection] Failed to leave 'Familiar face detection' page after clicking 'Skip'."
        page._logger.error(msg)
        if hasattr(BasePage, "capture_failure_screenshot"):
            BasePage.capture_failure_screenshot(page.driver, reason=msg, force=False, lock=True)
        raise AssertionError(msg)
