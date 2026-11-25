"""Page object for handling the 'Stay in the know' OOBE page on iOS.

Handles slow network loading spinners both before and after clicking 'No thanks'
(e.g. dimmed page + blue ActivityIndicator after tapping 'No thanks'), waiting until
the page finishes loading and actually transitions away before proceeding to downstream
OOBE steps ('Familiar face detection', 'Partner notifications', or 'Your camera device is ready').

NOTE: Private helpers and constants are prefixed with `_sik_` / `SIK_` to avoid MRO /
delegation name collisions in `GHASession`.
"""

from contextlib import contextmanager
import time
from typing import Any, Iterator, Optional, Sequence, Tuple

from appium.webdriver.common.appiumby import AppiumBy
from common import constants
from common.base_page import BasePage
from page_object.iGHA.gha_exceptions import OOBEInternalErrorException
from selenium.common.exceptions import WebDriverException
from utils import logging_utils

Locator = Tuple[str, str]
IOS_PREDICATE_BY = getattr(AppiumBy, "IOS_PREDICATE", "-ios predicate string")


class GHAStayInTheKnowPage(BasePage):
    """Handles 'Stay in the know' email opt-in/opt-out screen during iGHA Camera OOBE."""

    SIK_HEADLINE_LOCATORS: Tuple[Locator, ...] = (
        (
            IOS_PREDICATE_BY,
            'type IN {"XCUIElementTypeStaticText", "XCUIElementTypeTextView", "XCUIElementTypeOther"} AND ('
            'label CONTAINS[c] "Stay in the know" OR name CONTAINS[c] "Stay in the know" '
            'OR value CONTAINS[c] "Stay in the know" '
            'OR label CONTAINS[c] "Keep up to date" OR name CONTAINS[c] "Keep up to date" '
            'OR label CONTAINS[c] "Stay up to date on Google Home" '
            'OR value CONTAINS[c] "Stay up to date on Google Home")',
        ),
        (
            AppiumBy.XPATH,
            '//XCUIElementTypeStaticText[contains(@label, "Stay in the know") '
            'or contains(@name, "Stay in the know") or contains(@label, "Stay up to date on Google Home")]',
        ),
    )

    SIK_NO_THANKS_BTN_LOCATORS: Tuple[Locator, ...] = (
        (
            IOS_PREDICATE_BY,
            'type == "XCUIElementTypeButton" AND ('
            'label == "No thanks" OR name == "No thanks" '
            'OR label CONTAINS[c] "No thanks" OR name CONTAINS[c] "No thanks" '
            'OR name == "actionBarSecondaryButton")',
        ),
        (AppiumBy.ACCESSIBILITY_ID, "No thanks"),
        (AppiumBy.ACCESSIBILITY_ID, "actionBarSecondaryButton"),
        (
            AppiumBy.XPATH,
            '//XCUIElementTypeButton[@label="No thanks" or @name="No thanks" '
            'or @name="actionBarSecondaryButton"]',
        ),
    )

    SIK_DOWNSTREAM_LOCATORS: Tuple[Locator, ...] = (
        (
            IOS_PREDICATE_BY,
            'type IN {"XCUIElementTypeStaticText", "XCUIElementTypeTextView"} AND ('
            'label BEGINSWITH "Your camera device is ready" OR name BEGINSWITH "Your camera device is ready" '
            'OR label == "Familiar face detection" OR name == "Familiar face detection" '
            'OR label BEGINSWITH[c] "Notifications from the" OR name BEGINSWITH[c] "Notifications from the")',
        ),
        (AppiumBy.ACCESSIBILITY_ID, "deviceTileGridCollectionView"),
    )

    SIK_LOADING_PREDICATE: str = 'type == "XCUIElementTypeActivityIndicator" AND visible == 1'

    SIK_INTERNAL_ERROR_PREDICATE: str = (
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
    SIK_ALERT_OK_PREDICATE: str = 'label == "OK" OR name == "OK"'

    SIK_PAGE_WAIT_TIMEOUT: float = 15.0
    SIK_IDLE_TIMEOUT: float = 25.0
    SIK_IDLE_STABLE_SECONDS: float = 0.8
    SIK_LEAVE_PAGE_TIMEOUT: float = 30.0
    SIK_MAX_ATTEMPTS: int = 3
    SIK_POLL_INTERVAL: float = 0.5

    def __init__(self, driver: Any, timeout: float = 10.0) -> None:
        if super().__init__ is object.__init__:
            self.driver = driver
            self.timeout = timeout
            self._logger = logging_utils.get_logger(__name__, "stay_in_the_know_page")
        else:
            super().__init__(driver, timeout=timeout)

    @classmethod
    def _sik_resolve_page(cls, ctx: Any) -> "GHAStayInTheKnowPage":
        """Resolve a GHAStayInTheKnowPage instance whether called via page, GHASession, or BaseTestCase."""
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
            setattr(session, attr_name, page)
        if ctx is not session:
            setattr(ctx, attr_name, page)
        return page

    @contextmanager
    def _sik_no_implicit_wait(self) -> Iterator[None]:
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
    def _sik_no_idle_wait(self) -> Iterator[None]:
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

    def _sik_find_first(self, locators: Sequence[Locator], allow_hidden: bool = True) -> Optional[
        Any]:
        hidden = None
        with self._sik_no_implicit_wait():
            for by, val in locators:
                try:
                    elems = self.driver.find_elements(by, val)
                except WebDriverException:
                    continue
                for el in elems:
                    try:
                        if el.is_displayed():
                            return el
                        if allow_hidden and hidden is None:
                            hidden = el
                    except WebDriverException:
                        continue
        return hidden

    def _sik_is_on_page(self) -> bool:
        return self._sik_find_first(self.SIK_HEADLINE_LOCATORS, allow_hidden=True) is not None

    def _sik_is_downstream_visible(self) -> bool:
        return self._sik_find_first(self.SIK_DOWNSTREAM_LOCATORS, allow_hidden=False) is not None

    def _sik_is_loading_spinner_visible(self) -> bool:
        with self._sik_no_implicit_wait():
            try:
                spinners = self.driver.find_elements(IOS_PREDICATE_BY, self.SIK_LOADING_PREDICATE)
                return any(s.is_displayed() for s in spinners)
            except WebDriverException:
                return False

    def _sik_get_no_thanks_btn(self) -> Optional[Any]:
        return self._sik_find_first(self.SIK_NO_THANKS_BTN_LOCATORS, allow_hidden=True)

    @staticmethod
    def _sik_is_elem_enabled(elem: Any) -> bool:
        if elem is None:
            return False
        try:
            if hasattr(elem, "is_enabled") and not elem.is_enabled():
                return False
            attr = elem.get_attribute("enabled") if hasattr(elem, "get_attribute") else None
            if attr is not None and str(attr).strip().lower() == "false":
                return False
            return True
        except WebDriverException:
            return False

    def _sik_check_for_internal_error(self) -> None:
        with self._sik_no_implicit_wait():
            try:
                alerts = self.driver.find_elements(IOS_PREDICATE_BY,
                                                   self.SIK_INTERNAL_ERROR_PREDICATE)
            except WebDriverException:
                alerts = []
        if not alerts:
            return
        alert_elem = alerts[0]
        alert_text = "Internal error encountered."
        for attr in ("label", "name", "value"):
            try:
                v = alert_elem.get_attribute(attr)
                if v and str(v).strip():
                    alert_text = str(v).strip()
                    break
            except WebDriverException:
                continue
        self._logger.warning(f"[StayInTheKnow] Detected '{alert_text}' alert dialog!")
        if hasattr(BasePage, "capture_failure_screenshot"):
            BasePage.capture_failure_screenshot(
                self.driver,
                reason=f"GHA displayed '{alert_text}' during Stay in the know.",
                force=False,
                lock=True,
            )
        ok_btn = self._sik_find_first([(IOS_PREDICATE_BY, self.SIK_ALERT_OK_PREDICATE)],
                                      allow_hidden=True)
        if ok_btn is not None:
            with self._sik_no_idle_wait():
                try:
                    ok_btn.click()
                except WebDriverException:
                    try:
                        r = ok_btn.rect
                        self.driver.execute_script(
                            "mobile: tap",
                            {"x": int(r["x"] + r["width"] / 2), "y": int(r["y"] + r["height"] / 2)},
                        )
                    except WebDriverException:
                        pass
        raise OOBEInternalErrorException(f"GHA displayed '{alert_text}' during Stay in the know.")

    def _sik_wait_until_idle(self, timeout: float = SIK_IDLE_TIMEOUT) -> str:
        """Wait until any initial loading spinner finishes and 'No thanks' is enabled & stable."""
        deadline = time.time() + timeout
        idle_since: Optional[float] = None
        logged_spinner = False
        while time.time() < deadline:
            self._sik_check_for_internal_error()
            if self._sik_is_downstream_visible() or not self._sik_is_on_page():
                return "left"
            if self._sik_is_loading_spinner_visible():
                if not logged_spinner:
                    self._logger.info(
                        "[StayInTheKnow] Loading spinner visible on 'Stay in the know'; waiting before clicking 'No thanks'..."
                    )
                    logged_spinner = True
                idle_since = None
            else:
                btn = self._sik_get_no_thanks_btn()
                if self._sik_is_elem_enabled(btn):
                    idle_since = idle_since or time.time()
                    if (time.time() - idle_since) >= self.SIK_IDLE_STABLE_SECONDS:
                        return "ready"
                else:
                    idle_since = None
            time.sleep(self.SIK_POLL_INTERVAL)
        return "timeout"

    def _sik_tap_no_thanks(self, btn: Any, force_coordinates: bool = False) -> None:
        with self._sik_no_idle_wait():
            if not force_coordinates:
                try:
                    if getattr(btn, "is_displayed", lambda: True)():
                        btn.click()
                        return
                except WebDriverException:
                    pass
            try:
                rect = btn.rect
                cx = int(rect["x"] + rect["width"] / 2)
                cy = int(rect["y"] + rect["height"] / 2)
                self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                return
            except WebDriverException:
                pass
            btn.click()

    def _sik_wait_until_left_page(self, timeout: float = SIK_LEAVE_PAGE_TIMEOUT) -> str:
        """Wait after tapping 'No thanks' for network spinner to finish and transition away.

        Returns:
            'left' if the page transitioned away (or downstream screen appeared),
            'idle_still_on_page' if the spinner stopped and 'No thanks' is enabled again (tap swallowed),
            'timeout' if still spinning/loading past `timeout`.
        """
        deadline = time.time() + timeout
        consecutive_gone = 0
        idle_still_on_page_since: Optional[float] = None
        logged_post_tap_spinner = False

        while time.time() < deadline:
            self._sik_check_for_internal_error()
            on_page = self._sik_is_on_page()
            spinner = self._sik_is_loading_spinner_visible()

            if self._sik_is_downstream_visible():
                return "left"

            if not on_page and not spinner:
                consecutive_gone += 1
                if consecutive_gone >= 2:
                    return "left"
                idle_still_on_page_since = None
            else:
                consecutive_gone = 0
                if spinner:
                    if not logged_post_tap_spinner:
                        self._logger.info(
                            "[StayInTheKnow] 'Stay in the know' is loading after clicking 'No thanks'; waiting for completion..."
                        )
                        logged_post_tap_spinner = True
                    idle_still_on_page_since = None
                elif on_page:
                    btn = self._sik_get_no_thanks_btn()
                    if self._sik_is_elem_enabled(btn):
                        idle_still_on_page_since = idle_still_on_page_since or time.time()
                        if (time.time() - idle_still_on_page_since) >= 2.0:
                            return "idle_still_on_page"
                    else:
                        idle_still_on_page_since = None
            time.sleep(self.SIK_POLL_INTERVAL)

        return "timeout"

    def handle_stay_in_the_know_page_process(self, timeout: Optional[float] = None) -> bool:
        """Wait for 'Stay in the know' (if shown), click 'No thanks' once idle, and wait until it finishes loading and leaves."""
        page = GHAStayInTheKnowPage._sik_resolve_page(self)
        wait_timeout = page.SIK_PAGE_WAIT_TIMEOUT if timeout is None else float(timeout)
        page._logger.info(
            f"[StayInTheKnow] Checking if 'Stay in the know' page is present (up to {wait_timeout:.0f}s)..."
        )
        deadline = time.time() + wait_timeout
        present = False
        while time.time() < deadline:
            page._sik_check_for_internal_error()
            if page._sik_is_on_page():
                present = True
                break
            if page._sik_is_downstream_visible():
                page._logger.info(
                    "[StayInTheKnow] 'Stay in the know' not shown (next OOBE page already visible). Continuing..."
                )
                return False
            time.sleep(page.SIK_POLL_INTERVAL)

        if not present:
            page._logger.info(
                "[StayInTheKnow] 'Stay in the know' page did not appear. Continuing...")
            return False

        for attempt in range(1, page.SIK_MAX_ATTEMPTS + 1):
            idle_state = page._sik_wait_until_idle(timeout=page.SIK_IDLE_TIMEOUT)
            if idle_state == "left":
                page._logger.info("[StayInTheKnow] Left 'Stay in the know' page.")
                return True

            btn = page._sik_get_no_thanks_btn()
            if btn is None:
                if not page._sik_is_on_page():
                    return True
                time.sleep(page.SIK_POLL_INTERVAL)
                continue

            force_coords = attempt > 1
            page._logger.info(
                f"Clicking 'No thanks' button ({'coordinate tap' if force_coords else 'click'}, "
                f"attempt {attempt}/{page.SIK_MAX_ATTEMPTS})..."
            )
            page._sik_tap_no_thanks(btn, force_coordinates=force_coords)

            leave_state = page._sik_wait_until_left_page(timeout=page.SIK_LEAVE_PAGE_TIMEOUT)
            if leave_state == "left":
                page._logger.info("[StayInTheKnow] Successfully left 'Stay in the know' page.")
                return True
            if leave_state == "idle_still_on_page":
                page._logger.warning(
                    f"[StayInTheKnow] [Attempt {attempt}/{page.SIK_MAX_ATTEMPTS}] Still on 'Stay in the know' "
                    "after clicking 'No thanks' (tap likely swallowed). Retrying..."
                )
            else:
                page._logger.warning(
                    f"[StayInTheKnow] Timed out waiting for 'Stay in the know' loading after attempt {attempt}."
                )

        if not page._sik_is_on_page() or page._sik_is_downstream_visible():
            return True
        page._logger.warning("[StayInTheKnow] Proceeding after max 'No thanks' attempts.")
        return False
