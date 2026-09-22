"""Session Page Object managing iGHA lifecycle and aggregating all sub-page objects."""
import time
import tomllib
from typing import Optional, Any
from appium.webdriver.webdriver import WebDriver
from selenium.common.exceptions import WebDriverException, StaleElementReferenceException
from common import constants
from common.base_page import BasePage
from page_object.iGHA.gha_home_page import GHAHomePage
from page_object.iGHA.gha_account_picker import GHAAccountPicker
from page_object.iGHA.gha_device_page import GHADevicePage
from page_object.iGHA.gha_setup_device_page import GHASetUpDevicePage
from page_object.iGHA.gha_add_page import GHAAddPage
from page_object.iGHA.gha_add_device_page import GHAAddDevicePage
from page_object.iGHA.gha_enter_pairing_code_page import GHAEnterPairingCodePage
from page_object.iGHA.gha_privacy_guidelines_page import GHAPrivacyGuidelinesPage
from page_object.iGHA.gha_help_improve_camera_device_page import GHAHelpImproveCameraDevicePage
from page_object.iGHA.gha_watch_setup_video_page import GHAWatchSetupVideoPage
from page_object.iGHA.gha_connect_device_to_google_account_page import GHAConnectDeviceToGoogleAccountPage
from page_object.iGHA.gha_commission_flow import GHACommissioningPageObject
from page_object.iGHA.gha_where_is_this_device_page import GHAWhereIsThisDevicePage
from page_object.iGHA.gha_device_connected_page import GHADeviceConnectedPage
from page_object.iGHA.gha_camera_activated_page import GHACameraActivatedPage
from page_object.iGHA.gha_you_should_now_see_live_video_page import GHAYouShouldNowSeeLiveVideoPage
from page_object.iGHA.gha_choose_whether_you_want_to_turn_on_video_history import (
    GHAChooseWhetherYouWantToTurnOnVideoPage,
    OOBEInternalErrorException,
)
from page_object.iGHA.gha_adjust_your_mic_settings import GHAAdjustYourMicSettingsPage
from page_object.iGHA.gha_stay_in_the_know_page import GHAStayInTheKnowPage
from page_object.iGHA.gha_your_camera_device_is_ready_page import GHAYourCameraDeviceIsReadyPage
from page_object.iGHA.gha_setting_page import GHASettingsPage
from page_object.iGHA.gha_tab_page import GHATabPage
from page_object.iGHA.gha_device_setting_page import GHADeviceSettingPage
from page_object.iGHA.gha_camera_live_page import GHACameraLivePage
from page_object.iGHA.gha_single_device_found_page import GHASingleDeviceFoundPage
from utils import logging_utils
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class GHASession:
    """Central entry point managing iGHA application lifecycle and sub-page objects."""

    def __init__(self, driver: WebDriver) -> None:
        """Initialize GHASession with Appium driver and instantiate all iGHA page objects.
        Args:
            driver (WebDriver): The active Appium WebDriver instance.
        """
        self.driver = driver
        self.timeout = getattr(constants, "DEFAULT_TIMEOUT_SECONDS", 15.0)
        self._logger = logging_utils.get_logger(__name__, "gha_session")
        page_classes = [
            GHAHomePage,
            GHAAccountPicker,
            GHADevicePage,
            GHASetUpDevicePage,
            GHAAddPage,
            GHAAddDevicePage,
            GHAEnterPairingCodePage,
            GHAPrivacyGuidelinesPage,
            GHAHelpImproveCameraDevicePage,
            GHAWatchSetupVideoPage,
            GHAConnectDeviceToGoogleAccountPage,
            GHACommissioningPageObject,
            GHAWhereIsThisDevicePage,
            GHACameraActivatedPage,
            GHAYouShouldNowSeeLiveVideoPage,
            GHAChooseWhetherYouWantToTurnOnVideoPage,
            GHAAdjustYourMicSettingsPage,
            GHAStayInTheKnowPage,
            GHAYourCameraDeviceIsReadyPage,
            GHASettingsPage,
            GHATabPage,
            GHADeviceSettingPage,
            GHACameraLivePage
        ]
        for cls in page_classes:
            attr_name = cls.__name__.lower()
            setattr(self, attr_name, cls(driver))

    def __getattr__(self, name: str) -> Any:
        """Automatically delegate method lookup across all registered pages."""
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        for page in self.__dict__.values():
            if hasattr(page, name):
                return getattr(page, name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def _get_device_grid_view(self):
        """Locates the main device grid collection view on the GHA home page."""
        return self.driver.find_element(
            AppiumBy.ACCESSIBILITY_ID, "deviceTileGridCollectionView"
        )

    def _pull_down_to_refresh(self, element) -> None:
        """Performs a downward drag gesture on the element to trigger iOS pull-to-refresh."""
        rect = element.rect
        center_x = rect["x"] + rect["width"] // 2
        start_y = rect["y"] + int(rect["height"] * 0.15)
        end_y = rect["y"] + int(rect["height"] * 0.65)
        actions = ActionChains(self.driver)
        actions.w3c_actions = ActionBuilder(
            self.driver, mouse=PointerInput(interaction.POINTER_TOUCH, "touch")
        )
        actions.w3c_actions.pointer_action.move_to_location(center_x, start_y)
        actions.w3c_actions.pointer_action.pointer_down()
        actions.w3c_actions.pointer_action.pause(0.3)
        actions.w3c_actions.pointer_action.move_to_location(center_x, end_y)
        actions.w3c_actions.pointer_action.pause(0.5)
        actions.w3c_actions.pointer_action.pointer_up()
        actions.perform()

    def _dismiss_setup_new_devices_sheet(self, timeout: float = 10.0) -> bool:
        """Check for and dismiss the 'Set up new devices?' bottom sheet if it appears after launch.
        Args:
            timeout (float): Max time in seconds to poll for the bottom sheet (defaults to 5.0s).
        Returns:
            bool: True if the sheet was detected and dismissed, False otherwise.
        """
        self._logger.info(f"Checking for 'Set up new devices?' bottom sheet (polling up to {timeout}s)...")
        start_time = time.time()
        not_now_locators = [
            (AppiumBy.XPATH, '//XCUIElementTypeButton[@name="actionBarSecondaryButton" or @name="Not now" or @label="Not now"]'),
            (AppiumBy.XPATH, '//XCUIElementTypeStaticText[@name="Not now" or @label="Not now"]'),
            (AppiumBy.ACCESSIBILITY_ID, "actionBarSecondaryButton"),
            (AppiumBy.ACCESSIBILITY_ID, "Not now")
        ]
        while time.time() - start_time < timeout:
            try:
                self.driver.implicitly_wait(0)
                for by, loc in not_now_locators:
                    btns = self.driver.find_elements(by, loc)
                    for btn in btns:
                        try:
                            if btn.is_displayed():
                                self._logger.info("Detected 'Set up new devices?' prompt. Clicking 'Not now'...")
                                btn.click()
                                time.sleep(1.0)
                                return True
                        except (StaleElementReferenceException, WebDriverException):
                            continue
            except Exception:
                pass
            finally:
                self.driver.implicitly_wait(getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0))
            time.sleep(0.5)
        self._logger.info("No 'Set up new devices?' bottom sheet detected. Continuing.")
        return False

    def _emergency_recover_and_remove_device(self) -> None:
        """Restarts GHA and removes the partially paired device to restore a clean uncommissioned state."""
        self._logger.warning("[Emergency Teardown] Initiating GHA restart to reset navigation state...")
        try:
            self.stop_gha()
            time.sleep(2.0)
            self.start_gha()
            time.sleep(5.0)
            self._logger.info("[Emergency Teardown] Navigating to Settings to remove device...")
            self.handle_remove_device()
            self._logger.info("[Emergency Teardown] Device successfully removed during emergency cleanup.")
        except Exception as cleanup_err:
            self._logger.error(f"[Emergency Teardown] Failed to remove device during recovery: {cleanup_err}")

    def refresh_gha_devices(self, timeout: float = 5.0) -> None:
        """Refresh all devices in the Google Home App (iOS).
        Performs a pull-to-refresh on deviceTileGridCollectionView and waits
        for the iOS activity spinner to disappear.
        Args:
            timeout: The maximum time in seconds to wait for refresh to complete.
                     Defaults to 5 seconds.
        """
        try:
            time.sleep(3)
            grid_view = self._get_device_grid_view()
            self._pull_down_to_refresh(grid_view)
            time.sleep(0.5)
            spinner_locator = (
                AppiumBy.IOS_CLASS_CHAIN,
                "**/XCUIElementTypeActivityIndicator",
            )
            WebDriverWait(self.driver, timeout).until(
                EC.invisibility_of_element_located(spinner_locator)
            )
            self._logger.info("GHA has been refreshed.")
        except TimeoutException:
            self._logger.critical(f"Refresh too long..., timeout: {timeout}")
        except Exception as e:
            self._logger.error(f"Failed to refresh GHA devices: {e}")

    def _is_gha_running(self) -> bool:
        """Check if GHA is currently running in the active foreground."""
        try:
            return self.driver.query_app_state(constants.GHA_BUNDLE_ID) == constants.APP_STATE_FOREGROUND
        except WebDriverException as e:
            self._logger.error(f"Failed to query GHA app state: {e}")
            return False

    def stop_gha(self) -> bool:
        """Terminate the GHA application."""
        try:
            app_state = self.driver.query_app_state(constants.GHA_BUNDLE_ID)
            if app_state != constants.APP_STATE_NOT_RUNNING:
                self.driver.terminate_app(constants.GHA_BUNDLE_ID)
                self._logger.info("GHA stopped successfully.")
            else:
                self._logger.info("GHA is not running.")
            return True
        except WebDriverException as e:
            self._logger.error(f"Failed to stop GHA: {e}")
            return False

    def start_gha(self, timeout: float = 10.0) -> bool:
        """Start GHA and ensure it is running in the active foreground."""
        if self._is_gha_running():
            self._logger.info("GHA is already running in foreground.")
            return True
        self._logger.info("Starting Google Home App on iOS...")
        try:
            self.driver.activate_app(constants.GHA_BUNDLE_ID)
            self._dismiss_setup_new_devices_sheet()
        except WebDriverException as e:
            self._logger.error(f"Failed to activate GHA: {e}")
            return False
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self._is_gha_running():
                self._logger.info("GHA launched successfully in foreground.")
                return True
            try:
                self.driver.activate_app(constants.GHA_BUNDLE_ID)
            except WebDriverException:
                pass
        self._logger.error(f"Timed out after {timeout}s waiting for GHA.")
        return False

    def handle_device_selection_steps(self) -> bool:
        """Proceed to enter pairing code screen and input manual pairing code."""
        target_name = getattr(self, "device_name", "")
        self._logger.info(f"Checking for 'Single Device Found' screen for '{target_name}'...")
        try:
            GHASingleDeviceFoundPage.handle_if_present(self, target_device_name=target_name)
        except Exception as check_err:
            self._logger.warning(f"Single device check exception (ignored): {check_err}")
        GHAAddDevicePage.click_use_pairing_code_btn(self)
        GHAEnterPairingCodePage.enter_pairing_code(self, pairing_code=self.pairing_code)

    def pair_device_with_pairing_code(self) -> None:
        """Proceed to enter pairing code screen and input manual pairing code."""
        GHAAddDevicePage.click_use_pairing_code_btn(self)
        GHAEnterPairingCodePage.enter_pairing_code(self, pairing_code=self.pairing_code)

    def handle_setup_requirement_pages(self) -> None:
        """Handle privacy guidelines and product improvement consent screens."""
        GHAPrivacyGuidelinesPage.handle_privacy_guidelines_page_process(self)
        GHAHelpImproveCameraDevicePage.click_yes_i_m_in_btn(self)

    def handle_pairing_until_device_connected(self) -> bool:
        """Commission the Matter device through Apple sheets and GHA setup steps until connected."""
        device_name = getattr(self, "device_name", None)
        room_name = getattr(self, "room_name", "Attic")

        GHACommissioningPageObject(self.driver).complete_commissioning_and_pairing_flow(
            device_name=device_name, room_name=room_name
        )
        try:
            GHAChooseWhetherYouWantToTurnOnVideoPage.enable_video_history_and_proceed(self)
            GHAAdjustYourMicSettingsPage.enable_all_mic_settings_and_proceed(self)
            GHAStayInTheKnowPage.handle_stay_in_the_know_page_process(self)
            GHAYourCameraDeviceIsReadyPage.click_done_btn(self)
            return True
        except OOBEInternalErrorException as e:
            self._logger.error(f"[OOBE Failure] Intercepted internal error: {e}")
            self._emergency_recover_and_remove_device()
            raise AssertionError(f"Commissioning OOBE failed due to internal error: {e}") from e

    def handle_verify_camera_live_stream_and_remove(self):
        try:
            GHADevicePage.is_device_exist_device_page(self, device_name=self.device_name)
            GHADevicePage.enter_device_page(self, device_name=self.device_name)
            GHACameraLivePage.verify_camera_live_stream(self)
        finally:
            self.handle_remove_device()

    def handle_remove_device(self) -> None:
        """Navigate to Settings and completely remove/unpair the camera device."""
        self._logger.info("Start test case: remove device")
        GHATabPage.enter_home_settings_page(self)
        GHASettingsPage.open_device_settings(self, device_name=self.device_name)
        GHADeviceSettingPage.get_device_information(self)
        GHADeviceSettingPage.click_remove_device_btn(self)