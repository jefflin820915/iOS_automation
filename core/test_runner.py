"""Module for managing test execution lifecycles, iterations, session setup, teardown, and reporting."""
from contextlib import contextmanager
import inspect
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import traceback
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Tuple, Type, Union

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]
from appium import webdriver
from appium.options.common import AppiumOptions
from common import constants
from common.base_page import BasePage
from core.device_log_collector import DeviceLogCollector
from core.syslog_collector import SyslogCollector
from page_object.iGHA.gha_session import GHASession
from page_object.iGHP.ghp_session import GHPSession
from testcase.iGHA.test_home import TestGHAHome

try:
    from testcase.iGHP.test_home import TestGHPHome
except ImportError:  # pragma: no cover - fallback when testcase is partially mocked
    TestGHPHome = None  # type: ignore[assignment]
from utils import logging_utils
from utils.drive_uploader import DriveUploader
from utils.environment_utils import log_all_version_information, get_wifi_information
from utils.screen_recorder import ScreenRecorder
from utils.gemini_reporter import GeminiReporter
from utils import csv_report

logger = logging_utils.get_logger(__name__, "runner")


def extract_failure_stage(exc: Exception) -> str:
    """Automatically extract failing method name from exception traceback without manual tagging."""
    if not exc or not hasattr(exc, "__traceback__"):
        return "UNKNOWN"
    tb_frames = traceback.extract_tb(exc.__traceback__)
    for frame in reversed(tb_frames):
        if "page_object" in frame.filename:
            if frame.name not in ("find_element", "find_elements", "click", "send_keys",
                                  "__getattr__"):
                return frame.name.upper()
        if "testcase" in frame.filename and frame.line:
            matches = re.findall(r"\.([a-zA-Z0-9_]+)\s*\(", frame.line)
            if matches:
                return matches[-1].upper()
            return frame.name.upper()
    return "UNKNOWN"


class MultiProjectTestRunner:
    """Class managing complete test execution lifecycle, multi-iteration runs, and automated reporting."""
    MIN_FREE_DISK_GB: float = 5.0
    ACTIVE_SESSION_LOCK_FILE: str = ".session_active.lock"
    DEFAULT_DEVICE_LOG_CAPTURE: Dict[str, Dict[str, Any]] = {
        "Ref2 Battery Camera": {
            "adb_serial": "S1B1D22607000063",
            "shell_command": "catch_log",
            "file_suffix": "camera",
            "stop_shell_command": "pkill -f catch_log",
            "reconnect_timeout_s": 300,
        },
        "HD Wired Indoor Camera": {
            "adb_serial": "S1W1D22605000105",
            "shell_command": "catch_log",
            "file_suffix": "camera",
            "stop_shell_command": "pkill -f catch_log",
            "reconnect_timeout_s": 300,
        },
        "2K Battery Doorbell Camera": {
            "adb_serial": "S1D1D32607000176",
            "shell_command": "catch_log",
            "file_suffix": "camera",
            "stop_shell_command": "pkill -f catch_log",
            "reconnect_timeout_s": 300,
        },
    }

    def __init__(
            self,
            app: Optional[str] = "igha",
            device_name: Optional[Union[str, List[str]]] = None,
            pairing_code: Optional[Union[str, List[str]]] = None,
            count: Optional[int] = None,
            room_name: Optional[str] = "Attic",
            gemini_api_key: Optional[str] = constants.GEMINI_API_KEY,
            component_id: Optional[str] = "1796386",
            udid: Optional[str] = None,
            wda_port: Optional[int] = None,
            mjpeg_port: Optional[int] = None,
            ios_version: Optional[str] = None,
            appium_url: Optional[str] = None,
            adb_serial: Optional[Union[str, List[str]]] = None,
            plug_name: Optional[Union[str, List[str]]] = None,
            **kwargs: Any
    ) -> None:
        self.project_name = (app or "igha").lower()
        self.device_name = device_name
        self.pairing_code = pairing_code
        self.count = count
        self.room_name = room_name or "Attic"
        self.device_names: List[str] = self._normalize_str_list(device_name)
        self.pairing_codes: List[str] = self._normalize_str_list(pairing_code)
        self.adb_serials: List[str] = self._normalize_str_list(adb_serial)
        self.plug_names: List[str] = self._normalize_str_list(plug_name)

        self._multi_session_requested: bool = any(
            v is not None for v in (udid, wda_port, mjpeg_port, ios_version, appium_url)
        )
        self._configure_process_appium_target(
            udid=udid,
            wda_port=wda_port,
            mjpeg_port=mjpeg_port,
            ios_version=ios_version,
            appium_url=appium_url,
        )
        self.udid = str(constants.IOS_CAPABILITIES.get("appium:udid", "") or "")
        self.wda_local_port = constants.IOS_CAPABILITIES.get("appium:wdaLocalPort", 8100)
        self.mjpeg_server_port = constants.IOS_CAPABILITIES.get("appium:mjpegServerPort")
        self._configure_process_session_log_dir()
        if self.adb_serials:
            initial_dev, _ = self.get_iteration_targets(1)
            self._sync_adb_reset_target(initial_dev, self.get_iteration_adb_serial(1))
        if self.plug_names:
            self._apply_plug_filter(self.plug_names)

        self.driver: Optional[webdriver.Remote] = None
        self.syslog_collector: Optional[SyslogCollector] = None
        self.syslog_file_paths: List[str] = []
        self.device_log_collector: Optional[DeviceLogCollector] = None
        self.device_log_file_paths: List[str] = []
        self.failure_screenshots: List[str] = []
        self.screen_recordings: List[str] = []
        self.last_error_message: Optional[str] = None
        self.component_id = component_id
        self.gemini_reporter = GeminiReporter(api_key=gemini_api_key)
        self.gha_version: str = "N/A" if self.project_name == "ighp" else "4.29.25"
        self.sample_app_version: str = "UNKNOWN" if self.project_name == "ighp" else "N/A"
        self.sdk_version: str = "UNKNOWN" if self.project_name == "ighp" else "N/A"
        self.ios_version: str = str(
            constants.IOS_CAPABILITIES.get("appium:platformVersion") or "iOS 17+")
        self.wifi_ssid: str = "Atelier320482024g"
        self.phone_ip: str = "192.168.1.113"
        self.router_gateway: str = "192.168.1.1"
        self.subnet_mask: str = "255.255.255.0"
        self.device_id: str = "UNKNOWN"
        self.serial_number: str = "UNKNOWN"
        self.software_version: str = "UNKNOWN"
        self.device_ip: str = "UNKNOWN"
        self.env_info_collected: bool = False
        self.drive_uploader: Optional[DriveUploader] = DriveUploader.create_if_enabled()
        host_short = socket.gethostname().split(".")[0]
        if self._multi_session_requested:
            udid_tag = self._short_udid_tag(self.udid, self.wda_local_port)
            self.drive_run_folder_name = f"{datetime.now():%Y%m%d_%H%M%S}_{self.project_name}_{udid_tag}_{host_short}"
        else:
            self.drive_run_folder_name = f"{datetime.now():%Y%m%d_%H%M%S}_{self.project_name}_{host_short}"
        self._drive_last_case_folder_id: Optional[str] = None
        self._container_paths: List[str] = []
        self._completed_case_dirs: List[str] = []
        self._csv_accepts_drive_url: bool = self._csv_accepts_param("drive_url")
        if self.drive_uploader and not self._csv_accepts_drive_url:
            logger.warning(
                "[DRIVE] csv_report.append_test_result_to_csv() has no 'drive_url' parameter; "
                "Drive links will be logged but not written to CSV / Google Sheet."
            )

    @staticmethod
    def _normalize_str_list(raw_value: Optional[Union[str, List[str]]]) -> List[str]:
        """Normalize an optional string or list argument (including comma-separated strings) into List[str]."""
        if isinstance(raw_value, list):
            items: List[str] = []
            for entry in raw_value:
                if "," in str(entry):
                    items.extend(part.strip() for part in str(entry).split(",") if part.strip())
                elif str(entry).strip():
                    items.append(str(entry).strip())
            return items
        if isinstance(raw_value, str) and raw_value.strip():
            if "," in raw_value:
                return [part.strip() for part in raw_value.split(",") if part.strip()]
            return [raw_value.strip()]
        return []

    @staticmethod
    def _short_udid_tag(udid: str, wda_port: Any = None) -> str:
        """Build a short filesystem-safe phone identifier tag for session folder names."""
        cleaned = re.sub(r"[^A-Za-z0-9]", "", udid or "")
        if cleaned:
            return cleaned[-6:]
        if wda_port is not None:
            return f"wda{wda_port}"
        return f"pid{os.getpid()}"

    @staticmethod
    def _detect_ios_device_metadata(udid: str) -> Dict[str, str]:
        """Best-effort query via `tidevice -u <udid> info` for ProductVersion and DeviceName."""
        info: Dict[str, str] = {}
        if not udid or not shutil.which("tidevice"):
            return info
        try:
            proc = subprocess.run(
                ["tidevice", "-u", udid, "info"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                errors="replace",
                timeout=4.0,
            )
            for raw_line in (proc.stdout or "").splitlines():
                if ":" not in raw_line:
                    continue
                k, v = raw_line.split(":", 1)
                key = k.strip()
                val = v.strip()
                if key in ("ProductVersion", "DeviceName") and val:
                    info[key] = val
        except Exception:
            pass
        return info

    def _configure_process_appium_target(
            self,
            udid: Optional[str],
            wda_port: Optional[int],
            mjpeg_port: Optional[int],
            ios_version: Optional[str],
            appium_url: Optional[str],
    ) -> None:
        """Isolate constants.IOS_CAPABILITIES and constants.APPIUM_SERVER_URL inside this OS process."""
        caps = dict(getattr(constants, "IOS_CAPABILITIES", {}) or {})
        orig_udid = str(caps.get("appium:udid", "") or "").strip()

        if udid and udid.strip():
            clean_udid = udid.strip()
            caps["appium:udid"] = clean_udid
            if ios_version and ios_version.strip():
                caps["appium:platformVersion"] = ios_version.strip()
            elif clean_udid != orig_udid:
                meta = self._detect_ios_device_metadata(clean_udid)
                if meta.get("ProductVersion"):
                    caps["appium:platformVersion"] = meta["ProductVersion"]
                else:
                    caps.pop("appium:platformVersion", None)
                if meta.get("DeviceName"):
                    caps["appium:deviceName"] = meta["DeviceName"]
        elif ios_version and ios_version.strip():
            caps["appium:platformVersion"] = ios_version.strip()

        if wda_port is not None:
            port_int = int(wda_port)
            caps["appium:wdaLocalPort"] = port_int
            if mjpeg_port is None:
                caps["appium:mjpegServerPort"] = (
                            9100 + (port_int - 8100)) if port_int >= 8000 else (port_int + 1000)

        if mjpeg_port is not None:
            caps["appium:mjpegServerPort"] = int(mjpeg_port)

        constants.IOS_CAPABILITIES = caps

        if appium_url and appium_url.strip():
            constants.APPIUM_SERVER_URL = appium_url.strip()

    @classmethod
    def _read_session_lock_pid(cls, session_dir: str) -> Optional[int]:
        """Return the PID stored in session_dir/.session_active.lock, or None if absent/invalid."""
        lock_file = os.path.join(session_dir, cls.ACTIVE_SESSION_LOCK_FILE)
        if not os.path.isfile(lock_file):
            return None
        try:
            with open(lock_file, "r", encoding="utf-8") as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """Return True if an OS process with `pid` is currently running."""
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False

    @classmethod
    def _is_session_dir_active(cls, session_dir: str, ignore_current_pid: bool = False) -> bool:
        """Return True when `session_dir` is actively owned by a live test runner process."""
        owner_pid = cls._read_session_lock_pid(session_dir)
        if owner_pid is None:
            return False
        if ignore_current_pid and owner_pid == os.getpid():
            return False
        return cls._is_pid_alive(owner_pid)

    def _mark_session_active(self) -> None:
        """Write current PID into SESSION_LOG_DIR/.session_active.lock so sibling runners never prune it."""
        try:
            os.makedirs(constants.SESSION_LOG_DIR, exist_ok=True)
            lock_path = os.path.join(constants.SESSION_LOG_DIR, self.ACTIVE_SESSION_LOCK_FILE)
            with open(lock_path, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
        except OSError as e:
            logger.debug(f"[SESSION LOCK] Could not write active lock file: {e}")

    def _release_session_active(self) -> None:
        """Remove SESSION_LOG_DIR/.session_active.lock upon runner completion."""
        lock_path = os.path.join(constants.SESSION_LOG_DIR, self.ACTIVE_SESSION_LOCK_FILE)
        try:
            if os.path.isfile(lock_path):
                owner_pid = self._read_session_lock_pid(constants.SESSION_LOG_DIR)
                if owner_pid in (None, os.getpid()):
                    os.remove(lock_path)
        except OSError:
            pass

    def _configure_process_session_log_dir(self) -> None:
        """Ensure constants.SESSION_LOG_DIR will not collide with another concurrent terminal."""
        current_dir = os.path.abspath(constants.SESSION_LOG_DIR)
        claimed_by_other = os.path.isdir(current_dir) and self._is_session_dir_active(
            current_dir, ignore_current_pid=True
        )
        if not self._multi_session_requested and not claimed_by_other:
            return

        logs_root = os.path.dirname(current_dir)
        ts_part = getattr(constants, "TIMESTAMP", None) or datetime.now().strftime("%Y%m%d_%H%M%S")
        udid_tag = self._short_udid_tag(self.udid, self.wda_local_port)
        candidate = os.path.join(logs_root, f"LOG_{ts_part}_{self.project_name}_{udid_tag}")
        if os.path.isdir(candidate) and self._is_session_dir_active(candidate,
                                                                    ignore_current_pid=True):
            candidate = f"{candidate}_{os.getpid()}"

        constants.SESSION_LOG_DIR = candidate
        constants.MAIN_LOG_DIR = os.path.join(candidate, "Main log")
        constants.ADDITIONAL_LOG_DIR = os.path.join(candidate, "Additional log")

    @staticmethod
    @contextmanager
    def _interprocess_lock(lock_name: str) -> Iterator[None]:
        """Cross-process file lock in system temp dir (serializes Xcode WDA launch & CSV writes)."""
        if fcntl is None:
            yield
            return
        lock_path = os.path.join(tempfile.gettempdir(), lock_name)
        lock_file = None
        try:
            lock_file = open(lock_path, "a+", encoding="utf-8")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass
        try:
            yield
        finally:
            if lock_file is not None:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
                try:
                    lock_file.close()
                except OSError:
                    pass

    def _sync_adb_reset_target(self, device: Optional[str], adb_serial: Optional[str]) -> None:
        """Pin constants.DEVICE_RESET_CONFIG in this process to the active iteration's camera ADB serial."""
        if not adb_serial:
            return
        existing = getattr(constants, "DEVICE_RESET_CONFIG", None)
        merged: Dict[str, Any] = {}
        if isinstance(existing, dict):
            for k, v in existing.items():
                if isinstance(v, dict):
                    merged[k] = dict(v)
        target_cfg = {"adb_serial": adb_serial}
        if device and str(device).strip():
            merged[str(device).strip()] = dict(merged.get(str(device).strip(), {}), **target_cfg)
        merged["*"] = dict(merged.get("*", {}), **target_cfg)
        constants.DEVICE_RESET_CONFIG = merged

    @staticmethod
    def _apply_plug_filter(plug_names: List[str]) -> None:
        """Restrict Smart Plug power-cycling in this process to the specified plug keyword(s)."""
        if not plug_names:
            return
        try:
            from page_object.iGHA.gha_commission_flow import GHACommissioningPageObject
            GHACommissioningPageObject.DEFAULT_PLUG_KEYWORDS = tuple(plug_names)
        except Exception as e:
            logger.warning(
                f"[SMART PLUG] Could not apply --plug_name filter {plug_names} to GHA: {e}")
        try:
            from page_object.iGHP.ghp_commission_flow import GHPCommissioningPageObject
            GHPCommissioningPageObject.DEFAULT_PLUG_KEYWORDS = tuple(plug_names)
        except Exception as e:
            logger.warning(
                f"[SMART PLUG] Could not apply --plug_name filter {plug_names} to GHP: {e}")

    @staticmethod
    def _csv_accepts_param(param: str) -> bool:
        """Check whether csv_report.append_test_result_to_csv accepts a given keyword."""
        try:
            return param in inspect.signature(csv_report.append_test_result_to_csv).parameters
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _extract_sdk_version_from_syslog(syslog_path: Optional[str]) -> Optional[str]:
        """Fallback: parse unredacted `Home API Version: <ver>` from captured iOS syslog if present."""
        if not syslog_path or not os.path.isfile(syslog_path):
            return None
        pattern = re.compile(r"Home API Version:\s*(?!<private>)([^\s\r\n,;]+)")
        try:
            with open(syslog_path, mode="r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if "Home API Version:" in line:
                        m = pattern.search(line)
                        if m and m.group(1).strip():
                            return m.group(1).strip()
        except Exception:
            pass
        return None

    @staticmethod
    def _safe_drive_name(text: str) -> str:
        """Sanitize a string for use as a Drive folder name."""
        return re.sub(r'[\\/:*?"<>|]+', "-", text).strip() or "unknown"

    @staticmethod
    def _get_free_disk_gb(path: str) -> float:
        """Return available free disk space in GiB for the filesystem containing path."""
        check_path = path if os.path.exists(path) else os.path.dirname(path) or "."
        if not os.path.exists(check_path):
            check_path = "."
        usage = shutil.disk_usage(check_path)
        return usage.free / (1024 ** 3)

    def _ensure_sufficient_disk_space(self, min_free_gb: Optional[float] = None) -> None:
        """Check local disk space and automatically prune oldest logs/sessions if below threshold."""
        threshold_gb = float(
            min_free_gb
            if min_free_gb is not None
            else getattr(constants, "MIN_FREE_DISK_GB", self.MIN_FREE_DISK_GB)
        )
        session_dir = os.path.abspath(constants.SESSION_LOG_DIR)
        try:
            free_gb = self._get_free_disk_gb(session_dir)
        except Exception as e:
            logger.debug(f"[DISK GUARD] Unable to query disk usage: {e}")
            return

        if free_gb >= threshold_gb:
            return

        logger.warning(
            f"[DISK GUARD] Low disk space detected: {free_gb:.2f} GB free "
            f"(< {threshold_gb:.1f} GB threshold). Pruning old local logs/artifacts..."
        )
        logs_root = os.path.dirname(session_dir)
        if os.path.isdir(logs_root):
            try:
                sibling_dirs = []
                for entry in os.listdir(logs_root):
                    full_path = os.path.abspath(os.path.join(logs_root, entry))
                    if full_path == session_dir or not os.path.isdir(full_path):
                        continue
                    if self._is_session_dir_active(full_path):
                        logger.info(
                            f"[DISK GUARD] Skipping active sibling session directory: {full_path}")
                        continue
                    try:
                        sibling_dirs.append((os.path.getmtime(full_path), full_path))
                    except OSError:
                        continue
                sibling_dirs.sort(key=lambda item: item[0])
                for _, old_session_path in sibling_dirs:
                    if self._get_free_disk_gb(session_dir) >= threshold_gb:
                        break
                    try:
                        shutil.rmtree(old_session_path, ignore_errors=True)
                        logger.info(
                            f"[DISK GUARD] Removed old session directory: {old_session_path}")
                    except Exception as rm_err:
                        logger.warning(
                            f"[DISK GUARD] Failed to remove {old_session_path}: {rm_err}")
            except Exception as scan_err:
                logger.warning(
                    f"[DISK GUARD] Error scanning sibling session directories: {scan_err}")

        if self._get_free_disk_gb(session_dir) < threshold_gb and len(
                self._completed_case_dirs) > 1:
            if self.drive_uploader:
                try:
                    logger.info(
                        "[DISK GUARD] Waiting for pending Drive uploads before pruning local case dirs...")
                    self.drive_uploader.wait_all(timeout_s=120)
                except Exception as wait_err:
                    logger.warning(f"[DISK GUARD] Drive wait warning before prune: {wait_err}")
            while len(self._completed_case_dirs) > 1 and self._get_free_disk_gb(
                    session_dir) < threshold_gb:
                oldest_case = self._completed_case_dirs.pop(0)
                if os.path.isdir(oldest_case):
                    try:
                        shutil.rmtree(oldest_case, ignore_errors=True)
                        logger.info(
                            f"[DISK GUARD] Removed uploaded local case directory: {oldest_case}")
                    except Exception as rm_err:
                        logger.warning(
                            f"[DISK GUARD] Failed to remove case dir {oldest_case}: {rm_err}")

        new_free_gb = self._get_free_disk_gb(session_dir)
        logger.info(f"[DISK GUARD] Disk space after cleanup: {new_free_gb:.2f} GB free.")

    def _drive_reserve_case_folder(
            self, iteration: int, test_status: str, device: Optional[str], class_name: str,
            test_name: str
    ) -> Tuple[Optional[str], str]:
        """Create the Drive folder for this test case. Returns (folder_id, url) or (None, '')."""
        if not self.drive_uploader:
            return None, ""
        folder_name = self._safe_drive_name(
            f"iter{iteration:03d}_{test_status}_{device or 'unknown'}_{class_name}.{test_name}"
        )
        reserved = self.drive_uploader.reserve_folder(self.drive_run_folder_name, folder_name)
        if not reserved:
            return None, ""
        folder_id, url = reserved
        logger.info(f"[DRIVE] Case folder: {url}")
        return folder_id, url

    def _drive_upload_case_dir(self, folder_id: Optional[str], case_dir: str, label: str) -> None:
        """Queue background upload of the whole case directory."""
        if not self.drive_uploader or not folder_id:
            return
        if self.drive_uploader.upload_async(folder_id, local_dir=case_dir, label=label):
            self._drive_last_case_folder_id = folder_id

    def _drive_finalize(self) -> None:
        """Upload app container + session-level logs, then wait for all uploads to finish."""
        if not self.drive_uploader:
            return
        try:
            reserved = self.drive_uploader.reserve_folder(self.drive_run_folder_name)
            run_folder_id, run_url = reserved if reserved else (None, "")
            if self._container_paths:
                target = self._drive_last_case_folder_id or run_folder_id
                if target:
                    self.drive_uploader.upload_async(
                        target, extra_paths=self._container_paths, label="app container")
            session_dir = constants.SESSION_LOG_DIR
            if run_folder_id and os.path.isdir(session_dir):
                session_files = [
                    os.path.join(session_dir, name)
                    for name in sorted(os.listdir(session_dir))
                    if not name.startswith(".") and os.path.isfile(os.path.join(session_dir, name))
                ]
                if session_files:
                    self.drive_uploader.upload_async(
                        run_folder_id, extra_paths=session_files, label="session logs")
            logger.info(f"[DRIVE] Run folder: {run_url}")
            logger.info("[DRIVE] Waiting for uploads to finish... (Press Ctrl+C to skip)")
            self.drive_uploader.wait_all(
                timeout_s=getattr(constants, "DRIVE_UPLOAD_WAIT_TIMEOUT_S", 1800))
        except KeyboardInterrupt:
            self.drive_uploader.abort()
            logger.warning("[DRIVE] Upload wait skipped by user.")
        except Exception as e:
            logger.warning(f"[DRIVE] Finalize failed: {e}")

    @staticmethod
    def _normalize_device_key(name: Optional[str]) -> str:
        """Normalize a device name for config lookup (case-insensitive, ignores stray commas)."""
        return (name or "").strip().strip(",").strip().lower()

    def _device_log_config_for(
            self, device: Optional[str], adb_serial_override: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Return the device-log capture config for this device, or None if not configured."""
        mapping = getattr(constants, "DEVICE_LOG_CAPTURE", self.DEFAULT_DEVICE_LOG_CAPTURE) or {}
        key = self._normalize_device_key(device)
        matched_cfg: Optional[Dict[str, Any]] = None
        for name, cfg in mapping.items():
            if key and self._normalize_device_key(name) == key and isinstance(cfg, dict):
                matched_cfg = dict(cfg)
                break
        if matched_cfg is not None:
            if adb_serial_override:
                matched_cfg["adb_serial"] = adb_serial_override
            return matched_cfg
        if adb_serial_override:
            return {
                "adb_serial": adb_serial_override,
                "shell_command": "catch_log",
                "file_suffix": "camera",
                "stop_shell_command": "pkill -f catch_log",
                "reconnect_timeout_s": 300,
            }
        return None

    def _start_device_log(
            self,
            device: Optional[str],
            case_main_log_dir: str,
            current_ts: str,
            adb_serial_override: Optional[str] = None,
    ) -> Optional[str]:
        """Start extra device-side log capture (e.g. `adb shell catch_log`) for configured devices."""
        cfg = self._device_log_config_for(device, adb_serial_override=adb_serial_override)
        if not cfg:
            return None
        adb = shutil.which("adb")
        if not adb:
            logger.warning(
                f"[DEVICE LOG] 'adb' not found in PATH; skipping device log for '{device}'.")
            return None
        serial = str(cfg.get("adb_serial") or "").strip()
        base = [adb] + (["-s", serial] if serial else [])
        shell_cmd = str(cfg.get("shell_command") or "catch_log").strip()
        stop_shell = str(cfg.get("stop_shell_command") or "").strip()
        suffix = str(cfg.get("file_suffix") or "device").strip()
        log_path = os.path.join(case_main_log_dir, f"LOG_{current_ts}_{suffix}.log")
        collector = DeviceLogCollector(
            output_path=log_path,
            command=base + ["shell", shell_cmd],
            state_command=base + ["get-state"],
            stop_command=(base + ["shell", stop_shell]) if stop_shell else None,
            reconnect_timeout_s=float(cfg.get("reconnect_timeout_s", 180)),
            label=f"DeviceLog:{suffix}",
        )
        try:
            collector.start()
        except Exception as e:
            logger.warning(f"[DEVICE LOG] Failed to start capture for '{device}': {e}")
            return None
        self.device_log_collector = collector
        self.device_log_file_paths.append(log_path)
        logger.info(f"[DEVICE LOG] '{device}': capturing `adb shell {shell_cmd}` -> {log_path}")
        return log_path

    def _stop_device_log(self) -> None:
        """Stop the extra device-side log capture if running."""
        if not self.device_log_collector:
            return
        try:
            self.device_log_collector.stop()
        except Exception as e:
            logger.warning(f"[DEVICE LOG] Failed to stop capture: {e}")
        finally:
            self.device_log_collector = None

    def get_iteration_targets(self, iteration: int) -> Tuple[Optional[str], Optional[str]]:
        """Resolve target device and its corresponding pairing code for the given iteration.
        Guarantees strict 1-to-1 mapping between device_names[idx] and pairing_codes[idx].
        """
        if not self.device_names:
            target_device = self.device_name if isinstance(self.device_name, str) else None
            target_code = self.pairing_code if isinstance(self.pairing_code, str) else None
            return target_device, target_code
        device_idx = (iteration - 1) % len(self.device_names)
        target_device = self.device_names[device_idx]
        if not self.pairing_codes:
            target_code = self.pairing_code if isinstance(self.pairing_code, str) else None
        elif device_idx < len(self.pairing_codes):
            target_code = self.pairing_codes[device_idx]
        else:
            target_code = self.pairing_codes[device_idx % len(self.pairing_codes)]
        return target_device, target_code

    def get_iteration_adb_serial(self, iteration: int) -> Optional[str]:
        """Resolve the target camera ADB serial for the given iteration when --adb_serial is specified."""
        if not self.adb_serials:
            return None
        if self.device_names:
            idx = (iteration - 1) % len(self.device_names)
        else:
            idx = (iteration - 1) % len(self.adb_serials)
        if idx < len(self.adb_serials):
            return self.adb_serials[idx]
        return self.adb_serials[idx % len(self.adb_serials)]

    @staticmethod
    def _list_online_adb_serials() -> List[str]:
        """Best-effort check of currently connected online ADB device serials."""
        adb = shutil.which("adb")
        if not adb:
            return []
        try:
            proc = subprocess.run(
                [adb, "devices"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                errors="replace",
                timeout=3.0,
            )
            serials: List[str] = []
            for raw_line in (proc.stdout or "").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("List of devices") or line.startswith("*"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    serials.append(parts[0])
            return serials
        except Exception:
            return []

    def setup(self) -> None:
        """Initialize Appium session and configure implicit wait."""
        self._mark_session_active()
        self._ensure_sufficient_disk_space()
        mode_str = f"{self.count} times" if self.count else "INFINITE LOOP (Press Ctrl+C to stop)"
        logger.info("=" * 65)
        logger.info(f"       STARTING TEST SESSION FOR APP: {self.project_name}        ")
        logger.info(f"       Execution Mode     : {mode_str}")
        logger.info(f"       Target iPhone UDID : {self.udid or '<auto>'}")
        logger.info(f"       WDA Local Port     : {self.wda_local_port}")
        if self.mjpeg_server_port is not None:
            logger.info(f"       WDA MJPEG Port     : {self.mjpeg_server_port}")
        logger.info(f"       Session Log Dir    : {constants.SESSION_LOG_DIR}")
        if self.device_names:
            logger.info(f"       Target Devices     : {', '.join(self.device_names)}")
        elif self.device_name:
            logger.info(f"       Target Device Name : {self.device_name}")
        if self.pairing_codes:
            logger.info(f"       Pairing Codes      : {', '.join(self.pairing_codes)}")
        elif self.pairing_code:
            logger.info(f"       Pairing Code       : {self.pairing_code}")
        if self.adb_serials:
            logger.info(f"       ADB Target Serials : {', '.join(self.adb_serials)}")
        if self.plug_names:
            logger.info(f"       Smart Plug Filter  : {', '.join(self.plug_names)}")
        if self.device_names and self.pairing_codes:
            logger.info("-" * 65)
            logger.info("       Device <===> Pairing Code Mapping:")
            for idx, d_name in enumerate(self.device_names):
                p_code = (
                    self.pairing_codes[idx]
                    if idx < len(self.pairing_codes)
                    else self.pairing_codes[idx % len(self.pairing_codes)]
                )
                adb_note = ""
                if self.adb_serials:
                    s_code = (
                        self.adb_serials[idx]
                        if idx < len(self.adb_serials)
                        else self.adb_serials[idx % len(self.adb_serials)]
                    )
                    adb_note = f"  [ADB: {s_code}]"
                logger.info(f"         [{idx + 1}] '{d_name}'  <===>  '{p_code}'{adb_note}")
            logger.info("-" * 65)
        if self.room_name:
            logger.info(f"       Assigned Room Name : {self.room_name}")
        if self.drive_uploader:
            logger.info(f"       Drive Run Folder   : {self.drive_run_folder_name}")
        targets = self.device_names or (
            [self.device_name] if isinstance(self.device_name, str) else [])
        first_adb = self.get_iteration_adb_serial(1)
        device_log_targets = [
            d for d in targets if self._device_log_config_for(d, adb_serial_override=first_adb)
        ]
        if device_log_targets:
            logger.info(f"       Device Log Capture : {', '.join(device_log_targets)}")
        if not self.adb_serials:
            online_adb = self._list_online_adb_serials()
            if len(online_adb) > 1:
                logger.warning(
                    f"[MULTI-DEVICE NOTICE] Detected {len(online_adb)} connected ADB devices {online_adb} "
                    "without --adb_serial. Post-test ADB reset will reset ALL connected ADB devices unless "
                    "you pass --adb_serial <serial>."
                )
        logger.info("=" * 65)
        logger.info(f"Connecting to Appium Server at: {constants.APPIUM_SERVER_URL}")
        active_bundle = (
            getattr(constants, "iGHP_SAMPLE_APP_BUNDLE_ID",
                    "com.google.homeplatform.sampleapp.gomezandres")
            if self.project_name == "ighp"
            else getattr(constants, "GHA_BUNDLE_ID", "com.google.Chromecast.enterprise")
        )
        constants.ACTIVE_APP_BUNDLE_ID = active_bundle
        options = AppiumOptions()
        options.load_capabilities(constants.IOS_CAPABILITIES)
        with self._interprocess_lock("ios_automation_wda_init.lock"):
            self.driver = webdriver.Remote(constants.APPIUM_SERVER_URL, options=options)
        try:
            setattr(self.driver, "_active_app_bundle_id", active_bundle)
        except Exception:
            pass
        implicit_wait = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
        self.driver.implicitly_wait(implicit_wait)
        logger.info(f"Global driver implicit wait configured to: {implicit_wait}s")

    def teardown(self) -> None:
        """Collect .xcappdata container, quit Appium WebDriver, and stop syslog / device log collectors.
        Newly pulled container paths are remembered in self._container_paths for Drive upload.
        """
        logger.info("=" * 65)
        logger.info("            TEARDOWN & COLLECTING ARTIFACTS                  ")
        logger.info("=" * 65)
        self._ensure_sufficient_disk_space()
        if self.driver:
            target_bundle = (
                constants.iGHP_SAMPLE_APP_BUNDLE_ID if self.project_name == "ighp" else constants.GHA_BUNDLE_ID
            )
            try:
                dest = logging_utils._current_main_log_dir or constants.SESSION_LOG_DIR
                before = set(os.listdir(dest)) if os.path.isdir(dest) else set()
                logging_utils.pull_ios_app_container(self.driver, target_bundle, dest)
                after = set(os.listdir(dest)) if os.path.isdir(dest) else set()
                self._container_paths = [os.path.join(dest, name) for name in
                                         sorted(after - before)]
                if self._container_paths:
                    logger.info(
                        f"[DRIVE] App container artifacts queued for upload: {self._container_paths}")
            except Exception as e:
                logger.error(f"Failed to pull {target_bundle} container: {e}")
            logger.info("Quitting Appium WebDriver...")
            self.driver.quit()
        if self.syslog_collector:
            self.syslog_collector.stop()
        self._stop_device_log()  # [DEVICE LOG]
        for extra in [os.path.join(constants.SESSION_LOG_DIR, "Main log"),
                      os.path.join(constants.SESSION_LOG_DIR, "Additional log")]:
            if os.path.exists(extra) and not os.listdir(extra):
                try:
                    os.rmdir(extra)
                except Exception:
                    pass
        logger.info("=" * 65)
        logger.info(f"Artifacts and Logs stored in: {constants.SESSION_LOG_DIR}")
        logger.info("=" * 65)

    def _get_project_suite(self) -> Tuple[Any, List[Type]]:
        """Resolve session instance and test classes for the target project."""
        if self.project_name == "ighp":
            session_instance = GHPSession(self.driver)
            ghp_test_cls = TestGHPHome
            if ghp_test_cls is None:
                from testcase.iGHP.test_home import TestGHPHome as _TestGHPHome
                ghp_test_cls = _TestGHPHome
            test_classes = [ghp_test_cls]
        else:
            session_instance = GHASession(self.driver)
            test_classes = [TestGHAHome]
        initial_device, initial_code = self.get_iteration_targets(1)
        session_instance.device_name = initial_device
        session_instance.pairing_code = initial_code
        session_instance.room_name = self.room_name
        return session_instance, test_classes

    def run(self) -> None:
        """Execute test suite across iterations with dynamically isolated log directories per run."""
        total_runs = 0
        total_passed = 0
        total_failed = 0
        iteration = 0
        session_start_time = time.time()
        try:
            self.setup()
            session_instance, test_classes = self._get_project_suite()
            while True:
                iteration += 1
                if self.count is not None and iteration > self.count:
                    break
                self._ensure_sufficient_disk_space()
                current_device, current_pairing_code = self.get_iteration_targets(iteration)
                current_adb_serial = self.get_iteration_adb_serial(iteration)
                if current_adb_serial:
                    self._sync_adb_reset_target(current_device, current_adb_serial)
                session_instance.device_name = current_device
                session_instance.pairing_code = current_pairing_code
                iter_label = f"{iteration}/{self.count}" if self.count else f"{iteration} (Infinite)"
                logger.info("\n" + "=" * 65)
                logger.info(f"               STARTING ITERATION #{iter_label}")
                logger.info(f"               TARGET DEVICE : {current_device}")
                logger.info(f"               PAIRING CODE  : {current_pairing_code}")
                if current_adb_serial:
                    logger.info(f"               ADB SERIAL    : {current_adb_serial}")
                logger.info("=" * 65)
                for test_cls in test_classes:
                    test_instance = test_cls(
                        session=session_instance,
                        device_name=current_device,
                        pairing_code=current_pairing_code,
                        room_name=self.room_name
                    )
                    class_name = test_cls.__name__
                    test_methods = [
                        getattr(test_instance, name)
                        for name in dir(test_instance)
                        if name.startswith("test_") and callable(getattr(test_instance, name))
                    ]
                    for test_method in test_methods:
                        test_name = test_method.__name__
                        total_runs += 1
                        parent_session_dir = constants.SESSION_LOG_DIR
                        child_folder_name = f"iter{iteration}_{class_name}_{test_name}"
                        case_dir = os.path.join(parent_session_dir, child_folder_name)
                        case_main_log_dir = os.path.join(case_dir, "Main log")
                        case_additional_log_dir = os.path.join(case_dir, "Additional log")
                        os.makedirs(case_main_log_dir, exist_ok=True)
                        os.makedirs(case_additional_log_dir, exist_ok=True)
                        logging_utils.set_current_test_dirs(case_main_log_dir,
                                                            case_additional_log_dir)
                        logger.info(
                            f"\n>>> [RUNNING] [Iter #{iteration}] {class_name}.{test_name} "
                            f"(Device: '{current_device}', Code: '{current_pairing_code}')"
                        )
                        logger.info(f">>> [TARGET DIR] {case_dir}")
                        current_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        case_syslog_path = None
                        if self.udid:
                            case_syslog_path = os.path.join(case_main_log_dir,
                                                            f"LOG_{current_ts}_syslog.log")
                            self.syslog_collector = SyslogCollector(self.udid, case_syslog_path)
                            self.syslog_collector.start()
                        self._start_device_log(
                            current_device,
                            case_main_log_dir,
                            current_ts,
                            adb_serial_override=current_adb_serial,
                        )
                        screen_recorder = ScreenRecorder(output_dir=case_additional_log_dir)
                        if self.driver:
                            try:
                                if screen_recorder.start_recording(self.driver):
                                    logger.info(
                                        f"[REC] Screen recording started for: {class_name}.{test_name}")
                                else:
                                    logger.warning(
                                        f"[REC] Screen recording NOT started for: {class_name}.{test_name}")
                            except Exception as rec_err:
                                logger.warning(f"Failed to start screen recording: {rec_err}")
                        self.device_id = "UNKNOWN"
                        self.serial_number = "UNKNOWN"
                        self.software_version = "UNKNOWN"
                        self.device_ip = "UNKNOWN"
                        screenshot_file = os.path.join(
                            case_additional_log_dir,
                            f"FAILED_iter{iteration}_{current_ts}_{class_name}_{test_name}.png"
                        )
                        BasePage.reset_failure_screenshot_state(
                            self.driver, target_path=screenshot_file, remove_existing=False
                        )
                        start_time = time.time()
                        start_dt = datetime.now()
                        test_status = "PASS"
                        test_error = ""
                        caught_exception = None
                        try:
                            test_method()
                            elapsed = time.time() - start_time
                            BasePage.reset_failure_screenshot_state(self.driver,
                                                                    remove_existing=True)
                            logger.info(
                                f">>> [PASS] [Iter #{iteration}] {class_name}.{test_name} ({elapsed:.2f}s)")
                            total_passed += 1
                        except Exception as e:
                            elapsed = time.time() - start_time
                            caught_exception = e
                            test_status = "FAIL"
                            test_error = str(e)
                            self.last_error_message = test_error
                            logger.error(
                                f">>> [FAIL] [Iter #{iteration}] {class_name}.{test_name} ({elapsed:.2f}s) - Error: {e}"
                            )
                            total_failed += 1
                            if self.driver:
                                captured_shot = getattr(self.driver, "_failure_screenshot_captured",
                                                        None)
                                if captured_shot and os.path.isfile(captured_shot):
                                    self.failure_screenshots.append(captured_shot)
                                    logger.info(
                                        f"Using failure screenshot captured at moment of failure: {captured_shot}"
                                    )
                                else:
                                    try:
                                        self.driver.save_screenshot(screenshot_file)
                                        self.failure_screenshots.append(screenshot_file)
                                        logger.info(
                                            f"Saved failure screenshot to: {screenshot_file}")
                                    except Exception as shot_err:
                                        logger.error(f"Failed to capture screenshot: {shot_err}")
                        finally:
                            end_dt = datetime.now()
                            video_filename = ""
                            if self.driver:
                                rec_label = f"RECORD_iter{iteration}_{current_ts}_{class_name}_{test_name}"
                                try:
                                    saved_video = screen_recorder.stop_recording(
                                        self.driver, test_name=rec_label
                                    )
                                    if saved_video and os.path.exists(saved_video):
                                        self.screen_recordings.append(saved_video)
                                        video_filename = os.path.basename(saved_video)
                                        logger.info(
                                            f"[REC] Screen recording saved: {video_filename}")
                                except Exception as rec_stop_err:
                                    logger.warning(
                                        f"Failed to save screen recording: {rec_stop_err}")
                            if self.syslog_collector:
                                self.syslog_collector.stop()
                                if case_syslog_path and os.path.exists(case_syslog_path):
                                    self.syslog_file_paths.append(case_syslog_path)
                                self.syslog_collector = None
                            self._stop_device_log()  # [DEVICE LOG]
                            if self.project_name == "ighp":
                                drv_ver = getattr(self.driver, "_ghp_version_info",
                                                  None) if self.driver else None
                                if isinstance(drv_ver, dict):
                                    s_ver = str(drv_ver.get("sample_app_version") or "").strip()
                                    k_ver = str(drv_ver.get("sdk_version") or "").strip()
                                    if s_ver and s_ver.upper() not in ("UNKNOWN",
                                                                       "UNKNOWN / NOT INSTALLED"):
                                        self.sample_app_version = s_ver
                                    if k_ver and k_ver.upper() not in ("UNKNOWN",
                                                                       "UNKNOWN / NOT INSTALLED"):
                                        self.sdk_version = k_ver
                                sess_s_ver = str(getattr(session_instance, "sample_app_version",
                                                         "") or "").strip()
                                sess_k_ver = str(
                                    getattr(session_instance, "sdk_version", "") or "").strip()
                                if (
                                        sess_s_ver
                                        and sess_s_ver.upper() not in ("UNKNOWN",
                                                                       "UNKNOWN / NOT INSTALLED")
                                        and self.sample_app_version.upper() in ("", "UNKNOWN")
                                ):
                                    self.sample_app_version = sess_s_ver
                                if (
                                        sess_k_ver
                                        and sess_k_ver.upper() not in ("UNKNOWN",
                                                                       "UNKNOWN / NOT INSTALLED")
                                        and self.sdk_version.upper() in ("", "UNKNOWN")
                                ):
                                    self.sdk_version = sess_k_ver

                            if not self.env_info_collected and self.driver:
                                try:
                                    logger.info(
                                        "[ENV INFO] First testcase completed, collecting full environment info...")
                                    env_info = log_all_version_information(self.driver)
                                    if isinstance(env_info, dict):
                                        if self.project_name == "ighp":
                                            self.gha_version = "N/A"
                                            env_sample = str(
                                                env_info.get("sample_app_version")
                                                or env_info.get("sample_version")
                                                or ""
                                            ).strip()
                                            env_sdk = str(env_info.get("sdk_version") or "").strip()
                                            if env_sample and env_sample.upper() not in ("UNKNOWN",
                                                                                         "UNKNOWN / NOT INSTALLED"):
                                                self.sample_app_version = env_sample
                                            if env_sdk and env_sdk.upper() not in ("UNKNOWN",
                                                                                   "UNKNOWN / NOT INSTALLED"):
                                                self.sdk_version = env_sdk
                                        else:
                                            if "gha_version" in env_info:
                                                self.gha_version = str(env_info["gha_version"])
                                            self.sample_app_version = "N/A"
                                            self.sdk_version = "N/A"
                                        if "device_info" in env_info and "platform_version" in \
                                                env_info["device_info"]:
                                            self.ios_version = str(
                                                env_info["device_info"]["platform_version"])
                                        if "wifi_info" in env_info and isinstance(
                                                env_info["wifi_info"], dict):
                                            w_info = env_info["wifi_info"]
                                            self.wifi_ssid = str(w_info.get("ssid", self.wifi_ssid))
                                            self.phone_ip = str(
                                                w_info.get("ip_address", self.phone_ip))
                                            self.router_gateway = str(
                                                w_info.get("router_gateway", self.router_gateway))
                                            self.subnet_mask = str(
                                                w_info.get("subnet_mask", self.subnet_mask))
                                    if self.project_name == "ighp" and self.sdk_version.upper() in (
                                            "", "UNKNOWN", "UNKNOWN / NOT INSTALLED"
                                    ):
                                        syslog_sdk = self._extract_sdk_version_from_syslog(
                                            case_syslog_path)
                                        if syslog_sdk:
                                            self.sdk_version = syslog_sdk
                                    self.env_info_collected = True
                                    if self.project_name == "ighp":
                                        logger.info(
                                            f"[ENV INFO] Initialized: Sample App {self.sample_app_version} | "
                                            f"SDK {self.sdk_version} | iOS {self.ios_version} | "
                                            f"SSID {self.wifi_ssid} | Phone IP {self.phone_ip} | Gateway {self.router_gateway}"
                                        )
                                    else:
                                        logger.info(
                                            f"[ENV INFO] Initialized: GHA {self.gha_version} | iOS {self.ios_version} | "
                                            f"SSID {self.wifi_ssid} | Phone IP {self.phone_ip} | Gateway {self.router_gateway}"
                                        )
                                except Exception as env_err:
                                    logger.warning(
                                        f"Failed to collect version information: {env_err}")
                                    self.env_info_collected = True
                            elif self.driver:
                                try:
                                    logger.info(
                                        f"[ENV INFO] [Iter #{iteration}] Fetching latest Wi-Fi details for current run...")
                                    w_info = get_wifi_information(self.driver)
                                    if isinstance(w_info, dict):
                                        self.wifi_ssid = str(w_info.get("ssid", self.wifi_ssid))
                                        self.phone_ip = str(w_info.get("ip_address", self.phone_ip))
                                        self.router_gateway = str(
                                            w_info.get("router_gateway", self.router_gateway))
                                        self.subnet_mask = str(
                                            w_info.get("subnet_mask", self.subnet_mask))
                                    logger.info(
                                        f"[ENV INFO] [Iter #{iteration}] Updated Wi-Fi: SSID='{self.wifi_ssid}' | "
                                        f"Phone IP='{self.phone_ip}' | Gateway='{self.router_gateway}'"
                                    )
                                except Exception as wifi_err:
                                    logger.warning(
                                        f"Failed to refresh Wi-Fi info for iteration #{iteration}: {wifi_err}")
                            dev_tech = (
                                    getattr(self.driver, "device_tech_info", None)
                                    or getattr(test_instance, "device_tech_info", None)
                                    or getattr(session_instance, "device_tech_info", None)
                                    or getattr(getattr(test_instance, "session", None),
                                               "device_tech_info", None)
                            )
                            if isinstance(dev_tech, dict) and dev_tech:
                                for key, val in dev_tech.items():
                                    if val and str(val).upper() != "UNKNOWN":
                                        if key in ("device_id", "Device ID"):
                                            self.device_id = str(val)
                                        elif key in ("serial_number", "serial_no", "Serial Number"):
                                            self.serial_number = str(val)
                                        elif key in ("software_version", "Software Version",
                                                     "firmware_version"):
                                            self.software_version = str(val)
                                        elif key in ("device_ip", "camera_ip", "Device IP",
                                                     "ip_address"):
                                            self.device_ip = str(val)
                                logger.info(
                                    f"[TARGET DEVICE CAPTURED] ID: {self.device_id} | SN: {self.serial_number} | "
                                    f"FW: {self.software_version} | IP: {self.device_ip}"
                                )
                            else:
                                logger.warning(
                                    f"[TARGET DEVICE] No device_tech_info found! (dev_tech={dev_tech})"
                                )
                            if test_status == "PASS":
                                failure_stage = "No errors"
                            else:
                                failure_stage = extract_failure_stage(caught_exception)
                                logger.info(f"[FAILURE ATTRIBUTION] Failing step: {failure_stage}")
                            # [DRIVE] Reserve the Drive folder first so its URL can go into CSV / Sheet.
                            drive_folder_id, drive_url = self._drive_reserve_case_folder(
                                iteration, test_status, current_device, class_name, test_name
                            )
                            csv_kwargs = dict(
                                test_name=f"{class_name}.{test_name}",
                                device_name=current_device or "iPhone 11 Pro",
                                gha_version=self.gha_version,
                                status=test_status,
                                start_time=start_dt,
                                end_time=end_dt,
                                error_msg=test_error,
                                iteration=iteration,
                                ios_version=self.ios_version,
                                wifi_ssid=self.wifi_ssid,
                                failure_stage=failure_stage,
                                log_dir=child_folder_name,
                                video_file=video_filename,
                                host_machine=socket.gethostname(),
                                phone_ip=self.phone_ip,
                                router_gateway=self.router_gateway,
                                subnet_mask=self.subnet_mask,
                                device_id=self.device_id,
                                serial_number=self.serial_number,
                                software_version=self.software_version,
                                device_ip=self.device_ip
                            )
                            accepts_var_kw = False
                            try:
                                accepts_var_kw = any(
                                    p.kind == inspect.Parameter.VAR_KEYWORD
                                    for p in inspect.signature(
                                        csv_report.append_test_result_to_csv).parameters.values()
                                )
                            except (TypeError, ValueError):
                                accepts_var_kw = False
                            if self._csv_accepts_param("app") or accepts_var_kw:
                                csv_kwargs["app"] = self.project_name
                            if self._csv_accepts_param("sample_app_version") or accepts_var_kw:
                                csv_kwargs["sample_app_version"] = self.sample_app_version
                            if self._csv_accepts_param("sdk_version") or accepts_var_kw:
                                csv_kwargs["sdk_version"] = self.sdk_version
                            if self._csv_accepts_drive_url:
                                csv_kwargs["drive_url"] = drive_url
                            try:
                                with self._interprocess_lock("ios_automation_csv_report.lock"):
                                    csv_report.append_test_result_to_csv(**csv_kwargs)
                            except Exception as csv_err:
                                logger.warning(
                                    f"Failed to record result to CSV / Google Sheet: {csv_err}")
                            self._drive_upload_case_dir(drive_folder_id, case_dir,
                                                        label=child_folder_name)
                            self._completed_case_dirs.append(case_dir)
        except KeyboardInterrupt:
            logger.info(
                "\n[INTERRUPT] Received KeyboardInterrupt (Ctrl+C). Terminating test execution gracefully...")
        finally:
            total_duration = time.time() - session_start_time
            self.teardown()
            completed_iterations = iteration if self.count is None else min(iteration, self.count)
            logger.info("\n" + "=" * 65)
            logger.info(
                f"Final Execution Summary ({completed_iterations} total iterations completed):")
            logger.info(f"  Total Test Executions : {total_runs}")
            logger.info(f"  Total Passed          : {total_passed}")
            logger.info(f"  Total Failed          : {total_failed}")
            logger.info(f"  Total Duration        : {total_duration:.2f}s")
            logger.info("=" * 65)
            self._drive_finalize()
            self._release_session_active()
        if total_failed > 0 and self.count is not None:
            exit(1)
