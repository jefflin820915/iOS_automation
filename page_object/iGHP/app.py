"""App Facade for iOS Google Home Platform Sample App (iGHP)."""

from appium.webdriver.webdriver import WebDriver
from page_objects.iGHP.ghp_session import GHPSessionObject


class GHPApp:
    """Unified entry point for all iGHP Page Objects."""

    def __init__(self, driver: WebDriver) -> None:
        self.driver = driver
        self.session = GHPSessionObject(driver)