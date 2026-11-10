"""Test cases for iGHP (Google Home Platform iOS Sample App) mirroring TestGHAHome."""

import time
from common import constants
from common.base_test import BaseTestCase
from page_object.iGHP import ghp_session
from utils import logging_utils

logger = logging_utils.get_logger(__name__, "testcase_ighp")


class TestGHPHome(BaseTestCase):
    """End-to-end camera Matter commissioning, OOBE OTA, and Live Stream test suite for iGHP."""

    def test_add_camera_device_and_oobe(self) -> None:
        """Commission camera via 3P/Google Fabric + Setup Code, verify OOBE OTA & Live Stream, then reset."""
        logger.info(
            "Start iGHP test case: add camera device, OOBE OTA, and live stream verification")
        assert ghp_session.GHPSession.stop_ghp(self)
        assert ghp_session.GHPSession.start_ghp(self), "Failed to start iGHP Sample App"
        tab_devices = getattr(getattr(constants, "TAB", None), "DEVICES", "Devices")
        ghp_session.GHPDevicePage.go_to_tab(self, tab_devices)
        ghp_session.GHPSession.refresh_ghp_devices(self)
        ghp_session.GHPSession.click_add_devices_button(self)
        ghp_session.GHPSession.pair_device_with_pairing_code(self)
        ghp_session.GHPSession.handle_pairing_until_device_connected(self)
        ghp_session.GHPSession.handle_verify_camera_live_stream_and_remove(self)
        assert ghp_session.GHPSession.stop_ghp(self)
        time.sleep(5)
