"""Test cases for AT&T Connected Life (`att`) partner iOS app."""
from common.base_test import BaseTestCase
from page_object.Partner.ATT import att_session
from utils import logging_utils

logger = logging_utils.get_logger(__name__, "testcase_att")


class TestATTHome(BaseTestCase):
    """End-to-end AT&T Connected Life room, camera live stream, and GHP Google Account check."""

    def test_verify_camera_live_and_google_account(self) -> None:
        """Open room, refresh, log Online/Offline, verify 5~10s Live stream, check GHP Google Account."""
        logger.info(
            f"Start AT&T Connected Life test case: device='{self.device_name}', room='{self.room_name}'"
        )
        assert att_session.ATTSession.prepare_app_for_iteration(self), (
            "Failed to launch/prepare AT&T Connected Life app"
        )
        att_session.ATTDevicesPage.open_room(self, room_name=self.room_name)
        att_session.ATTRoomPage.refresh_room_page(self)
        att_session.ATTRoomPage.check_device_presence_and_status(
            self, device_name=self.device_name, room_name=self.room_name
        )
        att_session.ATTRoomPage.enter_camera_live_stream(
            self, device_name=self.device_name, room_name=self.room_name
        )
        att_session.ATTCameraLivePage.wait_and_verify_live_stream(self,
                                                                  device_name=self.device_name)
        att_session.ATTCameraLivePage.click_back_to_room(self, room_name=self.room_name)
        att_session.ATTRoomPage.click_back_to_devices(self)
        att_session.ATTDevicesPage.click_top_left_setting_button(self)
        att_session.ATTAccountPage.verify_google_account_signed_in(self)
        att_session.ATTAccountPage.close_account_page(self)
