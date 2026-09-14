"""Session Page Object managing iGHP lifecycle and aggregating all sub-page objects."""

import time
from appium.webdriver.webdriver import WebDriver
from selenium.common.exceptions import WebDriverException

from common import constants
from utils import logging_utils


class GHPSession:
    """Central entry point managing iGHP application lifecycle and sub-page objects."""

    def __init__(self, driver: WebDriver) -> None:
        """Initialize GHPSession with Appium driver."""
        self.driver = driver
        self._logger = logging_utils.get_logger(__name__, "ghp_session")

        # Future iGHP sub-page objects can be initialized here
        # self.main_page = GHPMainPageObject(driver)

    def start_ghp(self, timeout: float = 10.0) -> bool:
        """Start the Google Home Platform Sample App."""
        self._logger.info("Starting iGHP Sample App on iOS...")
        try:
            self.driver.activate_app(constants.iGHP_SAMPLE_APP_BUNDLE_ID)
            time.sleep(2.0)
            state = self.driver.query_app_state(constants.iGHP_SAMPLE_APP_BUNDLE_ID)
            return state == constants.APP_STATE_FOREGROUND
        except WebDriverException as e:
            self._logger.error(f"Failed to activate iGHP App: {e}")
            return False