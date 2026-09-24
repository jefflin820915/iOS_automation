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
        return
    except Exception as e:
        logger.debug(f"mobile: swipe failed: {e}")
    try:
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.common.actions import interaction
        from selenium.webdriver.common.actions.action_builder import ActionBuilder
        from selenium.webdriver.common.actions.pointer_input import PointerInput
        win = driver.get_window_size()
        w, h = win["width"], win["height"]
        start_x = int(w * 0.5)
        start_y = int(h * 0.75)
        end_y = int(h * 0.35)
        actions = ActionChains(driver)
        actions.w3c_actions = ActionBuilder(driver, mouse=PointerInput(interaction.POINTER_TOUCH, "touch"))
        actions.w3c_actions.pointer_action.move_to_location(start_x, start_y)
        actions.w3c_actions.pointer_action.pointer_down()
        actions.w3c_actions.pointer_action.pause(0.05)
        actions.w3c_actions.pointer_action.move_to_location(start_x, end_y)
        actions.w3c_actions.pointer_action.pointer_up()
        actions.perform()
    except Exception as e:
        logger.debug(f"W3C flick failed: {e}")

def _is_in_wifi_detail_page(driver: WebDriver, ssid: str = "") -> bool:
    """Verify whether the screen has actually navigated into the Wi-Fi More Info detail page."""
    try:
        wifi_nav = driver.find_elements(AppiumBy.XPATH, '//XCUIElementTypeNavigationBar[@name="Wi-Fi"]')
        if wifi_nav and wifi_nav[0].is_displayed():
            return False
        detail_xpaths = [
            '//XCUIElementTypeNavigationBar//XCUIElementTypeButton[@name="Wi-Fi" or @label="Wi-Fi"]',
            '//XCUIElementTypeStaticText[@name="Forget This Network" or @name="Auto-Join" or @name="Configure IP" or @name="IP Address"]',
        ]
        if ssid and ssid != "Unknown":
            detail_xpaths.insert(0, f'//XCUIElementTypeNavigationBar[@name="{ssid}"]')
        for xp in detail_xpaths:
            elems = driver.find_elements(AppiumBy.XPATH, xp)
            if elems and elems[0].is_displayed():
                return True
    except Exception:
        pass
    return False

def get_app_version(driver: WebDriver, bundle_id: str) -> str:
    """Retrieve any iOS installed App version via Appium or ideviceinstaller CLI.
    Args:
        driver (WebDriver): Appium driver instance.
        bundle_id (str): Target application bundle identifier.
    Returns:
        str: Clean application version string (e.g. '4.29.25') or 'Unknown / Not Installed'.
    """
    try:
        apps = driver.execute_script("mobile: listApps", {"applicationType": "User"})
        target_info = None
        if isinstance(apps, list):
            for app in apps:
                if isinstance(app, dict) and app.get("CFBundleIdentifier") == bundle_id:
                    target_info = app
                    break
        elif isinstance(apps, dict) and bundle_id in apps:
            val = apps[bundle_id]
            if isinstance(val, dict):
                target_info = val
            elif isinstance(val, str):
                return val.strip()
        if isinstance(target_info, dict):
            version = (
                    target_info.get("CFBundleShortVersionString")
                    or target_info.get("CFBundleVersion")
                    or target_info.get("version")
            )
            if version:
                return str(version).strip()
    except Exception as e:
        logger.debug(f"Appium listApps failed for {bundle_id}: {e}")
    try:
        output = subprocess.check_output(
            ["ideviceinstaller", "--list-apps"],
            stderr=subprocess.STDOUT,
            timeout=5
        ).decode("utf-8", errors="ignore")
        for line in output.splitlines():
            if bundle_id in line:
                parts = line.split("-")
                if len(parts) >= 2:
                    return parts[1].strip()
    except Exception:
        pass
    return "Unknown / Not Installed"

def get_ios_device_info(driver: WebDriver) -> Dict[str, Any]:
    """Collect OS version, device name, model, and screen metrics.
    Args:
        driver (WebDriver): Appium driver instance.
    Returns:
        Dict[str, Any]: Device attributes dictionary.
    """
    caps = driver.capabilities or {}
    device_info = {
        "device_name": caps.get("deviceName", "iPhone 11 Pro"),
        "platform_version": caps.get("platformVersion", "iOS 17+"),
        "udid": caps.get("udid", caps.get("deviceUDID", "00008030-00064DC43EEA802E")),
    }
    try:
        window_size = driver.get_window_size()
        device_info["screen_resolution"] = f"{window_size.get('width')}x{window_size.get('height')}"
    except Exception:
        device_info["screen_resolution"] = "Unknown"
    return device_info

def get_wifi_information(driver: WebDriver) -> Dict[str, str]:
    """Accurately retrieve current connected Wi-Fi network configuration from iOS Settings.
    Strictly identifies the active network via the 'checkmark' icon and 'Selected' trait,
    excluding all other networks from 'Other Networks' or 'Public Networks'.
    """
    wifi_info = {
        "ssid": "Unknown",
        "ip_address": "Unknown",
        "router_gateway": "Unknown",
        "subnet_mask": "Unknown",
    }
    opened_settings = False
    try:
        logger.info("Opening iOS Settings to inspect Wi-Fi details...")
        driver.activate_app("com.apple.Preferences")
        opened_settings = True
        time.sleep(1.5)
        try:
            back_to_wifi_btns = driver.find_elements(
                AppiumBy.XPATH,
                '//XCUIElementTypeNavigationBar//XCUIElementTypeButton[@name="Wi-Fi" or @label="Wi-Fi"]'
            )
            if back_to_wifi_btns and back_to_wifi_btns[0].is_displayed():
                logger.info("Returning from previous Wi-Fi detail page back to Wi-Fi list...")
                back_to_wifi_btns[0].click()
                time.sleep(1.2)
        except Exception:
            pass
        on_wifi_page = False
        try:
            on_wifi_page = bool(
                driver.find_elements(AppiumBy.XPATH, '//XCUIElementTypeNavigationBar[@name="Wi-Fi"]')
            )
        except Exception:
            pass
        if not on_wifi_page:
            wifi_cells = driver.find_elements(
                AppiumBy.XPATH,
                '//XCUIElementTypeCell[@name="Wi-Fi" or .//XCUIElementTypeStaticText[@name="Wi-Fi"]]'
            )
            if wifi_cells:
                try:
                    wifi_cells[0].click()
                    time.sleep(2.0)
                except Exception as click_err:
                    logger.debug(f"Failed to click Wi-Fi cell in Settings: {click_err}")
        checkmark_xpath = (
            '//XCUIElementTypeCell['
            './/XCUIElementTypeImage[@name="checkmark" or contains(@name, "Checkmark") or contains(@name, "checkmark")]'
            ']'
        )
        selected_xpath = (
            '//XCUIElementTypeCell['
            '@selected="true" or @selected="1" or '
            'starts-with(@label, "Selected") or starts-with(@name, "Selected")'
            ']'
        )
        connected_cell = None
        entered_detail_page = False
        ignored_sections = ["other networks", "public networks", "my networks"]
        for attempt in range(5):
            try:
                if _is_in_wifi_detail_page(driver, wifi_info["ssid"]):
                    entered_detail_page = True
                    break
                connected_cell = None
                cells = driver.find_elements(AppiumBy.XPATH, checkmark_xpath)
                for c in cells:
                    lbl = (c.get_attribute("label") or c.get_attribute("name") or "").lower()
                    if not any(header in lbl for header in ignored_sections):
                        connected_cell = c
                        break
                if not connected_cell:
                    cells = driver.find_elements(AppiumBy.XPATH, selected_xpath)
                    for c in cells:
                        lbl = (c.get_attribute("label") or c.get_attribute("name") or "").lower()
                        if not any(header in lbl for header in ignored_sections):
                            connected_cell = c
                            break
                if not connected_cell:
                    all_cells = driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeCell")
                    for c in all_cells:
                        lbl = c.get_attribute("label") or c.get_attribute("name") or ""
                        if lbl in ["Wi-Fi"] or any(h in lbl.lower() for h in ignored_sections):
                            continue
                        if c.find_elements(AppiumBy.XPATH, './/XCUIElementTypeImage[contains(@name, "checkmark") or contains(@name, "Checkmark")]'):
                            connected_cell = c
                            break
                if not connected_cell:
                    time.sleep(0.8)
                    continue
                if wifi_info["ssid"] == "Unknown":
                    try:
                        texts = connected_cell.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText")
                        for st in texts:
                            val = (st.get_attribute("value") or st.get_attribute("name") or st.text or "").strip()
                            if (
                                    val
                                    and val not in ["Wi-Fi", "Connected", "Selected"]
                                    and not val.startswith("_Tt")
                                    and "SwiftUI" not in val
                            ):
                                wifi_info["ssid"] = val
                                logger.info(f"Extracted active Wi-Fi SSID from checkmark cell: '{wifi_info['ssid']}'")
                                break
                        if wifi_info["ssid"] == "Unknown":
                            cell_name = connected_cell.get_attribute("name") or connected_cell.get_attribute("label") or ""
                            if cell_name:
                                clean_name = cell_name.replace("Selected,", "").strip()
                                candidate = clean_name.split(",")[0].strip()
                                if candidate and not candidate.startswith("_Tt") and "SwiftUI" not in candidate:
                                    wifi_info["ssid"] = candidate
                                    logger.info(f"Extracted active Wi-Fi SSID by splitting cell name: '{wifi_info['ssid']}'")
                    except (StaleElementReferenceException, WebDriverException) as read_err:
                        logger.debug(f"[Attempt {attempt + 1}] Stale cell while reading text: {read_err}")
                info_btn = None
                try:
                    found_btns = connected_cell.find_elements(
                        AppiumBy.XPATH,
                        './/XCUIElementTypeButton[@name="More Info" or contains(@label, "More") or @name="更多資訊"]'
                    )
                    if found_btns:
                        info_btn = found_btns[-1]
                except Exception:
                    pass
                if not info_btn:
                    try:
                        cell_buttons = connected_cell.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeButton")
                        if cell_buttons:
                            info_btn = cell_buttons[-1]
                    except Exception:
                        pass
                if info_btn and attempt == 0:
                    logger.info(f"Clicking More Info button for verified '{wifi_info['ssid']}' (attempt {attempt + 1})...")
                    try:
                        info_btn.click()
                    except Exception:
                        btn_rect = info_btn.rect
                        driver.execute_script("mobile: tap", {
                            "x": int(btn_rect["x"] + btn_rect["width"] / 2),
                            "y": int(btn_rect["y"] + btn_rect["height"] / 2)
                        })
                elif info_btn:
                    btn_rect = info_btn.rect
                    tap_x = int(btn_rect["x"] + btn_rect["width"] / 2)
                    tap_y = int(btn_rect["y"] + btn_rect["height"] / 2)
                    logger.info(f"Coordinate-tapping More Info button at ({tap_x}, {tap_y}) (attempt {attempt + 1})...")
                    driver.execute_script("mobile: tap", {"x": tap_x, "y": tap_y})
                else:
                    rect = connected_cell.rect
                    target_x = int(rect["x"] + rect["width"] - 25)
                    target_y = int(rect["y"] + rect["height"] / 2)
                    logger.info(f"Coordinate-tapping right edge (i icon) at ({target_x}, {target_y}) (attempt {attempt + 1})...")
                    driver.execute_script("mobile: tap", {"x": target_x, "y": target_y})
                time.sleep(1.5)
                if _is_in_wifi_detail_page(driver, wifi_info["ssid"]):
                    logger.info(f"Confirmed inside More Info detail page for '{wifi_info['ssid']}'!")
                    entered_detail_page = True
                    break
                else:
                    logger.warning(
                        f"[Attempt {attempt + 1}/5] Clicked More Info, but still on Wi-Fi list page! "
                        f"Retrying tap on (i) button..."
                    )
                    try:
                        rect = connected_cell.rect
                        driver.execute_script("mobile: tap", {
                            "x": int(rect["x"] + rect["width"] - 25),
                            "y": int(rect["y"] + rect["height"] / 2)
                        })
                        time.sleep(1.2)
                        if _is_in_wifi_detail_page(driver, wifi_info["ssid"]):
                            logger.info(f"Confirmed inside More Info detail page after fallback tap!")
                            entered_detail_page = True
                            break
                    except Exception:
                        pass
            except (StaleElementReferenceException, WebDriverException) as stale_err:
                logger.debug(f"[Attempt {attempt + 1}] Wi-Fi list refreshed during inspection ({stale_err}). Retrying...")
                time.sleep(0.8)
        if not entered_detail_page and not _is_in_wifi_detail_page(driver, wifi_info["ssid"]):
            logger.warning(
                f"Could not enter More Info detail page for '{wifi_info['ssid']}' after 5 attempts. "
                f"Skipping IPv4 scroll to avoid scrolling on the Wi-Fi list."
            )
            return wifi_info
        logger.info("Swiping up to reveal IPv4 Address section...")
        for _ in range(4):
            try:
                subnets = driver.find_elements(
                    AppiumBy.XPATH,
                    '//XCUIElementTypeStaticText[@name="Subnet Mask" or @name="Subnet" or @name="Mask网掩码"]'
                )
                if subnets and subnets[0].is_displayed():
                    break
            except Exception:
                pass
            _swipe_up_to_scroll_down(driver)
            time.sleep(0.6)

        def extract_cell_value(xpath_query: str, pattern: str, exclude_words: list) -> str:
            try:
                cells = driver.find_elements(AppiumBy.XPATH, xpath_query)
                for cell in cells:
                    try:
                        texts = cell.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText")
                        for t in texts:
                            val = (t.text or t.get_attribute("value") or t.get_attribute("name") or "").strip()
                            if not any(w in val for w in exclude_words) and re.match(pattern, val):
                                return val
                    except (StaleElementReferenceException, WebDriverException):
                        continue
            except Exception:
                pass
            return "Unknown"
        ip_cell_xpath = '//XCUIElementTypeCell[.//XCUIElementTypeStaticText[@name="IP Address" or @name="IP" or @name="Address"]]'
        ip_val = extract_cell_value(ip_cell_xpath, r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ["IP Address", "IP", "Address址"])
        if ip_val != "Unknown":
            wifi_info["ip_address"] = ip_val
        subnet_cell_xpath = '//XCUIElementTypeCell[.//XCUIElementTypeStaticText[@name="Subnet Mask" or @name="Subnet網路遮罩" or @name="Mask"]]'
        subnet_val = extract_cell_value(subnet_cell_xpath, r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ["Subnet", "遮罩", "掩码"])
        if subnet_val != "Unknown":
            wifi_info["subnet_mask"] = subnet_val
        router_cell_xpath = '//XCUIElementTypeCell[.//XCUIElementTypeStaticText[@name="Router"]]'
        router_val = extract_cell_value(router_cell_xpath, r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ["Router"])
        if router_val != "Unknown":
            wifi_info["router_gateway"] = router_val
        logger.info(f"Successfully collected Wi-Fi information: {wifi_info}")
    except Exception as e:
        logger.warning(f"Failed to retrieve Wi-Fi details from Settings: {e}. Using fallback values.")
    finally:
        if opened_settings:
            try:
                back_btns = driver.find_elements(
                    AppiumBy.XPATH,
                    '//XCUIElementTypeNavigationBar//XCUIElementTypeButton[@name="Wi-Fi" or @label="Wi-Fi"]'
                )
                if back_btns and back_btns[0].is_displayed():
                    back_btns[0].click()
                    time.sleep(0.5)
            except Exception:
                pass
            try:
                target_bundle = getattr(constants, "GHA_BUNDLE_ID", "com.google.Chromecast.enterprise")
                logger.info(f"Switching back to target app: {target_bundle}...")
                driver.activate_app(target_bundle)
                time.sleep(1.0)
            except Exception as app_err:
                logger.debug(f"Failed to switch back to {target_bundle}: {app_err}")
    return wifi_info

def log_all_version_information(driver: WebDriver) -> Dict[str, Any]:
    """Collect and log all system, app, and network version details.
    Args:
        driver (WebDriver): Appium driver instance.
    Returns:
        Dict[str, Any]: Consolidated environment information dictionary.
    """
    logger.info("=" * 60)
    logger.info(" [ENV INFO] Collecting Environment & Version Information")
    logger.info("=" * 60)
    gha_version = get_app_version(driver, constants.GHA_BUNDLE_ID)
    sample_version = get_app_version(driver, getattr(constants, "iGHP_SAMPLE_APP_BUNDLE_ID", ""))
    device_info = get_ios_device_info(driver)
    wifi_info = get_wifi_information(driver)
    logger.info(f"  * Google Home App Version : {gha_version}")
    logger.info(f"  * Sample App Version      : {sample_version}")
    logger.info(f"  * iOS Device Name         : {device_info.get('device_name')}")
    logger.info(f"  * iOS Platform Version    : {device_info.get('platform_version')}")
    logger.info(f"  * Device UDID             : {device_info.get('udid')}")
    logger.info(f"  * Screen Size             : {device_info.get('screen_resolution')}")
    logger.info(f"  * Connected Wi-Fi SSID    : {wifi_info.get('ssid')}")
    logger.info(f"  * Device IP Address       : {wifi_info.get('ip_address')}")
    logger.info(f"  * Router Gateway          : {wifi_info.get('router_gateway')}")
    logger.info(f"  * Subnet Mask             : {wifi_info.get('subnet_mask')}")
    logger.info("=" * 60)
    return {
        "gha_version": gha_version,
        "sample_version": sample_version,
        "device_info": device_info,
        "wifi_info": wifi_info,
    }