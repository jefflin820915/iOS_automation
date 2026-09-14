import base64
from datetime import datetime
import os
from typing import Optional
from appium.webdriver.webdriver import WebDriver


class ScreenRecorder:
    """Handles screen recording of iOS devices using Appium WebDriver and saves to Additional log."""

    def __init__(self, output_dir: str = "Additional log"):
        """Initializes the ScreenRecorder.
        Args:
            output_dir: Target directory where video files will be saved. Defaults
              to "Additional log".
        """
        self.output_dir = output_dir
        self._is_recording = False

    def start_recording(
            self,
            driver: WebDriver,
            time_limit: int = 1800,
            video_quality: str = "medium",
    ) -> bool:
        """Starts screen recording on the connected iOS device.
        Args:
            driver: Active Appium WebDriver instance.
            time_limit: Maximum recording time in seconds (default 1800s / 30 mins).
            video_quality: Video quality ('low', 'medium', 'high').
        Returns:
            True if recording started successfully, False otherwise.
        """
        if not driver:
            print(
                "[ScreenRecorder] Driver is not initialized. Cannot start recording."
            )
            return False
        try:
            # Start iOS screen recording via Appium XCUITest API
            driver.start_recording_screen(
                video_quality=video_quality,
                time_limit=time_limit,
            )
            self._is_recording = True
            print("[ScreenRecorder] Screen recording started successfully.")
            return True
        except Exception as e:
            print(f"[ScreenRecorder] Failed to start screen recording: {e}")
            self._is_recording = False
            return False

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
            print("[ScreenRecorder] Recording is not active or driver is None.")
            return None
        try:
            print("[ScreenRecorder] Stopping screen recording...")
            raw_base64_video = driver.stop_recording_screen()
            self._is_recording = False
            if not raw_base64_video:
                print("[ScreenRecorder] No video data received from Appium.")
                return None
            abs_output_dir = os.path.abspath(self.output_dir)
            os.makedirs(abs_output_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_test_name = f"{test_name}_" if test_name else ""
            video_filename = f"screen_record_{safe_test_name}{timestamp}.mp4"
            video_path = os.path.join(abs_output_dir, video_filename)
            video_bytes = base64.b64decode(raw_base64_video)
            with open(video_path, "wb") as f:
                f.write(video_bytes)
            print(f"[ScreenRecorder] Screen recording saved to: {video_path}")
            return video_path
        except Exception as e:
            print(f"[ScreenRecorder] Failed to stop/save screen recording: {e}")
            self._is_recording = False
            return None