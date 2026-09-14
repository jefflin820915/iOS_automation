"""Test cases for iGHA (Google Home App) on iOS using Class-based structure."""
import time

from common.base_test import BaseTestCase
from page_object.iGHA import gha_session
from utils import logging_utils

logger = logging_utils.get_logger(__name__, "testcase_igha")


class TestiGHPHome(BaseTestCase):
    def test_open_google_home_enterprise(self):
        """Verify Google Home Enterprise App can be opened and run in the foreground."""
        logger.info("Start test case: test_open_google_home_enterprise")

        assert gha_session.GHASession.start_gha(self), "Failed to start Google Home App"


        #driver.find_element(by=AppiumBy.ACCESSIBILITY_ID, value=constants.GHA_ACCOUNT_PARTICLE_BTN_ACCESSIBILITY_ID).click()
        #driver.find_element(by=AppiumBy.ACCESSIBILITY_ID, value=constants.GHA_EXPAND_ACCOUNT_LIST).click()

        #gha_account.select_or_add_account("jess.for.att.ghp@gmail.com")






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