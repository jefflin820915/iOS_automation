"""Page object for handling the optional 'Notifications from the <Partner>' OOBE page on iOS.

Appears after 'Adjust your mic settings' (and after 'Familiar face detection' when shown) on Homes
with a 3rd-party subscription partner such as AT&T Connected Life (`DuplicateNotificationsTask` /
`DISABLE_CAMERA_NOTIFICATION_FOR_THIRD_PARTY_DEVICES`).
If present, clicks 'Next' and verifies the page transitions away;
if not present (e.g. GHA moves directly to 'Stay in the know' or 'Your camera device is ready'),
immediately continues to the next OOBE step without failing.

NOTE: Private helpers and constants are prefixed with `_pn_` / `PN_` to avoid MRO / delegation
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


class GHAPartnerNotificationsPage(BasePage):
    """Handles optional 'Notifications from the AT&T Connected Life' (3P partner) OOBE screen."""

    PN_HEADLINE_LOCATORS: Tuple[Locator, ...] = (
        (
            IOS_PREDICATE_BY,
            'type IN {"XCUIElementTypeStaticText", "XCUIElementTypeOther"} AND ('
            'label BEGINSWITH[c] "Notifications from the" '
            'OR name BEGINSWITH[c] "Notifications from the" '
            'OR value BEGINSWITH[c] "Notifications from the" '
            'OR label CONTAINS[c] "AT&T Connected Life" '
            'OR name CONTAINS[c] "AT&T Connected Life")',
        ),
        (
            IOS_PREDICATE_BY,
            'type IN {"XCUIElementTypeStaticText", "XCUIElementTypeTextView"} AND ('
            'label CONTAINS[c] "notifications from the Google Home app" '
            'OR value CONTAINS[c] "notifications from the Google Home app")',
        ),
        (
            AppiumBy.ACCESSIBILITY_ID,
            "DISABLE_CAMERA_NOTIFICATIONS_FOR_THIRD_PARTY_DEVICES_PAGE_HEADER",
        ),
        (
            AppiumBy.XPATH,
            '//XCUIElementTypeStaticText[starts-with(@label, "Notifications from the") '
            'or starts-with(@name, "Notifications from the")]',
        ),
    )

    PN_NEXT_BTN_LOCATORS: Tuple[Locator, ...] = (
        (
            IOS_PREDICATE_BY,
            'type == "XCUIElementTypeButton" AND ('
            'label == "Next" OR name == "Next" OR name == "actionBarPrimaryButton" '
            'OR name == "DISABLE_CAMERA_NOTIFICATIONS_FOR_THIRD_PARTY_DEVICES_PAGE_NEXT_BUTTON")',
        ),
        (AppiumBy.ACCESSIBILITY_ID, getattr(constants, "GHA_NEXT_BTN_ACCESSIBILITY_ID", "Next")),
        (AppiumBy.ACCESSIBILITY_ID, "Next"),
        (AppiumBy.ACCESSIBILITY_ID, "actionBarPrimaryButton"),
        (
            AppiumBy.ACCESSIBILITY_ID,
            "DISABLE_CAMERA_NOTIFICATIONS_FOR_THIRD_PARTY_DEVICES_PAGE_NEXT_BUTTON",
        ),
        (
            AppiumBy.XPATH,
            '//XCUIElementTypeButton[@label="Next" or @name="Next" or @name="actionBarPrimaryButton"]',
        ),
    )

    # Downstream (or sibling) OOBE screens that indicate this page is not currently shown
    PN_DOWNSTREAM_LOCATORS: Tuple[Locator, ...] = (
        (
            IOS_PREDICATE_BY,
            'type == "XCUIElementTypeStaticText" AND ('
            'label == "Familiar face detection" OR name == "Familiar face detection" '
            'OR label CONTAINS[c] "Stay in the know" OR name CONTAINS[c] "Stay in the know" '
            'OR label CONTAINS[c] "Keep up to date" OR name CONTAINS[c] "Keep up to date" '
            'OR label BEGINSWITH "Your camera device is ready" '
            'OR name BEGINSWITH "Your camera device is ready")',
        ),
        (AppiumBy.ACCESSIBILITY_ID, "deviceTileGridCollectionView"),
    )

    PN_LOADING_PREDICATE: str = 'type == "XCUIElementTypeActivityIndicator" AND visible == 1'

    PN_INTERNAL_ERROR_PREDICATE: str = (
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
    PN_ALERT_OK_PREDICATE: str = 'label == "OK" OR name == "OK"'

    PN_PAGE_WAIT_TIMEOUT: float = 15.0
    PN_BTN_SETTLE_TIMEOUT: float = 3.0
    PN_LEAVE_PAGE_TIMEOUT: float = 10.0
    PN_POST_NEXT_SETTLE_SECONDS: float = 1.5
    PN_MAX_NEXT_ATTEMPTS: int = 3
    PN_POLL_INTERVAL: float = 0.4

    def __init__(self, driver: Any, timeout: float = 10.0) -> None:
        if super().__init__ is object.__init__:
            self.driver = driver
            self.timeout = timeout
            self._logger = logging_utils.get_logger(__name__, "partner_notif_page")
        else:
            super().__init__(driver, timeout=timeout)

    @classmethod
    def _pn_resolve_page(cls, ctx: Any) -> "GHAPartnerNotificationsPage":
        """Resolve a GHAPartnerNotificationsPage instance whether called via page, GHASession, or BaseTestCase."""
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
    def _pn_no_implicit_wait(self) -> Iterator[None]:
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
    def _pn_no_idle_wait(self) -> Iterator[None]:
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

    def _pn_find_first(
            self, locators: Sequence[Locator], allow_hidden: bool = True
    ) -> Optional[Any]:
        """Find the first matching element across locators (0s implicit wait)."""
        if not hasattr(self.driver, "find_elements"):
            return None
        hidden_candidate: Optional[Any] = None
        with self._pn_no_implicit_wait():
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

    def _pn_is_on_page(self) -> bool:
        """Return True if 'Notifications from the <Partner>' screen is currently in the DOM."""
        return self._pn_find_first(self.PN_HEADLINE_LOCATORS, allow_hidden=True) is not None

    def _pn_is_downstream_step_present(self) -> bool:
        """Return True if another post-Mic OOBE screen ('Stay in the know' / 'Ready' / 'Familiar face') is visible."""
        return self._pn_find_first(self.PN_DOWNSTREAM_LOCATORS, allow_hidden=True) is not None

    def _pn_check_for_internal_error(self) -> None:
        """Check for modal OOBE internal/offline error alerts, dismiss via OK, and raise OOBEInternalErrorException."""
        alert_elem = self._pn_find_first(
            ((IOS_PREDICATE_BY, self.PN_INTERNAL_ERROR_PREDICATE),), allow_hidden=False
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
        self._logger.warning(f"[PartnerNotifications] Detected '{alert_text}' alert dialog!")
        if hasattr(BasePage, "capture_failure_screenshot"):
            BasePage.capture_failure_screenshot(
                self.driver,
                reason=f"GHA displayed '{alert_text}' on Notifications from partner page.",
                force=False,
                lock=True,
            )
        with self._pn_no_idle_wait():
            for _ in range(4):
                ok_btn = self._pn_find_first(
                    ((IOS_PREDICATE_BY, self.PN_ALERT_OK_PREDICATE),), allow_hidden=True
                )
                if ok_btn is not None:
                    try:
                        ok_btn.click()
                        self._logger.info(
                            "[PartnerNotifications] Clicked 'OK' on internal error alert.")
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
                time.sleep(self.PN_POLL_INTERVAL)
        raise OOBEInternalErrorException(
            f"GHA displayed '{alert_text}' during Notifications from partner step."
        )

    def _pn_wait_for_page_or_downstream(self, timeout: float) -> str:
        """Poll until 'Notifications from the ...' appears, another OOBE page appears, or timeout expires."""
        if not hasattr(self.driver, "find_elements"):
            return "timeout"
        deadline = time.time() + max(0.0, timeout)
        while True:
            self._pn_check_for_internal_error()
            if self._pn_is_on_page():
                return "present"
            if self._pn_is_downstream_step_present():
                return "downstream"
            if time.time() >= deadline:
                return "timeout"
            time.sleep(self.PN_POLL_INTERVAL)

    def _pn_fallback_next_coords(self) -> Tuple[int, int]:
        """Compute bottom-right 'Next' pill coordinates (e.g. ~(332, 776) on 390x844 viewport)."""
        try:
            win = self.driver.get_window_size()
            w = int(win.get("width", 390))
            h = int(win.get("height", 844))
            if w > 0 and h > 0:
                return (max(260, w - 58), max(100, h - 68))
        except Exception:
            pass
        return (332, 776)

    def _pn_wait_next_clickable(self) -> Optional[Any]:
        """Wait briefly for the 'Next' button to be enabled and its rect to stabilize."""
        deadline = time.time() + self.PN_BTN_SETTLE_TIMEOUT
        last_rect = None
        btn = None
        while time.time() < deadline:
            self._pn_check_for_internal_error()
            busy = (
                    self._pn_find_first(
                        ((IOS_PREDICATE_BY, self.PN_LOADING_PREDICATE),), allow_hidden=False
                    )
                    is not None
            )
            btn = self._pn_find_first(self.PN_NEXT_BTN_LOCATORS, allow_hidden=True)
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
            time.sleep(self.PN_POLL_INTERVAL)
        return btn

    def _pn_tap_next(self, btn: Optional[Any], force_coordinates: bool) -> None:
        """Tap 'Next' via standard click or WDA coordinate tap fallback."""
        with self._pn_no_idle_wait():
            if btn is None:
                fx, fy = self._pn_fallback_next_coords()
                self._logger.info(
                    f"[PartnerNotifications] Tapping 'Next' at fallback coordinates ({fx}, {fy})..."
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
                        f"[PartnerNotifications] Direct click() on 'Next' failed ({err}); "
                        "falling back to coordinate tap..."
                    )

            if isinstance(rect, dict) and rect.get("width", 0) > 0 and rect.get("height", 0) > 0:
                cx = int(rect["x"] + rect["width"] / 2)
                cy = int(rect["y"] + rect["height"] / 2)
                self._logger.info(
                    f"[PartnerNotifications] Tapping 'Next' at coordinates ({cx}, {cy})..."
                )
                self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                return

            try:
                self.driver.execute_script("mobile: tap", {"elementId": btn.id})
                return
            except Exception:
                fx, fy = self._pn_fallback_next_coords()
                self._logger.info(
                    f"[PartnerNotifications] Tapping 'Next' at fallback coordinates ({fx}, {fy})..."
                )
                self.driver.execute_script("mobile: tap", {"x": int(fx), "y": int(fy)})

    def _pn_wait_until_left_page(self, timeout: float) -> bool:
        """Wait until 'Notifications from the ...' leaves the DOM for 2 consecutive polls."""
        deadline = time.time() + timeout
        consecutive_gone = 0
        while time.time() < deadline:
            self._pn_check_for_internal_error()
            if not self._pn_is_on_page():
                consecutive_gone += 1
                if consecutive_gone >= 2 or self._pn_is_downstream_step_present():
                    return True
            else:
                consecutive_gone = 0
            time.sleep(self.PN_POLL_INTERVAL)
        return False

    def handle_partner_notifications_if_present(
            self, timeout: Optional[float] = None
    ) -> bool:
        """Check for 'Notifications from the AT&T Connected Life' (3P partner) page; click 'Next' if shown.

        - If displayed: clicks 'Next', waits for `setUserPreferenceWithStructureID` RPC & transition, returns True.
        - If NOT displayed (downstream page appears or timeout expires): logs and returns False without failing.

        Raises:
            OOBEInternalErrorException: If GHA shows an internal/offline modal error alert.
            AssertionError: If the page IS displayed on screen, but clicking 'Next' fails to leave the page.
        """
        page = GHAPartnerNotificationsPage._pn_resolve_page(self)
        if getattr(page.driver, "_commissioned_via_timeout_online", False):
            page._logger.info(
                "[PartnerNotifications] Skipping check because device is already confirmed ONLINE "
                "on 'All devices' after timeout recovery."
            )
            return True

        wait_timeout = (
            float(timeout)
            if timeout is not None
            else float(
                getattr(
                    constants,
                    "PARTNER_NOTIFICATIONS_WAIT_TIMEOUT_SECONDS",
                    page.PN_PAGE_WAIT_TIMEOUT,
                )
            )
        )
        page._logger.info(
            f"[PartnerNotifications] Checking if 'Notifications from the <Partner>' page is present "
            f"(up to {wait_timeout:.0f}s)..."
        )
        state = page._pn_wait_for_page_or_downstream(wait_timeout)
        if state == "downstream":
            page._logger.info(
                "[PartnerNotifications] 'Notifications from the <Partner>' not shown "
                "(next OOBE page already visible). Continuing..."
            )
            return False
        if state != "present":
            page._logger.info(
                f"[PartnerNotifications] 'Notifications from the <Partner>' page did not appear within "
                f"{wait_timeout:.0f}s. Continuing to next step..."
            )
            return False

        page._logger.info(
            "[PartnerNotifications] Detected 'Notifications from the <Partner>' page. Clicking 'Next'..."
        )
        has_tapped_next = False
        for attempt in range(1, page.PN_MAX_NEXT_ATTEMPTS + 1):
            btn = page._pn_wait_next_clickable()
            if btn is None and has_tapped_next and not page._pn_is_on_page():
                page._logger.info(
                    "[PartnerNotifications] Already left 'Notifications from the <Partner>' page."
                )
                return True

            force_coordinates = attempt > 1 or btn is None
            page._logger.info(
                f"[PartnerNotifications] Clicking 'Next' "
                f"({'coordinate tap' if force_coordinates else 'click'}, "
                f"attempt {attempt}/{page.PN_MAX_NEXT_ATTEMPTS})..."
            )
            try:
                page._pn_tap_next(btn, force_coordinates=force_coordinates)
                has_tapped_next = True
            except WebDriverException as err:
                page._logger.warning(f"[PartnerNotifications] Tap on 'Next' failed: {err}")

            if page._pn_wait_until_left_page(page.PN_LEAVE_PAGE_TIMEOUT):
                page._logger.info(
                    "[PartnerNotifications] Successfully proceeded past 'Notifications from the <Partner>' page."
                )
                if page.PN_POST_NEXT_SETTLE_SECONDS > 0:
                    time.sleep(page.PN_POST_NEXT_SETTLE_SECONDS)
                return True

            page._logger.warning(
                f"[PartnerNotifications] Still on 'Notifications from the <Partner>' page after tapping 'Next' "
                f"(attempt {attempt}/{page.PN_MAX_NEXT_ATTEMPTS}). Retrying..."
            )

        msg = (
            "[PartnerNotifications] Failed to leave 'Notifications from the <Partner>' page "
            "after clicking 'Next'."
        )
        page._logger.error(msg)
        if hasattr(BasePage, "capture_failure_screenshot"):
            BasePage.capture_failure_screenshot(page.driver, reason=msg, force=False, lock=True)
        raise AssertionError(msg)
