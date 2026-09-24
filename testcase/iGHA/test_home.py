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
        assert gha_session.GHASession.stop_gha(self)
        time.sleep(10)
