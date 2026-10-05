"""Screen Recorder for iOS devices using Appium WebDriver and saves to Additional log."""
import base64
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional
from appium import webdriver
from appium.options.common import AppiumOptions
from appium.webdriver.webdriver import WebDriver
from common import constants
from utils import logging_utils

logger = logging_utils.get_logger(__name__, "screen_recorder")


class ScreenRecorder:
    """Handles screen recording of iOS devices using Appium WebDriver and saves to Additional log.
    Uses the standard Appium API (driver.start_recording_screen / stop_recording_screen), the same call
    the previous version fell back to. `mobile: startScreenRecording` is NOT used: it only exists in
    appium-xcuitest-driver >= 11.1.0 and older drivers reject it with NotImplementedError.
    Option keys must be camelCase: the Python client forwards them unchanged and the driver silently
    ignores unknown keys such as `time_limit`. On real devices the driver records with ffmpeg on the
    Appium host (`brew install ffmpeg`).
    """
    WDA_ERROR_SIGNATURES = (
        "ECONNREFUSED",
        "Could not proxy command to the remote server",
        "socket hang up",
        "A session is either terminated or not started",
        "invalid session id",
        "NoSuchDriverError",
    )

    def __init__(self, output_dir: str = "Additional log"):
        """Initializes the ScreenRecorder.
        Args:
            output_dir: Target directory where video files will be saved. Defaults to "Additional log".
        """
        self.output_dir = output_dir
        self._is_recording = False
        self._started_at: Optional[float] = None
        self._time_limit: Optional[int] = None

    @classmethod
    def _is_wda_connection_error(cls, exc: Exception) -> bool:
        """Return True if the exception indicates WDA (127.0.0.1:8100) or the Appium session disconnected."""
        msg = str(exc)
        return any(sig in msg for sig in cls.WDA_ERROR_SIGNATURES)

    @staticmethod
    def _reconnect_driver_in_place(driver: WebDriver) -> bool:
        """Rebuild the Appium WebDriver session in-place so all existing driver references heal automatically."""
        logger.warning(
            "[ScreenRecorder] Detected dead WDA connection (127.0.0.1:8100). Rebuilding Appium WebDriver session..."
        )
        device_tech_info = getattr(driver, "device_tech_info", None)
        try:
            driver.quit()
        except Exception:
            pass
        try:
            options = AppiumOptions()
            options.load_capabilities(constants.IOS_CAPABILITIES)
            new_driver = webdriver.Remote(constants.APPIUM_SERVER_URL, options=options)
            new_driver.implicitly_wait(getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0))
            if device_tech_info is not None:
                new_driver.device_tech_info = device_tech_info
            driver.__dict__.update(new_driver.__dict__)
            logger.info(
                f"[ScreenRecorder] Successfully re-established Appium/WDA session (session_id={driver.session_id})."
            )
            return True
        except Exception as reconnect_err:
            logger.error(f"[ScreenRecorder] Failed to rebuild Appium WebDriver session: {reconnect_err}")
            return False

    def start_recording(
            self,
            driver: WebDriver,
            time_limit: int = 1800,
            video_quality: str = "medium",
            video_fps: int = 10,
            video_scale: str = "720:-2",
            video_type: Optional[str] = None,
            pixel_format: Optional[str] = None,
    ) -> bool:
        """Starts screen recording on the connected iOS device.
        Args:
            driver: Active Appium WebDriver instance.
            time_limit: Maximum recording time in seconds (default 1800s / 30 mins). The driver stops
                recording by itself after this and rejects values above its maximum
                (4200s on current appium-xcuitest-driver).
            video_quality: 'low', 'medium', 'high' or 'photo'. Defaults to 'medium'.
            video_fps: Frames per second (default 10, enough for UI automation).
            video_scale: ffmpeg scale value (default '720:-2' = 720 px wide, aspect ratio kept).
            video_type: ffmpeg video codec. None keeps the driver default ('mjpeg').
                Use 'libx264' together with pixel_format='yuv420p' for H.264 output.
            pixel_format: ffmpeg output pixel format (e.g. 'yuv420p'). None keeps the driver default.
        Returns:
            True if recording started successfully, False otherwise.
        """
        if not driver:
            logger.error("[ScreenRecorder] Driver is not initialized. Cannot start recording.")
            return False
        options: Dict[str, Any] = {
            "timeLimit": time_limit,
            "videoQuality": video_quality,
            "videoFps": video_fps,
            "videoScale": video_scale,
            "forceRestart": True,  # restart cleanly if a previous recording is still running
        }
        if video_type:
            options["videoType"] = video_type
        if pixel_format:
            options["pixelFormat"] = pixel_format
        try:
            driver.start_recording_screen(**options)
        except Exception as e:
            if self._is_wda_connection_error(e) and self._reconnect_driver_in_place(driver):
                try:
                    driver.start_recording_screen(**options)
                except Exception as retry_err:
                    logger.error(f"[ScreenRecorder] Failed to start screen recording after WDA reconnect: {retry_err}")
                    self._is_recording = False
                    return False
            else:
                logger.error(f"[ScreenRecorder] Failed to start screen recording: {e}")
                self._is_recording = False
                return False
        self._is_recording = True
        self._started_at = time.time()
        self._time_limit = time_limit
        extra = "".join(
            f", {key}={value}" for key, value in (("type", video_type), ("pix_fmt", pixel_format)) if value
        )
        logger.info(
            f"[ScreenRecorder] Screen recording started successfully "
            f"(timeLimit={time_limit}s, quality={video_quality}, fps={video_fps}, scale={video_scale}{extra})."
        )
        return True

    def stop_recording(
            self, driver: WebDriver, test_name: Optional[str] = None
    ) -> Optional[str]:
        """Stops screen recording and saves the .mp4 video to the Additional log directory.
        Args:
            driver: Active Appium WebDriver instance.
            test_name: Optional test case name to prefix the output filename.
        Returns:
            Absolute path to the saved .mp4 video file, or None if failed.
        """
        if not driver or not self._is_recording:
            logger.warning("[ScreenRecorder] Recording is not active or driver is None.")
            return None
        elapsed = time.time() - self._started_at if self._started_at else 0.0
        try:
            logger.info(f"[ScreenRecorder] Stopping screen recording (recorded for {elapsed:.0f}s)...")
            raw_base64_video = driver.stop_recording_screen()
        except Exception as e:
            logger.error(f"[ScreenRecorder] Failed to stop screen recording: {e}")
            return None
        finally:
            self._is_recording = False
            self._started_at = None
        if not raw_base64_video:
            logger.warning("[ScreenRecorder] No video data received from Appium.")
            return None
        if self._time_limit and elapsed > self._time_limit:
            logger.warning(
                f"[ScreenRecorder] Case ran {elapsed:.0f}s but timeLimit is {self._time_limit}s: "
                f"the last {elapsed - self._time_limit:.0f}s are not in the video."
            )
        try:
            abs_output_dir = os.path.abspath(self.output_dir)
            os.makedirs(abs_output_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_test_name = f"{test_name}_" if test_name else ""
            video_filename = f"screen_record_{safe_test_name}{timestamp}.mp4"
            video_path = os.path.join(abs_output_dir, video_filename)
            video_bytes = base64.b64decode(raw_base64_video)
            with open(video_path, "wb") as f:
                f.write(video_bytes)
        except Exception as e:
            logger.error(f"[ScreenRecorder] Failed to save screen recording: {e}")
            return None
        file_size_mb = len(video_bytes) / (1024 * 1024)
        logger.info(f"[ScreenRecorder] Screen recording saved to: {video_path} (Size: {file_size_mb:.2f} MB)")
        return video_path