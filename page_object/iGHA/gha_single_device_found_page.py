"""Page object for handling GHA Single Device Found page on iOS."""
import re
import time
from contextlib import contextmanager
from typing import Iterator, List, Optional, Tuple
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
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
        (AppiumBy.IOS_PREDICATE, 'type == "XCUIElementTypeButton" AND (label == "Next" OR name == "Next")'),
        (AppiumBy.ACCESSIBILITY_ID, "Next"),
    ]
    DIFFERENT_DEVICE_BTN_LOCATORS: List[Locator] = [
        (
            AppiumBy.IOS_CLASS_CHAIN,
            '**/XCUIElementTypeButton[`name == "Footer_actionBar" AND label == "Set up a different device"`]',
        ),
        (
            AppiumBy.IOS_PREDICATE,
            'type == "XCUIElementTypeButton" AND '
            '(label CONTAINS[c] "Set up a different device" OR name CONTAINS[c] "Set up a different device")',
        ),
        (AppiumBy.ACCESSIBILITY_ID, "Set up a different device"),
    ]
    CLOSE_BTN_LOCATORS: List[Locator] = [
        (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "closeButton"`]'),
        (
            AppiumBy.IOS_PREDICATE,
            'type == "XCUIElementTypeButton" AND '
            '(name IN {"closeButton", "close", "Close"} OR label IN {"Close", "close"})',
        ),
        (AppiumBy.ACCESSIBILITY_ID, "closeButton"),
        (AppiumBy.ACCESSIBILITY_ID, "Close"),
    ]
    BACK_BTN_LOCATORS: List[Locator] = [
        *CLOSE_BTN_LOCATORS,
        (
            AppiumBy.IOS_PREDICATE,
            'type == "XCUIElementTypeButton" AND '
            '(name IN {"closeButton", "close", "Close", "Back", "back"} OR label IN {"Close", "Back"})',
        ),
        (AppiumBy.ACCESSIBILITY_ID, "Back"),
    ]
    HOME_READY_LOCATORS: List[Locator] = [
        (
            AppiumBy.ACCESSIBILITY_ID,
            getattr(constants, "GHA_ADD_DEVICES_BTN_ACCESSIBILITY_ID", "Add"),
        ),
        (AppiumBy.ACCESSIBILITY_ID, "homeViewTabBarAccessibilityID"),
        (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeTabBar'),
    ]
    HEADER_ROOT: Locator = (AppiumBy.ACCESSIBILITY_ID, "Header_rootView")
    HEADER_TITLE: Locator = (AppiumBy.ACCESSIBILITY_ID, "Header_title")
    HEADER_SUBTITLE: Locator = (AppiumBy.ACCESSIBILITY_ID, "Header_subtitle")
    HEADER_FALLBACK_PREDICATE: Locator = (
        AppiumBy.IOS_PREDICATE,
        'type == "XCUIElementTypeStaticText" AND '
        '(label BEGINSWITH[c] "Set up " OR value BEGINSWITH[c] "Set up " '
        'OR label BEGINSWITH[c] "Add " OR value BEGINSWITH[c] "Add ")',
    )
    NAV_BAR: Locator = (
        AppiumBy.IOS_CLASS_CHAIN,
        '**/XCUIElementTypeNavigationBar[`name CONTAINS "SingleDeviceFoundView"`]',
    )
    # Device ID label on each nearby device card, e.g. "4738:21505:2329"
    DEVICE_ID_TEXT: Locator = (
        AppiumBy.IOS_PREDICATE,
        'type == "XCUIElementTypeStaticText" AND label MATCHES "^[0-9]+:[0-9]+:[0-9]+$"',
    )
    MULTI_DEVICE_CARD_BTN: Locator = (
        AppiumBy.IOS_PREDICATE,
        'type == "XCUIElementTypeButton" AND name == "image-title-subtitle" AND visible == 1',
    )
    TITLE_PREFIX_PATTERN = re.compile(r"^(set up|add)\s+", re.IGNORECASE)
    IGNORED_TITLES = {
        "set up a different device",
        "set up nearby devices",
        "set up device",
        "add device",
        "add devices",
    }
    SDF_POLL_INTERVAL = 0.3
    SDF_DISCOVERY_TIMEOUT = 10.0
    SDF_TITLE_WAIT_TIMEOUT = 3.0
    SDF_LEAVE_PAGE_TIMEOUT = 8.0
    SDF_MAX_BACK_STEPS = 3

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
                    try:
                        if elem.is_displayed():
                            return elem
                    except (WebDriverException, StaleElementReferenceException):
                        continue
            except WebDriverException:
                pass
        return None

    def _sdf_find_any(self, by: str, value: str) -> Optional[WebElement]:
        """Return the first displayed element, or the first present DOM element if XCUITest marks children hidden."""
        with self._sdf_no_implicit_wait():
            try:
                elems = self.driver.find_elements(by, value)
                first_elem: Optional[WebElement] = None
                for elem in elems:
                    if first_elem is None:
                        first_elem = elem
                    try:
                        if elem.is_displayed():
                            return elem
                    except (WebDriverException, StaleElementReferenceException):
                        continue
                return first_elem
            except WebDriverException:
                pass
        return None

    def _sdf_find_first(self, locators: List[Locator], allow_hidden: bool = False) -> Optional[WebElement]:
        for by, value in locators:
            elem = self._sdf_find_any(by, value) if allow_hidden else self._sdf_find_displayed(by, value)
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
        self.driver.execute_script(
            "mobile: tap",
            {
                "x": int(rect["x"] + rect["width"] / 2),
                "y": int(rect["y"] + rect["height"] / 2),
            },
        )

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

    def _sdf_read_text(self, elem: Optional[WebElement]) -> str:
        """Safely read label/value/text from an element."""
        if elem is None:
            return ""
        for attr in ("label", "value", "text"):
            try:
                val = elem.get_attribute(attr) if attr != "text" else elem.text
                if val and str(val).strip():
                    return str(val).strip()
            except (WebDriverException, StaleElementReferenceException):
                continue
        return ""

    def _sdf_count_device_cards(self) -> int:
        """Count nearby device cards by their 'VID:PID:discriminator' labels or card buttons."""
        with self._sdf_no_implicit_wait():
            id_count = 0
            btn_count = 0
            try:
                id_count = len(self.driver.find_elements(*self.DEVICE_ID_TEXT))
            except WebDriverException:
                pass
            try:
                btn_count = len(self.driver.find_elements(*self.MULTI_DEVICE_CARD_BTN))
            except WebDriverException:
                pass
            return max(id_count, btn_count)

    def _sdf_has_nearby_subtitle(self) -> bool:
        """Check if 'This device was detected nearby' is present in Header_subtitle or Header_rootView."""
        for locator in (self.HEADER_SUBTITLE, self.HEADER_ROOT):
            sub_elem = self._sdf_find_any(*locator)
            sub_text = self._sdf_read_text(sub_elem).lower()
            if "this device was detected nearby" in sub_text:
                return True
        return False

    def _sdf_is_nearby_list_header(self) -> bool:
        """Return True if the multi-device 'Set up nearby devices' header is present."""
        for locator in (self.HEADER_TITLE, self.HEADER_SUBTITLE, self.HEADER_ROOT):
            elem = self._sdf_find_any(*locator)
            text = self._sdf_read_text(elem).lower()
            if "set up nearby devices" in text or "devices were detected nearby" in text:
                return True
        return False

    def is_single_device_found_page(self, timeout: float = 10.0) -> bool:
        """Strictly determine if the current screen is the 'Single Device Found' page.
        Polls through the 'Looking for devices...' scanning transition so it does not
        return False prematurely before SingleDeviceFoundView finishes loading.
        Rules:
        - 2+ device cards on screen -> multi-device list -> immediately False.
        - SingleDeviceFoundView nav bar or 'detected nearby' subtitle -> True (waits briefly for Next button).
        - Visible 'Next' button + 'Set up a different device' button with <= 1 card -> True.
        """
        effective_timeout = max(float(timeout or 0.0), self.SDF_DISCOVERY_TIMEOUT)
        deadline = time.time() + effective_timeout
        while time.time() < deadline:
            try:
                card_count = self._sdf_count_device_cards()
                if card_count >= 2 or self._sdf_is_nearby_list_header():
                    self._logger.info(
                        f"[SingleDevice] Detected multi-device 'Set up nearby devices' list (cards={card_count})."
                    )
                    return False
                has_navbar = self._sdf_find_any(*self.NAV_BAR) is not None
                has_subtitle = self._sdf_has_nearby_subtitle()
                has_next = self._sdf_find_first(self.NEXT_BTN_LOCATORS, allow_hidden=True) is not None
                has_diff_btn = self._sdf_find_first(self.DIFFERENT_DEVICE_BTN_LOCATORS, allow_hidden=True) is not None
                if has_navbar or has_subtitle or (has_next and has_diff_btn and card_count <= 1):
                    self._logger.info(
                        f"[SingleDevice] Confirmed 'Single Device Found' page "
                        f"(navbar={has_navbar}, subtitle={has_subtitle}, "
                        f"next={has_next}, diff_btn={has_diff_btn}, cards={card_count})."
                    )
                    return True
                # If 1 multi-device card button is visible and there is no SingleDevice marker or Next button,
                # check if 'Set up nearby devices' / multi-device list is already displayed.
                if card_count == 1 and not has_next and not has_navbar and not has_subtitle:
                    with self._sdf_no_implicit_wait():
                        try:
                            if self.driver.find_elements(*self.MULTI_DEVICE_CARD_BTN):
                                self._logger.info(
                                    "[SingleDevice] Detected nearby device list card without SingleDevice markers."
                                )
                                return False
                        except WebDriverException:
                            pass
            except WebDriverException:
                pass
            time.sleep(self.SDF_POLL_INTERVAL)
        return False
    def _sdf_extract_title_once(self) -> str:
        """Single non-blocking attempt to read the detected device title from Header_title / Header_rootView."""
        # 1. Direct Header_title (may have visible==false inside accessible Header_rootView)
        title_elem = self._sdf_find_any(*self.HEADER_TITLE)
        raw_title = self._sdf_read_text(title_elem)
        if raw_title:
            return raw_title
        # 2. Parent Header_rootView (e.g. "Set up Ref2 Battery Camera, This device was detected nearby")
        root_elem = self._sdf_find_any(*self.HEADER_ROOT)
        root_text = self._sdf_read_text(root_elem)
        if root_text:
            parts = re.split(r",\s*this device|\n", root_text, maxsplit=1, flags=re.IGNORECASE)
            candidate = parts[0].strip().rstrip(",")
            if candidate:
                return candidate
        # 3. Any StaticText starting with "Set up " or "Add "
        with self._sdf_no_implicit_wait():
            try:
                for elem in self.driver.find_elements(*self.HEADER_FALLBACK_PREDICATE):
                    text = self._sdf_read_text(elem)
                    if not text:
                        continue
                    parts = re.split(r",\s*this device|\n", text, maxsplit=1, flags=re.IGNORECASE)
                    candidate = parts[0].strip().rstrip(",")
                    if candidate and candidate.lower() not in self.IGNORED_TITLES:
                        return candidate
            except WebDriverException:
                pass
        return ""

    def get_detected_device_title(self, timeout: float = 3.0) -> str:
        """Extract the header title (e.g. 'Set up Ref2 Battery Camera'), polling briefly if still rendering."""
        deadline = time.time() + max(0.3, timeout)
        while time.time() < deadline:
            title = self._sdf_extract_title_once()
            if title:
                return title
            time.sleep(self.SDF_POLL_INTERVAL)
        return self._sdf_extract_title_once()
    def is_title_match_device(self, target_device_name: str) -> bool:
        """Check whether the header title refers to the target device (case-insensitive)."""
        detected_title = self.get_detected_device_title(timeout=self.SDF_TITLE_WAIT_TIMEOUT)
        detected_name = self.TITLE_PREFIX_PATTERN.sub("", detected_title).strip()
        target_clean = (target_device_name or "").strip()
        if not target_clean:
            matched = bool(detected_name)
        else:
            matched = bool(detected_name) and (
                    target_clean.lower() in detected_name.lower()
                    or detected_name.lower() in target_clean.lower()
            )
        self._logger.info(
            f"[SingleDevice] Title: '{detected_title}' (Device: '{detected_name}') | "
            f"Expected: '{target_clean}' | Match: {matched}"
        )
        return matched

    def click_next_button(self) -> bool:
        """Click 'Next' and verify the page transitioned (Next button disappears)."""
        for use_coordinates in (False, True):
            next_btn = self._sdf_find_first(self.NEXT_BTN_LOCATORS, allow_hidden=True)
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
            if self._sdf_wait_gone([self.NAV_BAR, self.NEXT_BTN_LOCATORS[0]], timeout=self.SDF_LEAVE_PAGE_TIMEOUT):
                self._logger.info("[SingleDevice] Successfully proceeded from Single Device Found page.")
                return True
        self._logger.error("[SingleDevice] Failed to leave Single Device Found page.")
        return False
    def click_different_device_button(self) -> bool:
        """Click 'Set up a different device' and verify leaving SingleDeviceFoundView."""
        for use_coordinates in (False, True):
            diff_btn = self._sdf_find_first(self.DIFFERENT_DEVICE_BTN_LOCATORS, allow_hidden=True)
            if diff_btn is None:
                if use_coordinates:
                    self._logger.info("[SingleDevice] 'Set up a different device' button already gone.")
                    return True
                self._logger.warning("[SingleDevice] 'Set up a different device' button not found.")
                return False
            try:
                if use_coordinates:
                    self._logger.warning(
                        "[SingleDevice] Still on Single Device page. Retrying 'Set up a different device' with coordinate tap..."
                    )
                    self._sdf_tap_center(diff_btn)
                else:
                    self._logger.info("[SingleDevice] Clicking 'Set up a different device'...")
                    diff_btn.click()
            except WebDriverException as err:
                self._logger.warning(f"[SingleDevice] Tap on 'Set up a different device' failed: {err}")
                continue
            if self._sdf_wait_gone(
                    [self.NAV_BAR, self.DIFFERENT_DEVICE_BTN_LOCATORS[0]],
                    timeout=3.5,
            ):
                self._logger.info("[SingleDevice] Clicked 'Set up a different device' and left Single Device page.")
                return True
        self._logger.warning("[SingleDevice] Finished clicking 'Set up a different device'.")
        return True

    def _sdf_is_on_home_page(self) -> bool:
        """Check if GHA has returned to the main Home/Devices screen (setup modal closed)."""
        if self._sdf_find_first(self.CLOSE_BTN_LOCATORS) is not None:
            return False
        if self._sdf_find_any(*self.NAV_BAR) is not None:
            return False
        return self._sdf_find_first(self.HOME_READY_LOCATORS) is not None
    def click_back_btn(self) -> bool:
        """Close or back out of the setup flow until returning to GHA Home screen."""
        self._logger.info("[SingleDevice] Looking for close/back button to return to Home screen...")
        clicked_any = False
        prev_label: Optional[str] = None
        for step in range(1, self.SDF_MAX_BACK_STEPS + 1):
            if step > 1 and self._sdf_is_on_home_page():
                self._logger.info("[SingleDevice] Confirmed back on GHA Home screen.")
                return True
            btn = self._sdf_find_first(self.BACK_BTN_LOCATORS, allow_hidden=True)
            if btn is None:
                if clicked_any and self._sdf_is_on_home_page():
                    return True
                break
            btn_label = self._sdf_read_text(btn) or "close/back"
            use_coordinates = (btn_label == prev_label)
            prev_label = btn_label
            try:
                if use_coordinates:
                    self._logger.info(
                        f"[SingleDevice] '{btn_label}' still present; coordinate-tapping "
                        f"(step {step}/{self.SDF_MAX_BACK_STEPS})..."
                    )
                    self._sdf_tap_center(btn)
                else:
                    self._logger.info(
                        f"[SingleDevice] Clicking '{btn_label}' button "
                        f"(step {step}/{self.SDF_MAX_BACK_STEPS})..."
                    )
                    if not self._sdf_click(btn):
                        self._sdf_tap_center(btn)
            except WebDriverException as err:
                self._logger.warning(f"[SingleDevice] Tap on '{btn_label}' failed: {err}")
            clicked_any = True
            time.sleep(1.5)
            if self._sdf_is_on_home_page():
                self._logger.info(f"[SingleDevice] Clicked '{btn_label}' and returned to Home screen.")
                return True
        if clicked_any:
            self._logger.info("[SingleDevice] Completed back/close button sequence.")
            return True
        self._logger.warning("[SingleDevice] Fallback: tapping top-left navigation bar corner (28, 56)...")
        try:
            self.driver.execute_script("mobile: tap", {"x": 28, "y": 56})
            time.sleep(1.5)
            return True
        except WebDriverException as e:
            self._logger.error(f"[SingleDevice] Failed to click back: {e}")
            return False

    @classmethod
    def handle_if_present(cls, session_or_page, target_device_name: str = "", timeout: float = 10.0) -> bool:
        """Handle the Single Device Found screen if present.
        Returns:
            True  -> Single page matched target and 'Next' was clicked successfully.
            False -> Not a single page (multi-device list), or detected device mismatched
                     and the flow was reset back to the device list.
        """
        from page_object.iGHA.gha_add_page import GHAAddPage
        from page_object.iGHA.gha_home_page import GHAHomePage
        driver = (
            session_or_page
            if hasattr(session_or_page, "find_elements")
            else getattr(session_or_page, "driver", session_or_page)
        )
        raw_target = target_device_name
        if not raw_target and not hasattr(session_or_page, "find_elements"):
            raw_target = getattr(session_or_page, "device_name", "")
        resolved_target = str(raw_target or "").strip()
        page = cls(driver)
        if not page.is_single_device_found_page(timeout=timeout):
            page._logger.info("[SingleDevice] Not a Single Device screen. Proceeding with list flow...")
            return False
        if page.is_title_match_device(resolved_target):
            return page.click_next_button()
        page._logger.warning(
            f"[SingleDevice] Detected device does NOT match '{resolved_target}'. "
            f"Switching to a different device..."
        )
        page.click_different_device_button()
        page.click_back_btn()
        GHAHomePage(driver).click_add_devices_button()
        GHAAddPage(driver).navigate_to_setup_device_page()
        return False