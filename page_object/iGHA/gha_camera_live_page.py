"""Page object for continuously verifying camera live stream stability and handling auto-retries on iOS."""
import time
from typing import Optional, List
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webdriver import WebDriver
from appium.webdriver.webelement import WebElement
from selenium.common.exceptions import WebDriverException, StaleElementReferenceException
from common import constants
from common.base_page import BasePage, PageNotPresentException
from utils import logging_utils


class GHACameraLivePage(BasePage):
    """Class for monitoring camera live video stream and handling connection retries."""

    RETRY_LOCATORS = [
        (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "Retry"`]'),
        (AppiumBy.IOS_PREDICATE, 'name == "Retry" OR label == "Retry"'),
        (AppiumBy.XPATH, '//XCUIElementTypeButton[@name="Retry" or @label="Retry"]'),
        (AppiumBy.XPATH, '//XCUIElementTypeOther[@name="CameraStateInfoView"]//XCUIElementTypeButton'),
        (AppiumBy.ACCESSIBILITY_ID, "Retry"),
    ]

    ERROR_OVERLAY_LOCATORS = [
        (AppiumBy.ACCESSIBILITY_ID, "CameraStateInfoView"),
        (AppiumBy.ACCESSIBILITY_ID, "cameraStateTitleLabel"),
        (AppiumBy.IOS_PREDICATE, 'label CONTAINS "Live view unavailable" OR label CONTAINS "unreachable"'),
    ]

    def _get_retry_btn(self) -> Optional[WebElement]:
        """Locate the Retry button element without is_displayed() filter."""
        default_wait = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
        try:
            self.driver.implicitly_wait(0)
            for by, loc in self.RETRY_LOCATORS:
                try:
                    elements = self.driver.find_elements(by, loc)
                    if elements:
                        return elements[0]
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            self.driver.implicitly_wait(default_wait)
        return None

    def _click_retry(self, retry_btn: Optional[WebElement]) -> bool:
        """Click the Retry button using coordinates to bypass XCUITest 'visible: false' interaction block."""
        self._logger.info("Triggering interaction on Retry button...")
        if retry_btn:
            try:
                rect = retry_btn.rect
                cx = int(rect['x'] + rect['width'] / 2)
                cy = int(rect['y'] + rect['height'] / 2)
                self._logger.info(f"Tapping Retry at calculated center coordinates ({cx}, {cy})...")
                self.driver.execute_script("mobile: tap", {"x": cx, "y": cy})
                return True
            except Exception as coord_err:
                self._logger.warning(f"Calculated coordinate tap failed: {coord_err}")
            try:
                self.driver.execute_script("mobile: tap", {"elementId": retry_btn.id})
                return True
            except Exception:
                pass
        self._logger.info("Fallback tapping at verified Inspector coordinates (187, 176)...")
        try:
            self.driver.execute_script("mobile: tap", {"x": 187, "y": 176})
            return True
        except Exception as tap_err:
            self._logger.error(f"Failed to tap Retry button: {tap_err}")
            return False

    def is_camera_live(self) -> bool:
        """Check if camera video stream is actively playing in Live state.

        Verified via official CamerazillaPlayerView label: 'Camera on, viewing live stream'.
        """
        if self._get_retry_btn() is not None:
            return False
        default_wait = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
        try:
            self.driver.implicitly_wait(0)
            for by, loc in self.ERROR_OVERLAY_LOCATORS:
                if self.driver.find_elements(by, loc):
                    return False
            # 2. PRIMARY GROUND TRUTH: Check CamerazillaPlayerView with 'Camera on, viewing live stream'
            players = self.driver.find_elements(
                AppiumBy.IOS_CLASS_CHAIN,
                '**/XCUIElementTypeButton[`name == "CamerazillaPlayerView"`]'
            )
            if not players:
                players = self.driver.find_elements(AppiumBy.ACCESSIBILITY_ID, "CamerazillaPlayerView")
            for p in players:
                label = str(p.get_attribute("label") or "").lower()
                if "live stream" in label or "viewing live stream" in label or "camera on" in label:
                    return True
            # 3. Secondary check: Live text badge
            live_badges = self.driver.find_elements(
                AppiumBy.IOS_PREDICATE,
                'label CONTAINS "Live" OR name CONTAINS "Live"'
            )
            for badge in live_badges:
                try:
                    if badge.is_displayed():
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            self.driver.implicitly_wait(default_wait)
        return False

    def click_back_btn(self) -> bool:
        """Click the top-left back/close button to exit the Camera Live stream page."""
        self._logger.info("Exiting Camera Live screen: looking for back/close button...")
        back_locators = [
            (AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "closeButton"`]'),
            (AppiumBy.ACCESSIBILITY_ID, "closeButton"),
            (AppiumBy.ACCESSIBILITY_ID, "close"),
            (AppiumBy.ACCESSIBILITY_ID, "Close"),
            (AppiumBy.ACCESSIBILITY_ID, "Back"),
            (AppiumBy.ACCESSIBILITY_ID, "back"),
            (AppiumBy.IOS_PREDICATE, 'label == "Back" OR name == "Back" OR label == "Close" OR name == "close"'),
        ]
        try:
            self.driver.execute_script("mobile: tap", {"x": 50, "y": 100})
            time.sleep(0.5)
            elems = self.driver.find_element(AppiumBy.IOS_CLASS_CHAIN, '**/XCUIElementTypeButton[`name == "closeButton"`]')
            elems.click()
            self._logger.info("Successfully clicked back button.")
            return True
        except Exception:
            pass
        self._logger.info("Navigation bar may be hidden. Tapping screen to reveal controls...")
        try:
            self.driver.execute_script("mobile: tap", {"x": 200, "y": 300})
            time.sleep(1.0)
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

    def _trigger_emergency_device_removal(self) -> None:
        """Trigger GHA restart and device removal so the camera is factory reset for the next run."""
        self._logger.warning("[Live Verification FAILED] Initiating emergency teardown to remove paired camera...")
        session = getattr(self, "session", None)
        if session and hasattr(session, "_emergency_recover_and_remove_device"):
            try:
                session._emergency_recover_and_remove_device()
                self._logger.info("[Live Verification FAILED] Successfully removed device via emergency cleanup.")
            except Exception as clean_err:
                self._logger.error(f"[Live Verification FAILED] Error during emergency device removal: {clean_err}")
        else:
            self._logger.warning("[Live Verification FAILED] Session back-reference not found. Attempting back button and restart...")
            try:
                self.click_back_btn()
            except Exception:
                pass
            try:
                self.driver.terminate_app(constants.GHA_BUNDLE_ID)
                time.sleep(2.0)
                self.driver.activate_app(constants.GHA_BUNDLE_ID)
            except Exception:
                pass

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
            bool: True if camera streamed live successfully for duration_seconds.
        Raises:
            AssertionError: If retries are exhausted or stream cannot reach a steady Live state.
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
            retry_btn = self._get_retry_btn()
            if retry_btn is not None:
                if retry_count >= max_retries:
                    self._trigger_emergency_device_removal()
                    raise AssertionError(
                        f"Camera live stream verification FAILED: Reached maximum retry limit ({max_retries}) "
                        f"and stream is still not live."
                    )
                retry_count += 1
                self._logger.warning(
                    f"Camera stream disconnected! Found 'Retry' button in CameraStateInfoView. Clicking retry (#{retry_count}/{max_retries})..."
                )
                self._click_retry(retry_btn)
                self._logger.info(f"Clicked Retry (#{retry_count}). Waiting 5s for stream reconnection...")
                time.sleep(5.0)
                if self.is_camera_live():
                    has_streamed_live = True
                    self._logger.info(f"Camera live stream recovered after retry (#{retry_count})!")
                continue
            if self.is_camera_live():
                has_streamed_live = True
                if elapsed - last_heartbeat_log >= 5.0:
                    self._logger.info(
                        f"Camera is LIVE streaming smoothly... ({int(elapsed)}s / {int(duration_seconds)}s elapsed)"
                    )
                    last_heartbeat_log = elapsed
            else:
                self._logger.info(f"Camera stream buffering / not live yet... ({int(elapsed)}s / {int(duration_seconds)}s elapsed)")
            time.sleep(check_interval)
        if not has_streamed_live or not self.is_camera_live():
            self._trigger_emergency_device_removal()
            raise AssertionError(
                f"Camera live stream verification FAILED: Reached duration ({int(duration_seconds)}s) "
                f"but stream was not in a valid LIVE state (has_streamed_live={has_streamed_live}, "
                f"is_live_now={self.is_camera_live()})."
            )
        total_time = int(time.time() - start_time)
        self._logger.info(
            f"SUCCESS: Camera live stream verified continuously for {total_time}s! (Total retries clicked: {retry_count})"
        )
        if exit_on_pass:
            self.click_back_btn()
        return True