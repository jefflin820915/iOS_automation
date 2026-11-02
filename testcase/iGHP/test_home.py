"""Test cases for iGHA (Google Home App) on iOS using Class-based structure."""
import time

from common.base_test import BaseTestCase
from page_object.iGHP import ghp_session
from utils import logging_utils

logger = logging_utils.get_logger(__name__, "testcase_igha")


class TestGHPHome(BaseTestCase):
    def test_open_google_home_enterprise(self):
        """Verify Google Home Enterprise App can be opened and run in the foreground."""
        logger.info("Start test case: test_open_google_home_enterprise")

        assert ghp_session.GHPSession.start_ghp(self), "Failed to start Google Home App"
        