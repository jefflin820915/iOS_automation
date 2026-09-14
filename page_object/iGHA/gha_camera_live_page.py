"""Page object for continuously verifying camera live stream stability and handling auto-retries on iOS."""
import time
from typing import Optional
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException
from common import constants
from common.base_page import BasePage, PageNotPresentException
from utils import logging_utils


class GHACameraLivePage(BasePage):
    """Class for monitoring camera live video stream and handling connection retries."""

    PLAYER_VIEW_CLASS_CHAIN = (
        '**/XCUIElementTypeButton[`name == "XCUIElementTypeStaticText" AND visible == 1`]',
        '**/XCUIElementTypeButton[`name == "CamerazillaPlayerView" AND visible == 1`]',
        '**/XCUIElementTypeButton[`name == "cameraStatusBadgeView" AND visible == 1`]'
    )
    LIVE_INDICATOR_PREDICATE = (
        '(label == "Live" OR label == "• Live" OR name == "Live" OR '
        'label CONTAINS "live stream") AND visible == 1'
    )


    RETRY_BTN_CLASS_CHAIN = "**/XCUIElementTypeButton[`name == \"Retry\"`]"


    def is_camera_live(self) -> bool:
        """Check if camera video stream is actively playing in Live state."""
        default_wait = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
        try:
            self.driver.implicitly_wait(0)
            players = self.driver.find_elements(AppiumBy.IOS_CLASS_CHAIN, self.PLAYER_VIEW_CLASS_CHAIN)
            for p in players:
                if p.is_displayed():
                    label = str(p.get_attribute("label") or "").lower()
                    if "live stream" in label or "camera on" in label:
                        return True
            live_badges = self.driver.find_elements(AppiumBy.IOS_PREDICATE, self.LIVE_INDICATOR_PREDICATE)
            if live_badges and live_badges[0].is_displayed():
                return True
        except Exception:
            pass
        finally:
            self.driver.implicitly_wait(default_wait)
        return False

    def _get_visible_retry_btn(self) -> Optional[WebElement]:
        """Check if a visible 'Retry' button is currently present on screen."""
        default_wait = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
        try:
            self.driver.implicitly_wait(0)
            retry_elems = self.driver.find_element(AppiumBy.IOS_CLASS_CHAIN, self.RETRY_BTN_CLASS_CHAIN)
            return retry_elems
        except Exception:
            pass
        finally:
            self.driver.implicitly_wait(default_wait)
        return None

    def click_back_btn(self) -> bool:
        """Click the top-left back/close button to exit the Camera Live stream page."""
        self._logger.info("Exiting Camera Live screen: looking for back/close button...")

        back_locators = [
            (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "closeButton" AND visible == 1`]'),
            (AppiumBy.ACCESSIBILITY_ID, "close"),
            (AppiumBy.ACCESSIBILITY_ID, "Close"),
            (AppiumBy.ACCESSIBILITY_ID, "Back"),
            (AppiumBy.ACCESSIBILITY_ID, "back"),
            (AppiumBy.IOS_PREDICATE, 'label == "Back" OR name == "Back" OR label == "Close" OR name == "close"'),
        ]
        try:
            self.driver.execute_script("mobile: tap", {"x": 50, "y": 100})
            time.sleep(0.5)
            elems = self.driver.find_element(AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "closeButton" AND visible == 1`]')
            elems.click()
            self._logger.info("Successfully clicked back button.")
            return True
        except Exception:
            pass
        self._logger.info("Navigation bar may be hidden. Tapping screen to reveal controls...")
        try:
            players = self.driver.find_elements(AppiumBy.IOS_CLASS_CHAIN, self.PLAYER_VIEW_CLASS_CHAIN)
            if players and players[0].is_displayed():
                players[0].click()
            else:
                self.driver.execute_script("mobile: tap", {"x": 50, "y": 100})
            for by, val in back_locators:
                elems = self.driver.find_elements(by, val)
                if elems and elems[0].is_displayed():
                    elems[0].click()
                    time.sleep(1.5)
                    self._logger.info("Successfully clicked back button after revealing controls.")
                    return True
        except Exception as e:
            self._logger.warning(f"Error tapping screen to reveal controls: {e}")
        self._logger.warning("Fallback: Tapping top-left corner coordinates to exit live view...")
        try:
            self.driver.execute_script("mobile: tap", {"x": 25, "y": 55})
            time.sleep(1.5)
            return True
        except Exception as e:
            self._logger.error(f"Failed to click back: {e}")
            return False

    def verify_camera_live_stream(
            self,
            duration_seconds: float = 30.0,
            max_retries: int = 20,
            check_interval: float = 1.0,
            exit_on_pass: bool = True
    ) -> bool:
        """Continuously observe camera live stream for duration_seconds, auto-clicking Retry if needed.
        Args:
            duration_seconds (float): Total seconds to continuously verify live stream (e.g. 30.0s).
            max_retries (int): Maximum allowable Retry clicks before failing. Defaults to 20.
            check_interval (float): Polling interval in seconds. Defaults to 1.0s.
            exit_on_pass (bool): Whether to click back button upon successful verification. Defaults to True.
        Returns:
            bool: True if camera streamed live successfully for duration_seconds, False otherwise.
        """
        self._logger.info(
            f"Starting Camera Live stream verification (Target: {int(duration_seconds)}s, Max Retries: {max_retries})..."
        )
        start_time = time.time()
        retry_count = 0
        last_heartbeat_log = 0.0
        has_streamed_live = False
        while (time.time() - start_time) < duration_seconds:
            elapsed = time.time() - start_time
            if retry_btn := self._get_visible_retry_btn():
                if retry_count >= max_retries:
                    return AssertionError(
                        f"Camera live stream verification FAILED: Reached maximum retry limit ({max_retries}) "
                        f"and stream is still not live. Returning False."
                    )
                retry_count += 1
                self._logger.warning(
                    f"Camera stream disconnected! Found 'Retry' button. Clicking retry (#{retry_count}/{max_retries})..."
                )
                try:
                    retry_btn.click()
                except WebDriverException:
                    self.driver.execute_script("mobile: tap", {"elementId": retry_btn.id})
                time.sleep(3.0)
                if self.is_camera_live():
                    has_streamed_live = True
                    self._logger.info(f"Camera live stream recovered after retry (#{retry_count}).")
                elif retry_count >= max_retries:
                    return AssertionError(
                        f"Camera live stream verification FAILED: Exhausted all {max_retries} retries "
                        f"and stream failed to recover. Returning False."
                    )
                continue
            if self.is_camera_live():
                has_streamed_live = True
                if elapsed - last_heartbeat_log >= 10.0:
                    self._logger.info(
                        f"Camera is LIVE streaming smoothly... ({int(elapsed)}s / {int(duration_seconds)}s elapsed)"
                    )
                    last_heartbeat_log = elapsed
            else:
                self._logger.debug(f"Camera stream buffering/reconnecting... ({int(elapsed)}s elapsed)")
            time.sleep(check_interval)
        if not has_streamed_live or not self.is_camera_live():
            return AssertionError(
                f"Camera live stream verification FAILED: Reached duration ({int(duration_seconds)}s) "
                f"but stream was not in a valid LIVE state (has_streamed_live={has_streamed_live}). Returning False."
            )
        total_time = int(time.time() - start_time)
        self._logger.info(
            f"SUCCESS: Camera live stream verified continuously for {total_time}s! (Total retries clicked: {retry_count})"
        )
        if exit_on_pass:
            self.click_back_btn()
        return True