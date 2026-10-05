"""Streams a device-side log command (e.g. `adb shell catch_log`) into a file.
Unlike SyslogCollector, this collector survives device reboots (e.g. smart-plug power cycles):
if the stream ends while the test case is still running, it waits for the device to come back
and resumes appending to the same file, with marker lines in between.
"""
import atexit
import os
import signal
import subprocess
import threading
import time
from datetime import datetime
from typing import List, Optional
from utils import logging_utils
logger = logging_utils.get_logger(__name__, "runner")

class DeviceLogCollector:
    """Captures a long-running device log command into a file with auto-reconnect."""

    FAST_EXIT_S = 3.0
    MAX_FAST_EXITS = 3
    STATE_POLL_S = 2.0

    def __init__(
            self,
            output_path: str,
            command: List[str],
            state_command: Optional[List[str]] = None,
            stop_command: Optional[List[str]] = None,
            reconnect_timeout_s: float = 180.0,
            label: str = "DeviceLog",
    ):
        """
        Args:
            output_path: File to append the device log to.
            command: Streaming command, e.g. ["adb", "shell", "catch_log"].
            state_command: Readiness check printing 'device' when connected, e.g. ["adb", "get-state"].
            stop_command: Optional device-side cleanup run on stop, e.g. ["adb", "shell", "pkill -f catch_log"].
            reconnect_timeout_s: Max wait per reconnect cycle before re-checking.
            label: Tag used in console logs and marker lines.
        """
        self.output_path = output_path
        self.command = command
        self.state_command = state_command
        self.stop_command = stop_command
        self.reconnect_timeout_s = reconnect_timeout_s
        self.label = label
        self._file = None
        self._process: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        atexit.register(self.stop)

    def start(self) -> None:
        """Start capturing in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.info(f"[{self.label}] Capture already running.")
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.output_path)), exist_ok=True)
        self._file = open(self.output_path, "ab", buffering=0)  # O_APPEND, shared with child process
        self._stop_event.clear()
        self._marker(f"capture started: {' '.join(self.command)}")
        self._thread = threading.Thread(target=self._run_loop, name=f"{self.label}-collector", daemon=True)
        self._thread.start()
        logger.info(f"[{self.label}] Capturing '{' '.join(self.command)}' -> {self.output_path}")

    def stop(self) -> None:
        """Stop capturing, clean up the device-side process, and close the file."""
        if self._file is None and self._thread is None:
            return
        self._stop_event.set()
        with self._lock:
            proc = self._process
        if proc is not None:
            self._terminate(proc)
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        if self.stop_command:
            try:
                subprocess.run(self.stop_command, capture_output=True, timeout=5, stdin=subprocess.DEVNULL)
            except Exception as e:
                logger.debug(f"[{self.label}] Stop command failed (ignored): {e}")
        if self._file:
            self._marker("capture stopped")
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None
            logger.info(f"[{self.label}] Capture stopped: {self.output_path}")

    def _marker(self, text: str) -> None:
        if not self._file:
            return
        try:
            line = f"\n===== [{self.label}] {datetime.now():%Y-%m-%d %H:%M:%S} {text} =====\n"
            self._file.write(line.encode("utf-8", errors="replace"))
        except Exception:
            pass

    def _device_ready(self) -> bool:
        if not self.state_command:
            return True
        try:
            out = subprocess.run(
                self.state_command, capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL
            )
            return out.stdout.strip() == "device"
        except Exception:
            return False

    def _wait_for_device(self) -> bool:
        deadline = time.time() + self.reconnect_timeout_s
        while not self._stop_event.is_set():
            if self._device_ready():
                self._marker("device connected")
                return True
            if time.time() > deadline:
                self._marker(f"device not back after {self.reconnect_timeout_s:.0f}s; still waiting")
                return False
            self._stop_event.wait(self.STATE_POLL_S)
        return False

    def _spawn(self) -> Optional[subprocess.Popen]:
        with self._lock:
            if self._stop_event.is_set():
                return None
            try:
                self._process = subprocess.Popen(
                    self.command,
                    stdout=self._file,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except Exception as e:
                self._marker(f"failed to start command: {e}")
                logger.error(f"[{self.label}] Failed to start {self.command}: {e}")
                self._process = None
            return self._process

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        for sig, wait_s in ((signal.SIGTERM, 3), (signal.SIGKILL, 2)):
            try:
                os.killpg(os.getpgid(proc.pid), sig)
            except (ProcessLookupError, PermissionError):
                return
            try:
                proc.wait(timeout=wait_s)
                return
            except subprocess.TimeoutExpired:
                continue
    def _run_loop(self) -> None:
        fast_exits = 0
        while not self._stop_event.is_set():
            if not self._device_ready():
                self._marker("device not connected; waiting...")
                logger.warning(f"[{self.label}] Device not connected; waiting to start capture...")
                if not self._wait_for_device():
                    continue
            started = time.time()
            proc = self._spawn()
            if proc is None:
                return
            rc = proc.wait()
            with self._lock:
                self._process = None
            if self._stop_event.is_set():
                return
            lived = time.time() - started
            fast_exits = fast_exits + 1 if lived < self.FAST_EXIT_S else 0
            self._marker(f"stream ended (rc={rc}, after {lived:.1f}s); reconnecting...")
            logger.warning(f"[{self.label}] Stream ended (rc={rc}, {lived:.1f}s). Device may be rebooting; reconnecting...")
            if fast_exits >= self.MAX_FAST_EXITS:
                self._marker("command keeps exiting immediately; giving up for this test case")
                logger.error(f"[{self.label}] '{' '.join(self.command)}' keeps exiting immediately; capture disabled.")
                return
            self._stop_event.wait(self.STATE_POLL_S)