"""Test cases for iGHP (Google Home Platform iOS Sample App) mirroring TestGHAHome."""

import time
from common import constants
from common.base_page import BasePage
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
        sess = ghp_session.GHPSession._resolve_session(self)
        sess._device_reset_done_in_run = False
        sess._device_removed_in_emergency = False
        sess._ghp_commissioning_reached = False
        test_failed = False
        try:
            assert ghp_session.GHPSession.stop_ghp(self)
            assert ghp_session.GHPSession.start_ghp(self), "Failed to start iGHP Sample App"
            tab_devices = getattr(getattr(constants, "TAB", None), "DEVICES", "Devices")
            ghp_session.GHPDevicePage.go_to_tab(self, tab_devices)
            ghp_session.GHPSession.refresh_ghp_devices(self)
            ghp_session.GHPSession.cleanup_leftover_device_if_present(self)
            ghp_session.GHPSession.click_add_devices_button(self)
            ghp_session.GHPSession.pair_device_with_pairing_code(self)
            sess._ghp_commissioning_reached = True
            ghp_session.GHPSession.handle_pairing_until_device_connected(self)
            ghp_session.GHPSession.handle_verify_camera_live_stream_and_remove(self)
            assert ghp_session.GHPSession.stop_ghp(self)
            time.sleep(5)
        except Exception as exc:
            test_failed = True
            if getattr(self, "driver", None) is not None:
                try:
                    BasePage.capture_failure_screenshot(
                        self.driver, reason=f"iGHP failure: {exc}", force=False, lock=True
                    )
                except Exception:
                    pass
            raise
        finally:
            if test_failed and not getattr(sess, "_device_reset_done_in_run", False):
                if getattr(sess, "_ghp_commissioning_reached", False) and not getattr(
                        sess, "_device_removed_in_emergency", False
                ):
                    logger.warning(
                        "[Post-Test Cleanup] Checking iGHP for leftover paired device before hardware reset..."
                    )
                    try:
                        ghp_session.GHPSession._emergency_recover_and_remove_device(self,
                                                                                    attempts=1)
                    except Exception as rem_err:
                        logger.warning(
                            f"[Post-Test Cleanup] Emergency UI removal warning: {rem_err}")
                logger.warning(
                    "[Post-Test Cleanup] iGHP test failed before live/remove stage; "
                    "running Smart Plug power-cycle + ADB factory reset..."
                )
                try:
                    ghp_session.GHPSession.reset_target_device(self, reason="test failure cleanup")
                except Exception as reset_err:
                    logger.error(f"[Post-Test Cleanup] Failure-path reset error: {reset_err}")
                try:
                    ghp_session.GHPSession.stop_ghp(self)
                except Exception:
                    pass
