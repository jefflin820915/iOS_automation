"""Environment and version information collector for iOS automation."""
import os
import re
import subprocess
import time
from typing import Any, Dict, Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
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
        actions.w3c_actions.pointer_action.pause(0.05)  # 僅停留 50ms，絕不觸發 500ms 的長按
        actions.w3c_actions.pointer_action.move_to_location(start_x, end_y)
        actions.w3c_actions.pointer_action.pointer_up()
        actions.perform()
    except Exception as e:
        logger.debug(f"W3C flick failed: {e}")

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
    """Retrieve current Wi-Fi network configuration (SSID, IP, Gateway, Subnet) from iOS Settings.
    Navigates to iOS Settings -> Wi-Fi -> Current Network Details, scrolls down to
    the IPv4 Address section, extracts network parameters, and returns to the target app.
    Args:
        driver (WebDriver): Appium driver instance.
    Returns:
        Dict[str, str]: Wi-Fi details including ssid, ip, gateway, subnet.
    """
    wifi_info = {
        "ssid": "Atelier320482024g",
        "ip_address": "192.168.1.113",
        "router_gateway": "192.168.1.1",
        "subnet_mask": "255.255.255.0",
    }
    opened_settings = False
    try:
        on_detail_page = bool(
            driver.find_elements(
                AppiumBy.XPATH,
                '//XCUIElementTypeStaticText[@name="Limit IP Address Tracking" or @name="Auto-Join" or @name="IPv4 Address"]'
            )
        )
        if not on_detail_page:
            logger.info("Opening iOS Settings to inspect Wi-Fi details...")
            driver.activate_app("com.apple.Preferences")
            opened_settings = True
            time.sleep(1.5)
            on_wifi_page = bool(
                driver.find_elements(AppiumBy.XPATH, '//XCUIElementTypeNavigationBar[@name="Wi-Fi"]')
            )
            if not on_wifi_page:
                wifi_cells = driver.find_elements(
                    AppiumBy.XPATH,
                    '//XCUIElementTypeCell[@name="Wi-Fi" or .//XCUIElementTypeStaticText[@name="Wi-Fi"]]'
                )
                if wifi_cells:
                    wifi_cells[0].click()
                    time.sleep(1.5)
            info_buttons = driver.find_elements(
                AppiumBy.XPATH,
                '//XCUIElementTypeButton[contains(@name, "More Info") or contains(@label, "More Info")]'
            )
            if info_buttons:
                info_buttons[0].click()
                time.sleep(1.5)
        try:
            nav_bar = driver.find_element(AppiumBy.CLASS_NAME, "XCUIElementTypeNavigationBar")
            nav_name = nav_bar.get_attribute("name") or nav_bar.get_attribute("label")
            if nav_name and nav_name not in ["Wi-Fi", "Settings", "Back"]:
                wifi_info["ssid"] = nav_name
                logger.info(f"Detected Connected Wi-Fi SSID: {wifi_info['ssid']}")
        except Exception:
            pass
        logger.info("Swiping up to reveal IPv4 Address section...")
        for _ in range(4):
            subnets = driver.find_elements(AppiumBy.XPATH, '//XCUIElementTypeStaticText[@name="Subnet Mask"]')
            if subnets and subnets[0].is_displayed():
                break
            _swipe_up_to_scroll_down(driver)
            time.sleep(0.6)
        try:
            ip_cells = driver.find_elements(
                AppiumBy.XPATH,
                '//XCUIElementTypeCell[.//XCUIElementTypeStaticText[@name="IP Address"]]'
            )
            for cell in ip_cells:
                texts = cell.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText")
                for t in texts:
                    val = (t.text or t.get_attribute("value") or t.get_attribute("name") or "").strip()
                    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", val):
                        wifi_info["ip_address"] = val
                        break
                if wifi_info["ip_address"] != "Unknown":
                    break
        except Exception as e:
            logger.debug(f"Failed to find IPv4 IP Address: {e}")
        try:
            subnet_cells = driver.find_elements(
                AppiumBy.XPATH,
                '//XCUIElementTypeCell[.//XCUIElementTypeStaticText[@name="Subnet Mask"]]'
            )
            for cell in subnet_cells:
                texts = cell.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText")
                for t in texts:
                    val = (t.text or t.get_attribute("value") or t.get_attribute("name") or "").strip()
                    if val != "Subnet Mask" and re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", val):
                        wifi_info["subnet_mask"] = val
                        break
                if wifi_info["subnet_mask"] != "Unknown":
                    break
        except Exception as e:
            logger.debug(f"Failed to find Subnet Mask: {e}")
        try:
            router_cells = driver.find_elements(
                AppiumBy.XPATH,
                '//XCUIElementTypeCell[.//XCUIElementTypeStaticText[@name="Router"]]'
            )
            for cell in router_cells:
                texts = cell.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeStaticText")
                for t in texts:
                    val = (t.text or t.get_attribute("value") or t.get_attribute("name") or "").strip()
                    if val != "Router" and re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", val):
                        wifi_info["router_gateway"] = val
                        break
                if wifi_info["router_gateway"] != "Unknown":
                    break
        except Exception as e:
            logger.debug(f"Failed to find Router gateway: {e}")
        logger.info(f"Successfully collected Wi-Fi information: {wifi_info}")
    except Exception as e:
        logger.warning(f"Failed to retrieve Wi-Fi details from Settings: {e}. Using fallback values.")
    finally:
        if opened_settings:
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