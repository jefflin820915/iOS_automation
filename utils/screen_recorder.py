"""Screen Recorder for iOS devices using Appium WebDriver and saves to Additional log."""
import base64
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import threading
import time
from typing import Any, Dict, Optional
from appium import webdriver
from appium.options.common import AppiumOptions
from appium.webdriver.webdriver import WebDriver
from common import constants
from utils import logging_utils

logger = logging_utils.get_logger(__name__, "screen_recorder")


class _LocalVideoUploadServer:
    """Ephemeral localhost HTTP server receiving streamed video from Appium's `remotePath` option.
    Why this exists:
    When `driver.stop_recording_screen()` is called without `remotePath`, Appium reads the entire
    `.mp4` file into Node.js memory, converts it to a giant Base64 string, and calls `JSON.stringify`
    (`v8::internal::FastJsonStringifier`). On large recordings (e.g. 200+ MB), V8's Zone allocator
    crashes the entire Appium Node.js server with:
        `FATAL ERROR: Zone Allocation failed - process out of memory`
    Passing `remotePath="http://127.0.0.1:<port>/video.mp4"` makes Appium stream the file from disk
    via `fs.createReadStream` over loopback HTTP and return an empty JSON string `""`, completely
    avoiding Base64 encoding and V8 `JSON.stringify` OOM.
    """
    def __init__(self, target_path: str):
        self.target_path = target_path
        self.received_bytes = 0
        self.content_type = ""
        self.error: Optional[Exception] = None
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
    def start(self) -> str:
        parent = self
        class _UploadHandler(BaseHTTPRequestHandler):
            def _handle_upload(self) -> None:
                try:
                    parent.content_type = self.headers.get("Content-Type", "") or ""
                    transfer_enc = (self.headers.get("Transfer-Encoding", "") or "").lower()
                    total = 0
                    with open(parent.target_path, "wb") as out_f:
                        if "chunked" in transfer_enc:
                            while True:
                                line = self.rfile.readline().strip()
                                if not line:
                                    break
                                chunk_len = int(line.split(b";")[0], 16)
                                if chunk_len == 0:
                                    self.rfile.readline()
                                    break
                                remaining = chunk_len
                                while remaining > 0:
                                    data = self.rfile.read(min(65536, remaining))
                                    if not data:
                                        break
                                    out_f.write(data)
                                    total += len(data)
                                    remaining -= len(data)
                                self.rfile.readline()
                        else:
                            remaining = int(self.headers.get("Content-Length", "0") or 0)
                            while remaining > 0:
                                data = self.rfile.read(min(65536, remaining))
                                if not data:
                                    break
                                out_f.write(data)
                                total += len(data)
                                remaining -= len(data)
                    if "multipart/form-data" in parent.content_type.lower() and total > 0:
                        parent._strip_multipart_envelope()
                        parent.received_bytes = os.path.getsize(parent.target_path)
                    else:
                        parent.received_bytes = total
                    self.send_response(200)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"OK")
                except Exception as exc:
                    parent.error = exc
                    try:
                        self.send_response(500)
                        self.end_headers()
                    except Exception:
                        pass
            do_PUT = _handle_upload
            do_POST = _handle_upload
            def log_message(self, format: str, *args: Any) -> None:
                return  # Suppress noisy BaseHTTPRequestHandler stderr logs
        self._server = HTTPServer(("127.0.0.1", 0), _UploadHandler)
        port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._thread.start()
        return f"http://127.0.0.1:{port}/video.mp4"
    def _strip_multipart_envelope(self) -> None:
        """If Appium uploaded as multipart/form-data, strip the outer boundary header and footer."""
        with open(self.target_path, "rb") as f:
            head = f.read(1024)
            header_end = head.find(b"\r\n\r\n")
            if header_end < 0:
                return
            payload_start = header_end + 4
            f.seek(0, os.SEEK_END)
            file_len = f.tell()
            tail_read = min(512, file_len - payload_start)
            f.seek(file_len - tail_read)
            tail = f.read(tail_read)
            boundary_pos = tail.rfind(b"\r\n--")
            payload_end = (file_len - tail_read + boundary_pos) if boundary_pos >= 0 else file_len
        tmp_path = self.target_path + ".raw"
        with open(self.target_path, "rb") as src, open(tmp_path, "wb") as dst:
            src.seek(payload_start)
            remaining = max(0, payload_end - payload_start)
            while remaining > 0:
                chunk = src.read(min(65536, remaining))
                if not chunk:
                    break
                dst.write(chunk)
                remaining -= len(chunk)
        os.replace(tmp_path, self.target_path)
    def close(self) -> None:
        if self._server:
            try:
                self._server.shutdown()
            except Exception:
                pass
            try:
                self._server.server_close()
            except Exception:
                pass
            self._server = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
class ScreenRecorder:
    """Handles screen recording of iOS devices using Appium WebDriver and saves to Additional log.
    Uses the standard Appium API (driver.start_recording_screen / stop_recording_screen).
    - Defaults to H.264 (`videoType='libx264'`, `pixelFormat='yuv420p'`, `videoFps=5`, `videoQuality='low'`)
      so a 10-15 min recording is ~5-15 MB instead of ~250 MB (Motion JPEG). Automatically falls back to
      driver default (`mjpeg`) if `libx264` is rejected.
    - Streams the recorded video via a local HTTP `remotePath` endpoint in `stop_recording_screen` so Appium
      does not Base64-encode and `JSON.stringify` a multi-hundred-MB buffer in V8 memory (which crashes
      Node.js with `FATAL ERROR: Zone Allocation failed - process out of memory`).
    """
    WDA_ERROR_SIGNATURES = (
        "ECONNREFUSED",
        "ECONNRESET",
        "Remote host closed connection",
        "Connection aborted",
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
            "[ScreenRecorder] Detected dead WDA/Appium connection. Rebuilding Appium WebDriver session..."
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
            video_quality: str = "low",
            video_fps: int = 5,
            video_scale: str = "720:-2",
            video_type: Optional[str] = "libx264",
            pixel_format: Optional[str] = "yuv420p",
    ) -> bool:
        """Starts screen recording on the connected iOS device.
        Args:
            driver: Active Appium WebDriver instance.
            time_limit: Maximum recording time in seconds (default 1800s / 30 mins).
            video_quality: 'low', 'medium', 'high' or 'photo'. Defaults to 'low' to prevent 200+ MB files.
            video_fps: Frames per second (default 5, sufficient for UI automation).
            video_scale: ffmpeg scale value (default '720:-2' = 720 px wide, aspect ratio kept).
            video_type: ffmpeg video codec. Defaults to 'libx264' (inter-frame H.264 compression, ~15x smaller
                than 'mjpeg'). Pass None to use the driver default ('mjpeg').
            pixel_format: ffmpeg output pixel format. Defaults to 'yuv420p' for QuickTime/Drive compatibility.
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
            elif video_type or pixel_format:
                logger.warning(
                    f"[ScreenRecorder] Codec {video_type}/{pixel_format} rejected ({e}); "
                    "retrying with driver default codec..."
                )
                options.pop("videoType", None)
                options.pop("pixelFormat", None)
                video_type = None
                pixel_format = None
                try:
                    driver.start_recording_screen(**options)
                except Exception as fallback_err:
                    logger.error(f"[ScreenRecorder] Failed to start screen recording: {fallback_err}")
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
            self,
            driver: WebDriver,
            test_name: Optional[str] = None,
            use_remote_stream: bool = True,
    ) -> Optional[str]:
        """Stops screen recording and saves the .mp4 video to the Additional log directory.
        Uses an ephemeral localhost HTTP server (`remotePath`) by default so Appium streams the `.mp4`
        directly to disk instead of Base64-encoding and `JSON.stringify`-ing it in V8 memory.
        Falls back to decoding Base64 if the driver returns Base64 payload directly.
        Args:
            driver: Active Appium WebDriver instance.
            test_name: Optional test case name to prefix the output filename.
            use_remote_stream: Whether to stream via localhost HTTP `remotePath` to avoid Appium V8 OOM.
        Returns:
            Absolute path to the saved .mp4 video file, or None if failed.
        """
        if not driver or not self._is_recording:
            logger.warning("[ScreenRecorder] Recording is not active or driver is None.")
            return None
        elapsed = time.time() - self._started_at if self._started_at else 0.0
        try:
            abs_output_dir = os.path.abspath(self.output_dir)
            os.makedirs(abs_output_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_test_name = f"{test_name}_" if test_name else ""
            video_filename = f"screen_record_{safe_test_name}{timestamp}.mp4"
            video_path = os.path.join(abs_output_dir, video_filename)
        except Exception as e:
            logger.error(f"[ScreenRecorder] Failed to prepare output path: {e}")
            self._is_recording = False
            self._started_at = None
            return None
        upload_server: Optional[_LocalVideoUploadServer] = None
        raw_base64_video: Any = None
        try:
            logger.info(f"[ScreenRecorder] Stopping screen recording (recorded for {elapsed:.0f}s)...")
            if use_remote_stream:
                try:
                    upload_server = _LocalVideoUploadServer(video_path)
                    remote_url = upload_server.start()
                    raw_base64_video = driver.stop_recording_screen(
                        remotePath=remote_url,
                        method="PUT",
                        fileFieldName="",
                    )
                except Exception as stream_err:
                    if self._is_wda_connection_error(stream_err):
                        raise stream_err
                    logger.warning(
                        f"[ScreenRecorder] Streamed stop_recording_screen failed ({stream_err}); "
                        "falling back to standard stop_recording_screen()..."
                    )
                    raw_base64_video = driver.stop_recording_screen()
            else:
                raw_base64_video = driver.stop_recording_screen()
        except Exception as e:
            logger.error(f"[ScreenRecorder] Failed to stop screen recording: {e}")
            if self._is_wda_connection_error(e):
                self._reconnect_driver_in_place(driver)
            return None
        finally:
            if upload_server:
                upload_server.close()
            self._is_recording = False
            self._started_at = None
        if self._time_limit and elapsed > self._time_limit:
            logger.warning(
                f"[ScreenRecorder] Case ran {elapsed:.0f}s but timeLimit is {self._time_limit}s: "
                f"the last {elapsed - self._time_limit:.0f}s are not in the video."
            )
        # Case 1: Streamed directly to disk via localhost HTTP `remotePath`
        if upload_server and upload_server.received_bytes > 0 and os.path.exists(video_path):
            file_size_mb = upload_server.received_bytes / (1024 * 1024)
            logger.info(
                f"[ScreenRecorder] Screen recording streamed & saved to: {video_path} "
                f"(Size: {file_size_mb:.2f} MB)"
            )
            return video_path
        # Case 2: Fallback when driver returned Base64 payload directly
        if not raw_base64_video:
            if os.path.exists(video_path):
                try:
                    os.remove(video_path)
                except OSError:
                    pass
            logger.warning("[ScreenRecorder] No video data received from Appium.")
            return None
        try:
            video_bytes = base64.b64decode(raw_base64_video)
            with open(video_path, "wb") as f:
                f.write(video_bytes)
        except Exception as e:
            logger.error(f"[ScreenRecorder] Failed to save screen recording: {e}")
            return None
        file_size_mb = len(video_bytes) / (1024 * 1024)
        logger.info(f"[ScreenRecorder] Screen recording saved to: {video_path} (Size: {file_size_mb:.2f} MB)")
        return video_path