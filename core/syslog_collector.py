import atexit
import os
import signal
import subprocess
from typing import Optional, List


class SyslogCollector:

    """Collects iOS syslog output into a file and guarantees cleanup upon termination."""
    def __init__(self, udid: str, output_path: str, command: Optional[List[str]] = None):
        """Initializes the SyslogCollector.
        Args:
            udid: The UDID of the iOS device.
            output_path: Path to the log file where syslog will be saved.
            command: Custom syslog command list. Defaults to tidevice syslog.
        """
        self.udid = udid
        self.output_path = output_path
        self.custom_command = command
        self._process: Optional[subprocess.Popen] = None
        self._file = None
        atexit.register(self.stop)

    def start(self) -> None:
        """Starts capturing syslog in a separate process group."""
        if self._process and self._process.poll() is None:
            print(f"[SyslogCollector] Syslog capture already running (PID: {self._process.pid}).")
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.output_path)), exist_ok=True)
        self._file = open(self.output_path, "w", encoding="utf-8", errors="replace")
        if self.custom_command:
            cmd = self.custom_command
        else:
            cmd = ["tidevice", "-u", self.udid, "syslog"]
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=self._file,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # Creates a new process group for clean termination
            )
            print(f"[SyslogCollector] Started syslog capture (PID: {self._process.pid}) -> {self.output_path}")
        except Exception as e:
            print(f"[SyslogCollector] Failed to start syslog capture with command {cmd}: {e}")
            if self._file:
                self._file.close()
                self._file = None
            raise

    def stop(self) -> None:
        """Gracefully terminates and kills the syslog process, closing the log file."""
        if self._process:
            pid = self._process.pid
            try:
                if self._process.poll() is None:
                    print(f"[SyslogCollector] Stopping syslog process group (PID: {pid})...")
                    try:
                        pgid = os.getpgid(pid)
                        os.killpg(pgid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        self._process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        print(f"[SyslogCollector] Syslog process {pid} didn't exit in time, killing with SIGKILL...")
                        try:
                            pgid = os.getpgid(pid)
                            os.killpg(pgid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        self._process.wait(timeout=2)
            except Exception as e:
                print(f"[SyslogCollector] Error while terminating syslog process {pid}: {e}")
            finally:
                self._process = None
        if self._file:
            try:
                self._file.flush()
                self._file.close()
            except Exception as e:
                print(f"[SyslogCollector] Error closing syslog file: {e}")
            finally:
                self._file = None
                print("[SyslogCollector] Syslog recording successfully stopped and closed.")

    def get_recent_logs(self, max_lines: int = 200) -> str:
        """Reads the last N lines from the captured syslog file.
        Args:
            max_lines: Number of trailing lines to return.
        Returns:
            A string containing the most recent log lines.
        """
        if not os.path.exists(self.output_path):
            return ""
        try:
            with open(self.output_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                return "".join(lines[-max_lines:])
        except Exception as e:
            return f"[SyslogCollector] Error reading recent logs: {e}"
    def __enter__(self):
        self.start()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()