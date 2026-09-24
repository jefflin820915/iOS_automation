"""Page object for handling GHA Single Device Found page on iOS."""
import re
import time
from contextlib import contextmanager
from typing import Iterator, List, Optional, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException
from common import constants
from common.base_page import BasePage

Locator = Tuple[str, str]


class GHASingleDeviceFoundPage(BasePage):
    """Handles the 'Single Device Found' screen during GHA setup.
    Single page: directly shows a 'Next' button for one detected device.
    Multi-device list: shows multiple device cards and NO 'Next' button.
    Both pages share the 'Set up a different device' button, so it is not a unique marker.
    """
    NEXT_BTN_LOCATORS: List[Locator] = [
        (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "Footer_actionBar" AND label == "Next"`]'),
        (AppiumBy.ACCESSIBILITY_ID, "Next"),
    ]
    DIFFERENT_DEVICE_BTN_LOCATORS: List[Locator] = [
        (AppiumBy.IOS_CLASS_CHAIN,
         '**/XCUIElementTypeButton[`name == "Footer_actionBar" AND label == "Set up a different device"`]'),
        (AppiumBy.ACCESSIBILITY_ID, "Set up a different device"),
    ]
    BACK_BTN_LOCATORS: List[Locator] = [
        (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "closeButton"`]'),
        (AppiumBy.IOS_PREDICATE,
         'type == "XCUIElementTypeButton" AND '
         '(name IN {"closeButton", "close", "Close", "Back", "back"} OR label IN {"Back", "Close"})'),
    ]
    HEADER_TITLE: Locator = (AppiumBy.ACCESSIBILITY_ID, "Header_title")
    HEADER_SUBTITLE: Locator = (AppiumBy.ACCESSIBILITY_ID, "Header_subtitle")
    NAV_BAR: Locator = (
        AppiumBy.IOS_CLASS_CHAIN,
        '**/XCUIElementTypeNavigationBar[`name CONTAINS "SingleDeviceFoundView"`]',
    )
    # Device ID label on each nearby device card, e.g. "4738:21505:2329"
    DEVICE_ID_TEXT: Locator = (
        AppiumBy.IOS_PREDICATE,
        'type == "XCUIElementTypeStaticText" AND label MATCHES "^[0-9]+:[0-9]+:[0-9]+$"',
    )
    TITLE_PREFIX_PATTERN = re.compile(r"^(set up|add)\s+", re.IGNORECASE)
    SDF_POLL_INTERVAL = 0.3
    SDF_LEAVE_PAGE_TIMEOUT = 8.0

    @contextmanager
    def _sdf_no_implicit_wait(self) -> Iterator[None]:
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

    def _sdf_find_displayed(self, by: str, value: str) -> Optional[WebElement]:
        """Return the first displayed element immediately, or None."""
        with self._sdf_no_implicit_wait():
            try:
                for elem in self.driver.find_elements(by, value):
                    if elem.is_displayed():
                        return elem
            except WebDriverException:
                pass
        return None

    def _sdf_find_first(self, locators: List[Locator]) -> Optional[WebElement]:
        for by, value in locators:
            elem = self._sdf_find_displayed(by, value)
            if elem is not None:
                return elem
        return None

    def _sdf_wait_gone(self, locators: List[Locator], timeout: float) -> bool:
        """Poll until none of the locators match a displayed element."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._sdf_find_first(locators) is None:
                return True
            time.sleep(self.SDF_POLL_INTERVAL)
        return False

    def _sdf_tap_center(self, element: WebElement) -> None:
        rect = element.rect
        self.driver.execute_script("mobile: tap", {
            "x": int(rect["x"] + rect["width"] / 2),
            "y": int(rect["y"] + rect["height"] / 2),
        })

    def _sdf_click(self, element: WebElement) -> bool:
        """Click the element, falling back to a coordinate tap."""
        try:
            element.click()
            return True
        except WebDriverException:
            pass
        try:
            self._sdf_tap_center(element)
            return True
        except WebDriverException:
            return False

    def _sdf_count_device_cards(self) -> int:
        """Count nearby device cards by their 'VID:PID:discriminator' labels."""
        with self._sdf_no_implicit_wait():
            try:
                return len(self.driver.find_elements(*self.DEVICE_ID_TEXT))
            except WebDriverException:
                return 0

    def _sdf_has_nearby_subtitle(self) -> bool:
        sub_elem = self._sdf_find_displayed(*self.HEADER_SUBTITLE)
        if sub_elem is None:
            return False
        try:
            sub_text = sub_elem.get_attribute("label") or sub_elem.text or ""
        except WebDriverException:
            return False
        return "detected nearby" in sub_text.lower()

    def is_single_device_found_page(self, timeout: float = 2.0) -> bool:
        """Strictly determine if the current screen is the 'Single Device Found' page.
        Rules:
        - Must have a visible 'Next' button (multi-device list has none).
        - 2+ device cards on screen -> multi-device list -> always False.
        - Needs a single-page marker: SingleDeviceFoundView nav bar, 'detected nearby' subtitle,
          or 'Set up a different device' together with at most one device card.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self._sdf_find_first(self.NEXT_BTN_LOCATORS) is None:
                    time.sleep(self.SDF_POLL_INTERVAL)
                    continue
                card_count = self._sdf_count_device_cards()
                if card_count >= 2:
                    self._logger.info(f"[SingleDevice] Detected {card_count} device cards -> multi-device list.")
                    return False
                has_navbar = self._sdf_find_displayed(*self.NAV_BAR) is not None
                has_subtitle = self._sdf_has_nearby_subtitle()
                has_diff_btn = self._sdf_find_first(self.DIFFERENT_DEVICE_BTN_LOCATORS) is not None
                if has_navbar or has_subtitle or (has_diff_btn and card_count <= 1):
                    self._logger.info(
                        f"[SingleDevice] Confirmed 'Single Device Found' page "
                        f"(navbar={has_navbar}, subtitle={has_subtitle}, "
                        f"diff_btn={has_diff_btn}, cards={card_count})."
                    )
                    return True
            except WebDriverException:
                pass
            time.sleep(self.SDF_POLL_INTERVAL)
        return False

    def get_detected_device_title(self) -> str:
        """Extract the header title (e.g. 'Set up Ref2 Battery Camera')."""
        elem = self._sdf_find_displayed(*self.HEADER_TITLE)
        if elem is None:
            return ""
        try:
            return (elem.get_attribute("label") or elem.get_attribute("value") or elem.text or "").strip()
        except WebDriverException:
            return ""

    def is_title_match_device(self, target_device_name: str) -> bool:
        """Check whether the header title refers to the target device (case-insensitive)."""
        detected_title = self.get_detected_device_title()
        detected_name = self.TITLE_PREFIX_PATTERN.sub("", detected_title).strip()
        matched = not target_device_name or target_device_name.lower() in detected_name.lower()
        self._logger.info(
            f"[SingleDevice] Title: '{detected_title}' | Expected: '{target_device_name}' | Match: {matched}"
        )
        return matched

    def click_next_button(self) -> bool:
        """Click 'Next' and verify the page transitioned (Next button disappears)."""
        for use_coordinates in (False, True):
            next_btn = self._sdf_find_first(self.NEXT_BTN_LOCATORS)
            if next_btn is None:
                self._logger.error("[SingleDevice] 'Next' button not found.")
                return False
            try:
                if use_coordinates:
                    self._logger.warning("[SingleDevice] Still on page. Retrying 'Next' with coordinate tap...")
                    self._sdf_tap_center(next_btn)
                else:
                    self._logger.info("[SingleDevice] Clicking 'Next'...")
                    next_btn.click()
            except WebDriverException as err:
                self._logger.warning(f"[SingleDevice] Tap on 'Next' failed: {err}")
                continue
            if self._sdf_wait_gone(self.NEXT_BTN_LOCATORS[:1], timeout=self.SDF_LEAVE_PAGE_TIMEOUT):
                self._logger.info("[SingleDevice] Successfully proceeded from Single Device Found page.")
                return True
        self._logger.error("[SingleDevice] Failed to leave Single Device Found page.")
        return False

    def click_different_device_button(self) -> bool:
        """Click 'Set up a different device' when the detected device is not the target."""
        diff_btn = self._sdf_find_first(self.DIFFERENT_DEVICE_BTN_LOCATORS)
        if diff_btn is None:
            self._logger.warning("[SingleDevice] 'Set up a different device' button not found.")
            return False
        if not self._sdf_click(diff_btn):
            return False
        time.sleep(2.0)
        self._logger.info("[SingleDevice] Clicked 'Set up a different device'.")
        return True

    def click_back_btn(self) -> bool:
        """Click the top-left back/close button (reveals hidden controls if needed)."""
        self._logger.info("[SingleDevice] Looking for back/close button...")
        btn = self._sdf_find_first(self.BACK_BTN_LOCATORS)
        if btn is None:
            self._logger.info("[SingleDevice] Controls may be hidden. Tapping screen to reveal...")
            try:
                self.driver.execute_script("mobile: tap", {"x": 200, "y": 300})
                time.sleep(1.0)
            except WebDriverException:
                pass
            btn = self._sdf_find_first(self.BACK_BTN_LOCATORS)
        if btn is not None and self._sdf_click(btn):
            time.sleep(1.5)
            self._logger.info("[SingleDevice] Clicked back button.")
            return True
        self._logger.warning("[SingleDevice] Fallback: tapping top-left corner...")
        try:
            self.driver.execute_script("mobile: tap", {"x": 25, "y": 55})
            time.sleep(1.5)
            return True
        except WebDriverException as e:
            self._logger.error(f"[SingleDevice] Failed to click back: {e}")
            return False

    @classmethod
    def handle_if_present(cls, session_or_page, target_device_name: str, timeout: float = 2.5) -> bool:
        """Handle the Single Device Found screen if present.
        Returns:
            True  -> Single page matched target and 'Next' was clicked successfully.
            False -> Not a single page (multi-device list), or detected device mismatched
                     and the flow was reset back to the device list.
        """
        # Local imports to avoid circular import with gha_session
        from page_object.iGHA.gha_add_page import GHAAddPage
        from page_object.iGHA.gha_home_page import GHAHomePage
        driver = getattr(session_or_page, "driver", session_or_page)
        page = cls(driver)
        if not page.is_single_device_found_page(timeout=timeout):
            page._logger.info("[SingleDevice] Not a Single Device screen. Proceeding with list flow...")
            return False
        if page.is_title_match_device(target_device_name):
            return page.click_next_button()
        page._logger.warning(
            f"[SingleDevice] Detected device does NOT match '{target_device_name}'. "
            f"Switching to a different device..."
        )
        page.click_different_device_button()
        page.click_back_btn()
        GHAHomePage(driver).click_add_devices_button()
        GHAAddPage(driver).navigate_to_setup_device_page()
        return False