"""Test cases for iGHA (Google Home App) on iOS using Class-based structure."""
import time
from common import constants
from common.base_test import BaseTestCase
from page_object.iGHA import gha_session
from utils import logging_utils
from appium.webdriver.common.appiumby import AppiumBy


logger = logging_utils.get_logger(__name__, "testcase_igha")


class TestGHAHome(BaseTestCase):
    def test_add_camera_device_and_oobe(self):
        """Verify Google Home Enterprise App can be opened and run in the foreground."""
        logger.info("Start test case: add camera device and oobe")
        assert gha_session.GHASession.stop_gha(self)
        assert gha_session.GHASession.start_gha(self), "Failed to start Google Home App"
        gha_session.GHATabPage.go_to_tab(self, constants.TAB.DEVICES)
        gha_session.GHASession.refresh_gha_devices(self)
        gha_session.GHAHomePage.click_add_devices_button(self)
        gha_session.GHASession.handle_device_selection_steps(self)
        gha_session.GHASession.pair_device_with_pairing_code(self)
        gha_session.GHASession.handle_setup_requirement_pages(self)
        gha_session.GHASession.handle_pairing_until_device_connected(self)
        gha_session.GHASession.handle_verify_camera_live_stream_and_remove(self)
        gha_session.GHASession.refresh_gha_devices(self)
        assert gha_session.GHASession.stop_gha(self)
        time.sleep(15)


        #self.driver.find_element(by=AppiumBy.ACCESSIBILITY_ID, value=constants.GHA_EXPAND_ACCOUNT_LIST).click()
        #gha_session.GHAAccountPicker.select_or_add_account(self,"jess.for.att.ghp@gmail.com")








    # logger.info("Test passed: Google Home App is running in the foreground")
    # def test_verify_ios_get_started_page(driver):
    #     """Verify opening Google Home iOS Get Started page using Safari."""
    #     logger.info("Start test case: test_verify_ios_get_started_page")
    #     # Launch Safari in the context of native driver session
    #     driver.activate_app(constants.SAFARI_BUNDLE_ID)
    #     driver.get(constants.GHP_DEV_SITE)
    #     time.sleep(5)
    #     driver.find_element(by=AppiumBy.ACCESSIBILITY_ID, value="Get started with the Google Home APIs Copy link to this section: Get started with the Google Home APIs, article").is_displayed()
    #     logger.info("Safari has been activated")