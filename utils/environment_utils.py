"""Environment and version information collector for iOS automation."""
import re
import subprocess
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional, Sequence, Union
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from common import constants
from utils import logging_utils

logger = logging_utils.get_logger(__name__, "env_info")

SETTINGS_BUNDLE_ID = "com.apple.Preferences"
DEFAULT_IMPLICIT_WAIT = getattr(constants, "DEFAULT_IMPLICIT_WAIT", 10.0)
MAX_DETAIL_PAGE_ATTEMPTS = 5
MAX_SCROLL_ATTEMPTS = 4
INFO_ICON_EDGE_OFFSET = 25
UNKNOWN = "Unknown"
IPV4_PATTERN = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")
IGNORED_SECTIONS = ("other networks", "public networks", "my networks")
IGNORED_SSID_TEXTS = {"Wi-Fi", "Connected", "Selected"}
IPV4_FIELD_LABELS: Dict[str, Sequence[str]] = {
    "ip_address": ("IP Address",),
    "subnet_mask": ("Subnet Mask",),
    "router_gateway": ("Router",),
}

class _XPath:
    """XPath locators for iOS Settings > Wi-Fi pages (English locale only)."""
    WIFI_NAV_BAR = '//XCUIElementTypeNavigationBar[@name="Wi-Fi"]'
    WIFI_BACK_BUTTON = (
        '//XCUIElementTypeNavigationBar'
        '//XCUIElementTypeButton[@name="Wi-Fi" or @label="Wi-Fi"]'
    )
    WIFI_SETTINGS_CELL = (
        '//XCUIElementTypeCell[@name="Wi-Fi" or .//XCUIElementTypeStaticText[@name="Wi-Fi"]]'
    )
    CHECKMARK_CELL = (
        '//XCUIElementTypeCell[.//XCUIElementTypeImage'
        '[contains(@name, "checkmark") or contains(@name, "Checkmark")]]'
    )
    SELECTED_CELL = (
        '//XCUIElementTypeCell[@selected="true" or @selected="1" or '
        'starts-with(@label, "Selected") or starts-with(@name, "Selected")]'
    )
    MORE_INFO_BUTTON = (
        './/XCUIElementTypeButton[@name="More Info" or contains(@label, "More")]'
    )
    DETAIL_INDICATORS = (
        '//XCUIElementTypeStaticText[@name="Forget This Network" or @name="Auto-Join" '
        'or @name="Configure IP" or @name="IP Address"]'
    )
    SUBNET_LABEL = '//XCUIElementTypeStaticText[@name="Subnet Mask"]'
    COPY_MENU = '//XCUIElementTypeMenuItem[@name="Copy"]'
    @staticmethod
    def cell_with_labels(labels: Sequence[str]) -> str:
        """Build an XPath matching a cell that contains any of the given static-text labels."""
        condition = " or ".join(f'@name="{label}"' for label in labels)
        return f"//XCUIElementTypeCell[.//XCUIElementTypeStaticText[{condition}]]"

@contextmanager
def _implicit_wait(driver: WebDriver, seconds: float) -> Iterator[None]:
    """Temporarily override implicit wait and always restore the previous value."""
    try:
        previous = driver.timeouts.implicit_wait
    except Exception:
        previous = DEFAULT_IMPLICIT_WAIT
    driver.implicitly_wait(seconds)
    try:
        yield
    finally:
        try:
            driver.implicitly_wait(previous)
        except WebDriverException:
            pass

def _first_displayed(root: Union[WebDriver, WebElement], xpath: str) -> Optional[WebElement]:
    """Return the first displayed element matching the XPath, or None."""
    try:
        for element in root.find_elements(AppiumBy.XPATH, xpath):
            if element.is_displayed():
                return element
    except WebDriverException:
        pass
    return None

def _tap(driver: WebDriver, x: int, y: int) -> None:
    driver.execute_script("mobile: tap", {"x": x, "y": y})

def _tap_rect_center(driver: WebDriver, rect: Dict[str, float]) -> None:
    _tap(driver, int(rect["x"] + rect["width"] / 2), int(rect["y"] + rect["height"] / 2))

def _tap_info_icon_of_cell(driver: WebDriver, cell: WebElement) -> None:
    """Tap the right edge of a Wi-Fi cell where the (i) icon is located."""
    rect = cell.rect
    x = int(rect["x"] + rect["width"] - INFO_ICON_EDGE_OFFSET)
    y = int(rect["y"] + rect["height"] / 2)
    logger.info(f"Coordinate-tapping (i) icon at ({x}, {y})...")
    _tap(driver, x, y)

def _swipe_up_to_scroll_down(driver: WebDriver) -> None:
    """Fast swipe up (scroll content down) without triggering iOS long-press / Copy menu."""
    try:
        if driver.find_elements(AppiumBy.XPATH, _XPath.COPY_MENU):
            driver.find_element(AppiumBy.CLASS_NAME, "XCUIElementTypeNavigationBar").click()
            time.sleep(0.3)
    except WebDriverException:
        pass
    try:
        driver.execute_script("mobile: swipe", {"direction": "up"})
        return
    except WebDriverException as err:
        logger.debug(f"mobile: swipe failed, falling back to W3C flick: {err}")
    try:
        size = driver.get_window_size()
        x = int(size["width"] * 0.5)
        start_y, end_y = int(size["height"] * 0.75), int(size["height"] * 0.35)
        actions = ActionChains(driver)
        actions.w3c_actions = ActionBuilder(
            driver, mouse=PointerInput(interaction.POINTER_TOUCH, "touch")
        )
        pointer = actions.w3c_actions.pointer_action
        pointer.move_to_location(x, start_y)
        pointer.pointer_down()
        pointer.pause(0.05)
        pointer.move_to_location(x, end_y)
        pointer.pointer_up()
        actions.perform()
    except WebDriverException as err:
        logger.debug(f"W3C flick failed: {err}")

def _version_from_list_apps(driver: WebDriver, bundle_id: str) -> Optional[str]:
    """Read app version via Appium `mobile: listApps`."""
    apps = driver.execute_script("mobile: listApps", {"applicationType": "User"})
    info: Any = None
    if isinstance(apps, list):
        info = next(
            (a for a in apps if isinstance(a, dict) and a.get("CFBundleIdentifier") == bundle_id),
            None,
        )
    elif isinstance(apps, dict):
        info = apps.get(bundle_id)
    if isinstance(info, str):
        return info.strip()
    if isinstance(info, dict):
        version = (
                info.get("CFBundleShortVersionString")
                or info.get("CFBundleVersion")
                or info.get("version")
        )
        return str(version).strip() if version else None
    return None

def _version_from_ideviceinstaller(bundle_id: str) -> Optional[str]:
    """Read app version via `ideviceinstaller --list-apps` CLI."""
    output = subprocess.check_output(
        ["ideviceinstaller", "--list-apps"], stderr=subprocess.STDOUT, timeout=5
    ).decode("utf-8", errors="ignore")
    for line in output.splitlines():
        if bundle_id in line:
            parts = line.split("-")
            if len(parts) >= 2:
                return parts[1].strip()
    return None

def get_app_version(driver: WebDriver, bundle_id: str) -> str:
    """Retrieve an installed iOS app version via Appium, falling back to ideviceinstaller.
    Args:
        driver: Appium driver instance.
        bundle_id: Target application bundle identifier.
    Returns:
        Version string (e.g. '4.29.25') or 'Unknown / Not Installed'.
    """
    if not bundle_id:
        return "Unknown / Not Installed"
    try:
        version = _version_from_list_apps(driver, bundle_id)
        if version:
            return version
    except Exception as err:
        logger.debug(f"Appium listApps failed for {bundle_id}: {err}")
    try:
        version = _version_from_ideviceinstaller(bundle_id)
        if version:
            return version
    except Exception as err:
        logger.debug(f"ideviceinstaller failed for {bundle_id}: {err}")
    return "Unknown / Not Installed"

def get_ios_device_info(driver: WebDriver) -> Dict[str, Any]:
    """Collect iOS device name, platform version, UDID, and screen resolution."""
    caps = driver.capabilities or {}
    device_info: Dict[str, Any] = {
        "device_name": caps.get("deviceName", "iPhone 11 Pro"),
        "platform_version": caps.get("platformVersion", "iOS 17+"),
        "udid": caps.get("udid", caps.get("deviceUDID", "00008030-00064DC43EEA802E")),
    }
    try:
        size = driver.get_window_size()
        device_info["screen_resolution"] = f"{size.get('width')}x{size.get('height')}"
    except WebDriverException:
        device_info["screen_resolution"] = UNKNOWN
    return device_info

def _is_in_wifi_detail_page(driver: WebDriver, ssid: str = "") -> bool:
    """Return True if the screen is on the Wi-Fi 'More Info' detail page."""
    if _first_displayed(driver, _XPath.WIFI_NAV_BAR):
        return False
    candidates = [_XPath.WIFI_BACK_BUTTON, _XPath.DETAIL_INDICATORS]
    if ssid and ssid != UNKNOWN and '"' not in ssid:
        candidates.insert(0, f'//XCUIElementTypeNavigationBar[@name="{ssid}"]')
    return any(_first_displayed(driver, xpath) for xpath in candidates)

def _open_wifi_list_page(driver: WebDriver) -> None:
    """Navigate to Settings > Wi-Fi list, backing out of a stale detail page if needed."""
    back_btn = _first_displayed(driver, _XPath.WIFI_BACK_BUTTON)
    if back_btn:
        logger.info("Returning from previous Wi-Fi detail page back to Wi-Fi list...")
        back_btn.click()
        time.sleep(1.2)
    if driver.find_elements(AppiumBy.XPATH, _XPath.WIFI_NAV_BAR):
        return
    wifi_cells = driver.find_elements(AppiumBy.XPATH, _XPath.WIFI_SETTINGS_CELL)
    if wifi_cells:
        try:
            wifi_cells[0].click()
            time.sleep(2.0)
        except WebDriverException as err:
            logger.debug(f"Failed to click Wi-Fi cell in Settings: {err}")

def _find_connected_cell(driver: WebDriver) -> Optional[WebElement]:
    """Find the currently connected network cell (checkmark first, then 'Selected' trait)."""
    for xpath in (_XPath.CHECKMARK_CELL, _XPath.SELECTED_CELL):
        for cell in driver.find_elements(AppiumBy.XPATH, xpath):
            label = (cell.get_attribute("label") or cell.get_attribute("name") or "").lower()
            if not any(section in label for section in IGNORED_SECTIONS):
                return cell
    return None

def _is_valid_ssid(text: str) -> bool:
    return bool(text) and text not in IGNORED_SSID_TEXTS \
        and not text.startswith("_Tt") and "SwiftUI" not in text

def _extract_ssid(cell: WebElement) -> str:
    """Extract the SSID from a connected Wi-Fi cell."""
    for text_el in cell.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText"):
        text = (
                text_el.get_attribute("value") or text_el.get_attribute("name") or text_el.text or ""
        ).strip()
        if _is_valid_ssid(text):
            return text
    cell_name = cell.get_attribute("name") or cell.get_attribute("label") or ""
    candidate = cell_name.replace("Selected,", "").split(",")[0].strip()
    return candidate if _is_valid_ssid(candidate) else UNKNOWN

def _find_info_button(cell: WebElement) -> Optional[WebElement]:
    """Locate the (i) More Info button inside a Wi-Fi cell."""
    try:
        buttons = (
                cell.find_elements(AppiumBy.XPATH, _XPath.MORE_INFO_BUTTON)
                or cell.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeButton")
        )
        return buttons[-1] if buttons else None
    except WebDriverException:
        return None

def _tap_more_info(driver: WebDriver, cell: WebElement, attempt: int) -> None:
    """Tap the (i) button: element click on the first attempt, coordinate tap afterwards."""
    info_btn = _find_info_button(cell)
    if info_btn is None:
        _tap_info_icon_of_cell(driver, cell)
        return
    if attempt == 1:
        try:
            info_btn.click()
            return
        except WebDriverException:
            pass
    _tap_rect_center(driver, info_btn.rect)

def _enter_wifi_detail_page(driver: WebDriver, wifi_info: Dict[str, str]) -> bool:
    """Enter the connected network's More Info page, filling in the SSID along the way."""
    for attempt in range(1, MAX_DETAIL_PAGE_ATTEMPTS + 1):
        try:
            if _is_in_wifi_detail_page(driver, wifi_info["ssid"]):
                return True
            cell = _find_connected_cell(driver)
            if cell is None:
                time.sleep(0.8)
                continue
            if wifi_info["ssid"] == UNKNOWN:
                wifi_info["ssid"] = _extract_ssid(cell)
                if wifi_info["ssid"] != UNKNOWN:
                    logger.info(f"Extracted active Wi-Fi SSID: '{wifi_info['ssid']}'")
            logger.info(
                f"Clicking More Info for '{wifi_info['ssid']}' "
                f"(attempt {attempt}/{MAX_DETAIL_PAGE_ATTEMPTS})..."
            )
            _tap_more_info(driver, cell, attempt)
            time.sleep(1.5)
            if _is_in_wifi_detail_page(driver, wifi_info["ssid"]):
                logger.info(f"Confirmed inside More Info detail page for '{wifi_info['ssid']}'!")
                return True
            logger.warning(
                f"[Attempt {attempt}/{MAX_DETAIL_PAGE_ATTEMPTS}] Still on Wi-Fi list page. "
                f"Retrying with right-edge tap..."
            )
            _tap_info_icon_of_cell(driver, cell)
            time.sleep(1.2)
            if _is_in_wifi_detail_page(driver, wifi_info["ssid"]):
                logger.info("Confirmed inside More Info detail page after fallback tap!")
                return True
        except WebDriverException as err:
            logger.debug(f"[Attempt {attempt}] Wi-Fi list refreshed during inspection: {err}")
            time.sleep(0.8)
    return False

def _scroll_to_ipv4_section(driver: WebDriver) -> None:
    """Scroll down the detail page until the Subnet Mask row is visible."""
    for _ in range(MAX_SCROLL_ATTEMPTS):
        if _first_displayed(driver, _XPath.SUBNET_LABEL):
            return
        _swipe_up_to_scroll_down(driver)
        time.sleep(0.6)

def _extract_ipv4_value(driver: WebDriver, labels: Sequence[str]) -> str:
    """Return the IPv4 value shown in the cell whose label matches one of `labels`."""
    try:
        cells = driver.find_elements(AppiumBy.XPATH, _XPath.cell_with_labels(labels))
    except WebDriverException:
        return UNKNOWN
    for cell in cells:
        try:
            for text_el in cell.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText"):
                text = (
                        text_el.text or text_el.get_attribute("value") or text_el.get_attribute("name") or ""
                ).strip()
                if IPV4_PATTERN.fullmatch(text):
                    return text
        except WebDriverException:
            continue
    return UNKNOWN

def _return_to_target_app(driver: WebDriver) -> None:
    """Leave the Wi-Fi detail page and switch back to the Google Home app."""
    back_btn = _first_displayed(driver, _XPath.WIFI_BACK_BUTTON)
    if back_btn:
        try:
            back_btn.click()
            time.sleep(0.5)
        except WebDriverException:
            pass
    target_bundle = getattr(constants, "GHA_BUNDLE_ID", "com.google.Chromecast.enterprise")
    try:
        logger.info(f"Switching back to target app: {target_bundle}...")
        driver.activate_app(target_bundle)
        time.sleep(1.0)
    except WebDriverException as err:
        logger.warning(f"Failed to switch back to {target_bundle}: {err}")

def get_wifi_information(driver: WebDriver) -> Dict[str, str]:
    """Retrieve the connected Wi-Fi SSID, IP, subnet mask, and router from iOS Settings.
    The active network is identified strictly by its checkmark icon / 'Selected' trait,
    ignoring networks listed under 'Other Networks' or 'Public Networks'.
    """
    wifi_info = {
        "ssid": UNKNOWN,
        "ip_address": UNKNOWN,
        "router_gateway": UNKNOWN,
        "subnet_mask": UNKNOWN,
    }
    with _implicit_wait(driver, 0):
        try:
            logger.info("Opening iOS Settings to inspect Wi-Fi details...")
            driver.activate_app(SETTINGS_BUNDLE_ID)
            time.sleep(1.5)
            _open_wifi_list_page(driver)
            if not _enter_wifi_detail_page(driver, wifi_info):
                logger.warning(
                    f"Could not enter More Info page for '{wifi_info['ssid']}' after "
                    f"{MAX_DETAIL_PAGE_ATTEMPTS} attempts. Skipping IPv4 extraction."
                )
                return wifi_info
            logger.info("Swiping up to reveal IPv4 Address section...")
            _scroll_to_ipv4_section(driver)
            for key, labels in IPV4_FIELD_LABELS.items():
                wifi_info[key] = _extract_ipv4_value(driver, labels)
            logger.info(f"Successfully collected Wi-Fi information: {wifi_info}")
        except Exception as err:
            logger.warning(f"Failed to retrieve Wi-Fi details from Settings: {err}. Using fallback values.")
        finally:
            _return_to_target_app(driver)
    return wifi_info

def log_all_version_information(driver: WebDriver) -> Dict[str, Any]:
    """Collect and log all system, app, and network version details.
    Args:
        driver: Appium driver instance.
    Returns:
        Consolidated environment information dictionary.
    """
    separator = "=" * 60
    logger.info(separator)
    logger.info(" [ENV INFO] Collecting Environment & Version Information")
    logger.info(separator)
    gha_version = get_app_version(driver, constants.GHA_BUNDLE_ID)
    sample_version = get_app_version(driver, getattr(constants, "iGHP_SAMPLE_APP_BUNDLE_ID", ""))
    device_info = get_ios_device_info(driver)
    wifi_info = get_wifi_information(driver)
    rows = [
        ("Google Home App Version", gha_version),
        ("Sample App Version", sample_version),
        ("iOS Device Name", device_info.get("device_name")),
        ("iOS Platform Version", device_info.get("platform_version")),
        ("Device UDID", device_info.get("udid")),
        ("Screen Size", device_info.get("screen_resolution")),
        ("Connected Wi-Fi SSID", wifi_info.get("ssid")),
        ("Device IP Address", wifi_info.get("ip_address")),
        ("Router Gateway", wifi_info.get("router_gateway")),
        ("Subnet Mask", wifi_info.get("subnet_mask")),
    ]
    for label, value in rows:
        logger.info(f"  * {label:<24}: {value}")
    logger.info(separator)
    return {
        "gha_version": gha_version,
        "sample_version": sample_version,
        "device_info": device_info,
        "wifi_info": wifi_info,
    }