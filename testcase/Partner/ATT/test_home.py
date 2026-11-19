"""Test cases for AT&T Connected Life (`att`) partner iOS app."""

import traceback
from typing import List, Optional
from common.base_test import BaseTestCase
from page_object.Partner.ATT import att_session
from utils import logging_utils

logger = logging_utils.get_logger(__name__, "testcase_att")


def _extract_att_page_stage(exc: Optional[Exception]) -> str:
    """Extract failing page_object method name (uppercase) from an exception traceback."""
    if not exc or not hasattr(exc, "__traceback__"):
        return "UNKNOWN"
    for frame in reversed(traceback.extract_tb(exc.__traceback__)):
        if "page_object" in frame.filename:
            if frame.name not in ("find_element", "find_elements", "click", "send_keys",
                                  "__getattr__"):
                return frame.name.upper()
    return "UNKNOWN"


class TestATTHome(BaseTestCase):
    """End-to-end AT&T Connected Life room, camera live stream, and GHP Google Account check."""

    def test_verify_camera_live_and_google_account(self) -> None:
        """Open room, refresh, log Online/Offline, verify 5~10s Live stream, check GHP Google Account.

        If Camera Live Stream fails, still navigate back to Home/Devices and verify the
        GHP Google Account state:
        - Live fail + Account fail -> combined Failure Stage and Error Message with both failures.
        - Live fail + Account pass -> keep only the single Live Stream Failure Stage and Error Message.
        """
        logger.info(
            f"Start AT&T Connected Life test case: device='{self.device_name}', room='{self.room_name}'"
        )
        assert att_session.ATTSession.prepare_app_for_iteration(self), (
            "Failed to launch/prepare AT&T Connected Life app"
        )
        # 1. Click room -> refresh room page -> confirm camera device exists
        att_session.ATTDevicesPage.open_room(self, room_name=self.room_name)
        att_session.ATTRoomPage.refresh_room_page(self)
        # 2. Check device Online/Offline status (continues to step 3 regardless of Online/Offline)
        att_session.ATTRoomPage.check_device_presence_and_status(
            self, device_name=self.device_name, room_name=self.room_name
        )
        # 3. Regardless of Online/Offline, enter Live Stream -> wait for top-left 'Live' -> verify 5~10s
        live_exc: Optional[Exception] = None
        live_stage: str = ""
        try:
            att_session.ATTRoomPage.enter_camera_live_stream(
                self, device_name=self.device_name, room_name=self.room_name
            )
            att_session.ATTCameraLivePage.wait_and_verify_live_stream(self,
                                                                      device_name=self.device_name, wait_live_timeout_s=60.0)
        except Exception as exc:
            live_exc = exc
            live_stage = _extract_att_page_stage(exc)
            logger.warning(
                f"[ATT Home] Camera Live Stream failed at '{live_stage}' ({exc}); "
                "continuing to verify GHP Google Account status..."
            )

        # 4. Return to Home page by clicking Back twice (Live -> Room -> Devices), with Devices recovery fallback
        try:
            devices_page = att_session.ATTDevicesPage._resolve_page(self)
            room_page = att_session.ATTRoomPage._resolve_page(self)
            if not devices_page.is_on_devices_page():
                if live_exc is not None and not room_page._is_live_stream_page_open(
                        self.device_name or "", self.room_name or ""
                ):
                    att_session.ATTRoomPage.click_back_to_devices(self)
                else:
                    att_session.ATTCameraLivePage.click_back_to_room(self, room_name=self.room_name)
                    att_session.ATTRoomPage.click_back_to_devices(self)
        except Exception as nav_err:
            if live_exc is None:
                raise
            logger.warning(
                f"[ATT Home] Back navigation failed after Live failure ({nav_err}); "
                "recovering via go_to_devices_tab..."
            )
            att_session.ATTDevicesPage.go_to_devices_tab(self)
        account_exc: Optional[Exception] = None
        account_stage: str = ""
        try:
            att_session.ATTDevicesPage.click_top_left_setting_button(self)
            att_session.ATTAccountPage.verify_google_account_signed_in(self)
            att_session.ATTAccountPage.close_account_page(self)
        except Exception as exc:
            if live_exc is None:
                raise
            account_exc = exc
            account_stage = _extract_att_page_stage(exc)
            try:
                att_session.ATTAccountPage.close_account_page(self)
            except Exception:
                pass

        if live_exc is not None and account_exc is not None:
            stages: List[str] = []
            for st in (live_stage, account_stage):
                if st and st != "UNKNOWN" and st not in stages:
                    stages.append(st)
            combined = AssertionError(
                f"[Live Stream] {live_exc} | [Google Account] {account_exc}"
            )
            setattr(combined, "failure_stage", " | ".join(stages) if stages else "UNKNOWN")
            raise combined from live_exc

        if live_exc is not None:
            raise live_exc
