"""Environment and version information collector for iOS automation."""
import os
import re
import subprocess
import time
from typing import Any, Dict, Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from selenium.common.exceptions import (
    WebDriverException,
    StaleElementReferenceException,
    NoSuchElementException
)
from common import constants
from utils import logging_utils


logger = logging_utils.get_logger(__name__, "env_info")

def _swipe_up_to_scroll_down(driver: WebDriver) -> None:
    """Perform a fast swipe up (scrolling content down) without triggering iOS long-press / Copy menu."""
    try:
        copy_menus = driver.find_elements(
            AppiumBy.XPATH,
            '//XCUIElementTypeMenuItem[@name="Copy" or @name="拷貝"]'
        )
        if copy_menus:
            nav_bar = driver.find_element(AppiumBy.CLASS_NAME, "XCUIElementTypeNavigationBar")
            nav_bar.click()
            time.sleep(0.3)
    except Exception:
        pass
    try:
        driver.execute_script("mobile: swipe", {"direction": "up"})
        time.sleep(0.8)
        return
    except Exception:
        pass
    try:
        size = driver.get_window_size()
        start_x = int(size["width"] * 0.5)
        start_y = int(size["height"] * 0.75)
        end_y = int(size["height"] * 0.25)
        driver.swipe(start_x, start_y, start_x, end_y, duration=300)
        time.sleep(0.8)
    except Exception as e:
        logger.debug(f"Fallback swipe failed: {e}")

def _is_in_wifi_detail_page(driver: WebDriver, ssid_name: str = "") -> bool:
    """Check if the current screen is inside the specific Wi-Fi network's More Info detail page."""
    try:
        wifi_nav = driver.find_elements(
            AppiumBy.XPATH,
            '//XCUIElementTypeNavigationBar[@name="Wi-Fi" or @name="Wi‑Fi"]'
        )
        if wifi_nav:
            return False
        if ssid_name and ssid_name not in ("Unknown", "Error"):
            safe_ssid = ssid_name.replace('"', '\\"')
            ssid_nav = driver.find_elements(
                AppiumBy.XPATH,
                f'//XCUIElementTypeNavigationBar[@name="{safe_ssid}" or contains(@name, "{safe_ssid}")]'
            )
            if ssid_nav:
                return True
        detail_indicators = driver.find_elements(
            AppiumBy.XPATH,
            '//XCUIElementTypeStaticText['
            '@name="Forget This Network" or '
            '@name="Auto-Join" or '
            '@name="Configure IP" or '
            '@name="IP Address" or @name="IP址" or '
            '@name="Private Wi-Fi Address"'
            ']'
        )
        return len(detail_indicators) > 0
    except Exception:
        return False

def _extract_cell_value(driver: WebDriver, xpath_query: str, pattern: str, exclude_words: list) -> str:
    """Extract IPv4/Subnet/Router text value from a matching XCUIElementTypeCell."""
    try:
        cells = driver.find_elements(AppiumBy.XPATH, xpath_query)
        for cell in cells:
            for attr in ("value", "label", "name"):
                val = cell.get_attribute(attr) or ""
                m = re.search(pattern, val)
                if m:
                    return m.group(0)
            texts = cell.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText")
            for t in texts:
                for attr in ("value", "label", "name"):
                    txt = (t.get_attribute(attr) or "").strip()
                    if txt and txt not in exclude_words:
                        m = re.search(pattern, txt)
                        if m:
                            return m.group(0)
    except Exception:
        pass
    return "Unknown"

def get_wifi_information(driver: WebDriver, target_bundle_id: str = constants.GHA_BUNDLE_ID) -> Dict[str, str]:
    """Navigate to iOS Settings -> Wi-Fi to extract current SSID, IP Address, Subnet Mask, and Router."""
    wifi_info = {
        "ssid": "Unknown",
        "ip_address": "Unknown",
        "subnet_mask": "Unknown",
        "router": "Unknown"
    }
    default_wait = getattr(constants, "DEFAULT_IMPLICIT_WAIT", 10.0)
    logger.info("Opening iOS Settings to inspect Wi-Fi details...")
    try:
        driver.implicitly_wait(0)
        try:
            driver.terminate_app("com.apple.Preferences")
            time.sleep(0.5)
        except Exception:
            pass
        driver.activate_app("com.apple.Preferences")
        time.sleep(2.0)
        try:
            back_to_wifi_btns = driver.find_elements(
                AppiumBy.XPATH,
                '//XCUIElementTypeNavigationBar/XCUIElementTypeButton[@name="Wi-Fi" or @name="Wi‑Fi"]'
            )
            if back_to_wifi_btns:
                back_to_wifi_btns[0].click()
                time.sleep(1.0)
        except Exception:
            pass
        in_wifi_page = False
        try:
            wifi_nav = driver.find_elements(
                AppiumBy.XPATH,
                '//XCUIElementTypeNavigationBar[@name="Wi-Fi" or @name="Wi‑Fi"]'
            )
            if wifi_nav:
                in_wifi_page = True
        except Exception:
            pass
        if not in_wifi_page:
            for _ in range(3):
                try:
                    back_btns = driver.find_elements(
                        AppiumBy.XPATH,
                        '//XCUIElementTypeNavigationBar/XCUIElementTypeButton[1]'
                    )
                    if back_btns and back_btns[0].is_displayed():
                        btn_name = back_btns[0].get_attribute("name") or ""
                        if btn_name not in ("", "Settings") or len(back_btns) > 0:
                            back_btns[0].click()
                            time.sleep(0.8)
                        else:
                            break
                    else:
                        break
                except Exception:
                    break
            wifi_cell = None
            for _ in range(3):
                cells = driver.find_elements(
                    AppiumBy.XPATH,
                    '//XCUIElementTypeCell[.//XCUIElementTypeStaticText[@name="Wi-Fi" or @name="Wi‑Fi"]]'
                )
                if cells:
                    wifi_cell = cells[0]
                    break
                time.sleep(1.0)
            if wifi_cell:
                try:
                    val = wifi_cell.get_attribute("value")
                    if val and val not in ("Off", "Not Connected"):
                        wifi_info["ssid"] = str(val).strip()
                except Exception:
                    pass
                wifi_cell.click()
                time.sleep(2.0)
        entered_detail = False
        for attempt in range(3):
            active_cell = None
            cells = driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeCell")
            for cell in cells:
                try:
                    cname = cell.get_attribute("name") or ""
                    clabel = cell.get_attribute("label") or ""
                    if cname in ("Wi-Fi", "Wi‑Fi", "Ask to Join Networks", "Auto-Join Hotspot"):
                        continue
                    more_btns = cell.find_elements(
                        AppiumBy.XPATH,
                        './/XCUIElementTypeButton[contains(@name, "More Info") or contains(@label, "More Info")]'
                    )
                    if not more_btns:
                        continue
                    images = cell.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeImage")
                    has_checkmark = False
                    for img in images:
                        img_name = (img.get_attribute("name") or "").lower()
                        if "checkmark" in img_name or "selected" in img_name:
                            has_checkmark = True
                            break
                    if has_checkmark or (wifi_info["ssid"] != "Unknown" and wifi_info["ssid"] in (cname or clabel)):
                        active_cell = cell
                        if wifi_info["ssid"] == "Unknown":
                            raw_ssid = cname or clabel
                            cleaned_ssid = re.split(r',|，|Secure|Unsecured|Signal', raw_ssid)[0].strip()
                            if cleaned_ssid:
                                wifi_info["ssid"] = cleaned_ssid
                                logger.info(f"Extracted active Wi-Fi SSID from checkmark cell: '{cleaned_ssid}'")
                        break
                except Exception:
                    continue
            if active_cell:
                logger.info(
                    f"Clicking More Info button for verified '{wifi_info['ssid']}' (attempt {attempt + 1})..."
                )
                try:
                    more_btn = active_cell.find_element(
                        AppiumBy.XPATH,
                        './/XCUIElementTypeButton[contains(@name, "More Info") or contains(@label, "More Info")]'
                    )
                    more_btn.click()
                except Exception:
                    rect = active_cell.rect
                    tap_x = int(rect["x"] + rect["width"] - 28)
                    tap_y = int(rect["y"] + (rect["height"] / 2))
                    logger.info(f"Using coordinate tap at ({tap_x}, {tap_y}) for More Info button...")
                    driver.execute_script("mobile: tap", {"x": tap_x, "y": tap_y})
            else:
                more_info_btns = driver.find_elements(
                    AppiumBy.XPATH,
                    '//XCUIElementTypeButton[contains(@name, "More Info") or contains(@label, "More Info"))]'
                )
                if more_info_btns:
                    logger.info(
                        f"Fallback: Clicking first More Info button on Wi-Fi page (attempt {attempt + 1})..."
                    )
                    try:
                        more_info_btns[0].click()
                    except Exception:
                        rect = more_info_btns[0].rect
                        driver.execute_script(
                            "mobile: tap",
                            {"x": int(rect["x"] + rect["width"] / 2), "y": int(rect["y"] + rect["height"] / 2)}
                        )
            time.sleep(2.0)
            if _is_in_wifi_detail_page(driver, wifi_info["ssid"]):
                logger.info(f"Confirmed inside More Info detail page for '{wifi_info['ssid']}'!")
                entered_detail = True
                break
            else:
                logger.warning(
                    f"Still on Wi-Fi list page after clicking More Info (attempt {attempt + 1}/3). Retrying..."
                )
                if active_cell and attempt >= 1:
                    try:
                        rect = active_cell.rect
                        tap_x = int(rect["x"] + rect["width"] - 28)
                        tap_y = int(rect["y"] + (rect["height"] / 2))
                        driver.execute_script("mobile: tap", {"x": tap_x, "y": tap_y})
                        time.sleep(2.0)
                        if _is_in_wifi_detail_page(driver, wifi_info["ssid"]):
                            logger.info(
                                f"Confirmed inside More Info detail page after coordinate tap for '{wifi_info['ssid']}'!"
                            )
                            entered_detail = True
                            break
                    except Exception:
                        pass
        if not entered_detail:
            logger.warning("Could not confirm entry into Wi-Fi More Info detail page.")
        logger.info("Swiping up to reveal IPv4 Address section...")
        for _ in range(3):
            _swipe_up_to_scroll_down(driver)
            try:
                ip_labels = driver.find_elements(
                    AppiumBy.XPATH,
                    '//XCUIElementTypeStaticText[@name="IP Address" or @name="IP" or @name="Router"]'
                )
                if ip_labels and any(el.is_displayed() for el in ip_labels):
                    subnets = driver.find_elements(
                        AppiumBy.XPATH,
                        '//XCUIElementTypeStaticText[@name="Subnet Mask" or @name="Subnet"]'
                    )
                    if subnets and any(el.is_displayed() for el in subnets):
                        break
            except Exception:
                pass
        ip_cell_xpath = (
            '//XCUIElementTypeCell[.//XCUIElementTypeStaticText['
            '@name="IP Address" or @name="IP" or @name="Address"'
            ']]'
        )
        ip_val = _extract_cell_value(
            driver,
            ip_cell_xpath,
            r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
            ["IP Address", "IP", "Address"]
        )
        if ip_val != "Unknown":
            wifi_info["ip_address"] = ip_val
        subnet_cell_xpath = (
            '//XCUIElementTypeCell[.//XCUIElementTypeStaticText['
            '@name="Subnet Mask" or @name="Subnet"'
            ']]'
        )
        subnet_val = _extract_cell_value(
            driver,
            subnet_cell_xpath,
            r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
            ["Subnet Mask", "Subnet"]
        )
        if subnet_val != "Unknown":
            wifi_info["subnet_mask"] = subnet_val
        router_cell_xpath = (
            '//XCUIElementTypeCell[.//XCUIElementTypeStaticText['
            '@name="Router"'
            ']]'
        )
        router_val = _extract_cell_value(
            driver,
            router_cell_xpath,
            r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
            ["Router"]
        )
        if router_val != "Unknown":
            wifi_info["router"] = router_val
    except Exception as e:
        logger.warning(f"Failed to retrieve Wi-Fi details from Settings: {e}. Using fallback values.")
    finally:
        try:
            driver.implicitly_wait(default_wait)
        except Exception:
            pass
        try:
            logger.info(f"Switching back to target app: {target_bundle_id}...")
            driver.activate_app(target_bundle_id)
            time.sleep(1.5)
        except Exception as e:
            logger.error(f"Failed to switch back to {target_bundle_id}: {e}")
    logger.info(
        f"Wi-Fi Information collected: SSID='{wifi_info['ssid']}', "
        f"IP='{wifi_info['ip_address']}', Subnet='{wifi_info['subnet_mask']}', Router='{wifi_info['router']}'"
    )
    return wifi_info

def get_ios_device_version(udid: str) -> str:
    """Retrieve the iOS version of the connected iPhone via ideviceinfo or xcrun."""
    try:
        res = subprocess.run(
            ["ideviceinfo", "-u", udid, "-k", "ProductVersion"],
            capture_output=True, text=True, timeout=5
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return "Unknown"

def get_app_version_from_device(udid: str, bundle_id: str) -> str:
    """Retrieve the installed Google Home app version via ideviceinstaller or mobile: listApps."""
    try:
        res = subprocess.run(
            ["ideviceinstaller", "-u", udid, "-l", "-o", "xml"],
            capture_output=True, text=True, timeout=10
        )
        if res.returncode == 0 and bundle_id in res.stdout:
            match = re.search(
                rf"<string>{re.escape(bundle_id)}</string>.*?<key>CFBundleShortVersionString</key>\s*<string>([^<]+)</string>",
                res.stdout,
                re.DOTALL
            )
            if match:
                return match.group(1).strip()
    except Exception:
        pass
    return "Unknown"

def log_all_version_information(
        driver: WebDriver,
        udid: str = constants.iOS_UUID,
        bundle_id: str = constants.GHA_BUNDLE_ID
) -> Dict[str, Any]:
    """Collect and log all environment, OS, App, and Wi-Fi version information."""
    env_summary: Dict[str, Any] = {
        "udid": udid,
        "bundle_id": bundle_id,
        "ios_version": get_ios_device_version(udid),
        "app_version": get_app_version_from_device(udid, bundle_id),
    }
    try:
        caps = driver.capabilities
        if env_summary["ios_version"] == "Unknown":
            env_summary["ios_version"] = caps.get("platformVersion", "Unknown")
    except Exception:
        pass
    wifi_details = get_wifi_information(driver, target_bundle_id=bundle_id)
    env_summary["wifi"] = wifi_details
    logger.info("====================================================")
    logger.info(f"Environment & Version Summary: {env_summary}")
    logger.info("====================================================")
    return env_summary