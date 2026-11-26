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

try:
    from page_object.Partner.ATT.att_common import resolve_att_bundle_id
    from page_object.Partner.ATT.att_session import ATTSession
except ImportError:  # pragma: no cover - fallback when ATT package is absent
    ATTSession = None  # type: ignore[assignment]
    resolve_att_bundle_id = None  # type: ignore[assignment]
from testcase.iGHA.test_home import TestGHAHome

try:
    from testcase.iGHP.test_home import TestGHPHome
except ImportError:  # pragma: no cover - fallback when testcase is partially mocked
    TestGHPHome = None  # type: ignore[assignment]
try:
    from testcase.Partner.ATT.test_home import TestATTHome
except ImportError:  # pragma: no cover - fallback when testcase is partially mocked
    TestATTHome = None  # type: ignore[assignment]
from utils import logging_utils
from utils.drive_uploader import DriveUploader
from utils.environment_utils import log_all_version_information, get_wifi_information
from utils.screen_recorder import ScreenRecorder
from utils.gemini_reporter import GeminiReporter
from utils import csv_report

logger = logging_utils.get_logger(__name__, "runner")


def extract_failure_stage(exc: Exception) -> str:
    """Automatically extract failing method name from exception traceback without manual tagging."""
    if not exc:
        return "UNKNOWN"
    explicit_stage = str(getattr(exc, "failure_stage", "") or "").strip()
    if explicit_stage:
        return explicit_stage
    if not hasattr(exc, "__traceback__"):
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
    VALID_APPS: Tuple[str, ...] = ("igha", "ighp", "att")
    MIN_FREE_DISK_GB: float = 5.0
    ACTIVE_SESSION_LOCK_FILE: str = ".session_active.lock"
    DEFAULT_DEVICE_LOG_CAPTURE: Dict[str, Dict[str, Any]] = {
        "Ref2 Battery Camera": {
            "adb_serial": "S1B1D22607000063",
            "shell_command": "catch_log",
            "file_suffix": "camera",  # -> Main log/LOG_<ts>_camera.log
            "stop_shell_command": "pkill -f catch_log",
            "reconnect_timeout_s": 300,
        },
        "HD Wired Indoor Camera": {
            "adb_serial": "S1W1D22605000105",
            "shell_command": "catch_log",
            "file_suffix": "camera",  # -> Main log/LOG_<ts>_camera.log
            "stop_shell_command": "pkill -f catch_log",
            "reconnect_timeout_s": 300,
        },
        "2K Battery Doorbell Camera": {
            "adb_serial": "S1D1D32607000176",
            "shell_command": "catch_log",
            "file_suffix": "camera",  # -> Main log/LOG_<ts>_camera.log
            "stop_shell_command": "pkill -f catch_log",
            "reconnect_timeout_s": 300,
        },
    }

    def __init__(
            self,
            app: Optional[Union[str, List[str]]] = "igha",
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
        raw_apps = [item.lower() for item in self._normalize_str_list(app)]
        if not raw_apps:
            raw_apps = ["igha"]
        invalid_apps = [item for item in raw_apps if item not in self.VALID_APPS]
        if invalid_apps:
            raise ValueError(
                f"Unsupported app(s): {invalid_apps}. Valid choices: {list(self.VALID_APPS)}"
            )
        self.app_names: List[str] = list(dict.fromkeys(raw_apps))
        self.project_name: str = self.app_names[0]
        self.project_tag: str = "_".join(self.app_names)
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
        self._session_ts: str = (
                getattr(constants, "TIMESTAMP", None) or datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        self._app_session_dirs: Dict[str, str] = {}
        self._configure_process_session_log_dir()
        if self.adb_serials:
            initial_dev, _ = self.get_iteration_targets(1)
            self._sync_adb_reset_target(initial_dev, self.get_iteration_adb_serial(1))
        if self.plug_names:
            self._apply_plug_filter(self.plug_names)

        self.driver: Optional[webdriver.Remote] = None
        self.syslog_collector: Optional[SyslogCollector] = None
        self.syslog_file_paths: List[str] = []
        self.device_log_collector: Optional[DeviceLogCollector] = None  # [DEVICE LOG]
        self.device_log_file_paths: List[str] = []  # [DEVICE LOG]
        self.failure_screenshots: List[str] = []
        self.screen_recordings: List[str] = []
        self.last_error_message: Optional[str] = None
        self.component_id = component_id
        self.gemini_reporter = GeminiReporter(api_key=gemini_api_key)
        self._app_versions: Dict[str, Dict[str, str]] = {
            app_item: self._default_versions_for_app(app_item)
            for app_item in self.app_names
        }
        self._env_collected_by_app: Dict[str, bool] = {app_item: False for app_item in
                                                       self.app_names}
        self._app_stats: Dict[str, Dict[str, int]] = {
            app_item: {"runs": 0, "passed": 0, "failed": 0}
            for app_item in self.app_names
        }
        self._apply_app_version_fields(self.project_name)
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
        self._drive_uploaders_by_app: Dict[str, Optional[DriveUploader]] = {
            app_item: self._create_drive_uploader_for_app(app_item)
            for app_item in self.app_names
        }
        self.drive_uploader: Optional[DriveUploader] = self._drive_uploaders_by_app.get(
            self.project_name
        )
        host_short = socket.gethostname().split(".")[0]
        drive_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        udid_tag = self._short_udid_tag(self.udid, self.wda_local_port)
        use_udid_in_drive = self._multi_session_requested or (
                bool(self.udid) and len(self.app_names) > 1
        )
        self._drive_run_folders_by_app: Dict[str, str] = {
            app_item: (
                f"{drive_ts}_{app_item}_{udid_tag}_{host_short}"
                if use_udid_in_drive
                else f"{drive_ts}_{app_item}_{host_short}"
            )
            for app_item in self.app_names
        }
        self.drive_run_folder_name: str = self._drive_run_folders_by_app[self.project_name]
        self._drive_last_case_folder_id: Optional[str] = None
        self._drive_last_case_folder_id_by_app: Dict[str, Optional[str]] = {}
        self._container_paths: List[str] = []
        self._container_paths_by_app: Dict[str, List[str]] = {}
        self._completed_case_dirs: List[str] = []
        self._csv_accepts_drive_url: bool = self._csv_accepts_param("drive_url")
        if self.drive_uploader and not self._csv_accepts_drive_url:
            logger.warning(
                "[DRIVE] csv_report.append_test_result_to_csv() has no 'drive_url' parameter; "
                "Drive links will be logged but not written to CSV / Google Sheet."
            )

    @staticmethod
    def _default_versions_for_app(app_name: str) -> Dict[str, str]:
        app_key = (app_name or "igha").lower()
        return {
            "gha_version": "N/A" if app_key in ("ighp", "att") else "4.29.25",
            "att_version": "UNKNOWN" if app_key == "att" else "N/A",
            "sample_app_version": "UNKNOWN" if app_key == "ighp" else "N/A",
            "sdk_version": "UNKNOWN" if app_key == "ighp" else "N/A",
        }

    def _apply_app_version_fields(self, app_name: str) -> None:
        versions = self._app_versions.setdefault(app_name, self._default_versions_for_app(app_name))
        self.gha_version = versions.get("gha_version", "N/A")
        self.att_version = versions.get("att_version", "N/A")
        self.sample_app_version = versions.get("sample_app_version", "N/A")
        self.sdk_version = versions.get("sdk_version", "N/A")

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
                    # Let Appium XCUITest query the real iPhone directly rather than sending another phone's iOS version.
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

    @staticmethod
    def _create_drive_uploader_for_app(app_name: str) -> Optional[DriveUploader]:
        """Resolve per-app DriveUploader when supported, falling back to 0-arg create_if_enabled()."""
        factory = getattr(DriveUploader, "create_if_enabled", None)
        if not callable(factory):
            return None
        try:
            params = inspect.signature(factory).parameters
            if "app_name" in params:
                return factory(app_name=app_name)
        except (TypeError, ValueError):
            pass
        return factory()

    def _mark_session_active(self, target_dir: Optional[str] = None) -> None:
        """Write current PID into `.session_active.lock` so sibling runners never prune it."""
        session_dir = os.path.abspath(target_dir or constants.SESSION_LOG_DIR)
        try:
            os.makedirs(session_dir, exist_ok=True)
            lock_path = os.path.join(session_dir, self.ACTIVE_SESSION_LOCK_FILE)
            with open(lock_path, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
        except OSError as e:
            logger.debug(f"[SESSION LOCK] Could not write active lock file: {e}")

    def _release_session_active(self) -> None:
        """Remove `.session_active.lock` from all active session directories upon runner completion."""
        seen = set()
        candidates = list(self._app_session_dirs.values()) + [constants.SESSION_LOG_DIR]
        for session_dir in candidates:
            norm = os.path.abspath(session_dir)
            if norm in seen:
                continue
            seen.add(norm)
            lock_path = os.path.join(norm, self.ACTIVE_SESSION_LOCK_FILE)
            try:
                if os.path.isfile(lock_path):
                    owner_pid = self._read_session_lock_pid(norm)
                    if owner_pid in (None, os.getpid()):
                        os.remove(lock_path)
            except OSError:
                pass

    def _switch_session_log_dir_for_app(self, app_name: str) -> None:
        """Point `constants.SESSION_LOG_DIR` (and Main/Additional subdirs) to `app_name`'s folder."""
        app_key = (app_name or self.project_name or "igha").lower()
        target_dir = self._app_session_dirs.get(app_key)
        if not target_dir:
            return
        constants.SESSION_LOG_DIR = target_dir
        constants.MAIN_LOG_DIR = os.path.join(target_dir, "Main log")
        constants.ADDITIONAL_LOG_DIR = os.path.join(target_dir, "Additional log")
        self._mark_session_active(target_dir)

    def _configure_process_session_log_dir(self) -> None:
        """Ensure each app in this run gets its own local log folder and avoids terminal collisions."""
        current_dir = os.path.abspath(constants.SESSION_LOG_DIR)
        claimed_by_other = os.path.isdir(current_dir) and self._is_session_dir_active(
            current_dir, ignore_current_pid=True
        )
        if len(self.app_names) == 1 and not self._multi_session_requested and not claimed_by_other:
            self._app_session_dirs[self.project_name] = current_dir
            return

        logs_root = os.path.dirname(current_dir)
        ts_part = self._session_ts
        udid_tag = self._short_udid_tag(self.udid, self.wda_local_port)
        base_name = os.path.basename(current_dir)
        use_udid_suffix = (
                self._multi_session_requested
                or claimed_by_other
                or (udid_tag and f"_{udid_tag}" in base_name)
                or (bool(self.udid) and len(self.app_names) > 1)
        )

        for app_item in self.app_names:
            dir_name = (
                f"LOG_{ts_part}_{app_item}_{udid_tag}"
                if use_udid_suffix
                else f"LOG_{ts_part}_{app_item}"
            )
            candidate = os.path.join(logs_root, dir_name)
            if os.path.isdir(candidate) and self._is_session_dir_active(candidate,
                                                                        ignore_current_pid=True):
                candidate = f"{candidate}_{os.getpid()}"
            self._app_session_dirs[app_item] = os.path.abspath(candidate)

        if len(self.app_names) > 1 and current_dir not in self._app_session_dirs.values():
            if os.path.isdir(current_dir):
                try:
                    for sub in ("Main log", "Additional log"):
                        sub_p = os.path.join(current_dir, sub)
                        if os.path.isdir(sub_p) and not os.listdir(sub_p):
                            os.rmdir(sub_p)
                    if not os.listdir(current_dir):
                        os.rmdir(current_dir)
                except OSError:
                    pass

        self._switch_session_log_dir_for_app(self.project_name)

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
    def _call_env_fn(fn: Any, driver: Any, return_to_app: bool) -> Any:
        """Invoke `log_all_version_information` / `get_wifi_information` with `return_to_app` when supported."""
        try:
            params = inspect.signature(fn).parameters
            if "return_to_app" in params or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            ):
                return fn(driver, return_to_app=return_to_app)
        except (TypeError, ValueError):
            pass
        return fn(driver)

    WDA_ERROR_SIGNATURES: Tuple[str, ...] = (
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

    def _preflight_heal_wda_and_dismiss_system_modals(self, current_app: str) -> None:
        """Verify WDA session is alive (rebuilding under lock if dead), unlock screen, and clear stray modals."""
        if self.driver is None:
            return
        # 1. WDA session health probe & locked in-place rebuild
        if hasattr(self.driver, "get_window_size"):
            try:
                self.driver.get_window_size()
            except Exception as probe_err:
                if any(sig in str(probe_err) for sig in self.WDA_ERROR_SIGNATURES):
                    logger.warning(
                        f"[PRE-FLIGHT] Dead WDA session detected before iteration ({probe_err}); "
                        "rebuilding Appium WebDriver session under lock..."
                    )
                    try:
                        self.driver.quit()
                    except Exception:
                        pass
                    try:
                        options = AppiumOptions()
                        options.load_capabilities(constants.IOS_CAPABILITIES)
                        with self._interprocess_lock("ios_automation_wda_init.lock"):
                            new_driver = webdriver.Remote(constants.APPIUM_SERVER_URL,
                                                          options=options)
                        new_driver.implicitly_wait(
                            getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
                        )
                        self.driver.__dict__.update(new_driver.__dict__)
                        self._activate_app_context(current_app)
                        logger.info(
                            "[PRE-FLIGHT] Successfully rebuilt Appium/WDA session in-place.")
                    except Exception as rebuild_err:
                        logger.error(f"[PRE-FLIGHT] Failed rebuilding WDA session: {rebuild_err}")
                        return

        # 2. Ensure iPhone screen is unlocked
        if hasattr(self.driver, "is_locked"):
            try:
                if self.driver.is_locked():
                    helper = BasePage.__new__(BasePage)
                    helper.driver = self.driver
                    helper._logger = logger
                    helper._unlock_device_if_locked()
            except Exception:
                pass

        # 3. Dismiss any lingering SpringBoard system alert or leftover HomeUIService / Safari sheet (<50ms when clean)
        if hasattr(self.driver, "execute_script"):
            try:
                btns = self.driver.execute_script("mobile: alert", {"action": "getButtons"})
                if isinstance(btns, (list, tuple)) and btns:
                    logger.warning(
                        f"[PRE-FLIGHT] Dismissing leftover system alert (buttons={list(btns)})...")
                    try:
                        self.driver.execute_script("mobile: alert", {"action": "dismiss"})
                    except Exception:
                        try:
                            self.driver.execute_script("mobile: alert", {"action": "accept"})
                        except Exception:
                            pass
            except Exception:
                pass

        if hasattr(self.driver, "find_elements") and hasattr(self.driver, "implicitly_wait"):
            default_wait = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
            try:
                self.driver.implicitly_wait(0)
                pred_by = "-ios predicate string"
                sheet_markers = self.driver.find_elements(
                    pred_by,
                    '(type == "XCUIElementTypeOther" AND name IN {"PRXCardContainerView", "TopBrowserBar"}) '
                    'OR (type == "XCUIElementTypeWebView")',
                )
                if any(getattr(m, "is_displayed", lambda: False)() for m in sheet_markers):
                    close_btns = self.driver.find_elements(
                        pred_by,
                        'type == "XCUIElementTypeButton" AND ('
                        'name IN {"Cancel", "Close", "xmark", "Done", "取消", "完成", "關閉"} '
                        'OR label IN {"Cancel", "Close", "Done", "取消", "完成", "關閉"})',
                    )
                    for cb in close_btns:
                        if getattr(cb, "is_displayed", lambda: False)():
                            logger.warning(
                                "[PRE-FLIGHT] Closing leftover Apple/Safari modal sheet before iteration...")
                            try:
                                cb.click()
                                time.sleep(0.8)
                            except Exception:
                                pass
                            break
            except Exception:
                pass
            finally:
                try:
                    self.driver.implicitly_wait(default_wait)
                except Exception:
                    pass

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
            self,
            iteration: int,
            test_status: str,
            device: Optional[str],
            class_name: str,
            test_name: str,
            app_name: Optional[str] = None,
    ) -> Tuple[Optional[str], str]:
        """Create the Drive folder for this test case. Returns (folder_id, url) or (None, '')."""
        app_key = (app_name or self.project_name or "igha").lower()
        uploader = self._drive_uploaders_by_app.get(app_key, self.drive_uploader)
        if not uploader:
            return None, ""
        run_folder = self._drive_run_folders_by_app.get(app_key, self.drive_run_folder_name)
        folder_name = self._safe_drive_name(
            f"iter{iteration:03d}_{test_status}_{device or 'unknown'}_{class_name}.{test_name}"
        )
        reserved = uploader.reserve_folder(run_folder, folder_name)
        if not isinstance(reserved, (tuple, list)) or len(reserved) != 2:
            return None, ""
        folder_id, url = reserved
        logger.info(f"[DRIVE] [{app_key}] Case folder: {url}")
        return folder_id, url

    def _drive_upload_case_dir(
            self,
            folder_id: Optional[str],
            case_dir: str,
            label: str,
            app_name: Optional[str] = None,
    ) -> None:
        """Queue background upload of the whole case directory into the app's Drive folder."""
        app_key = (app_name or self.project_name or "igha").lower()
        uploader = self._drive_uploaders_by_app.get(app_key, self.drive_uploader)
        if not uploader or not folder_id:
            return
        if uploader.upload_async(folder_id, local_dir=case_dir, label=label):
            self._drive_last_case_folder_id = folder_id
            self._drive_last_case_folder_id_by_app[app_key] = folder_id

    def _drive_finalize(self) -> None:
        """Upload per-app containers & session-level logs, then wait for all uploads to finish."""
        active_uploaders: List[DriveUploader] = []
        seen_ids = set()
        for app_item in self.app_names:
            up = self._drive_uploaders_by_app.get(app_item, self.drive_uploader)
            if up and id(up) not in seen_ids:
                seen_ids.add(id(up))
                active_uploaders.append(up)
        if not active_uploaders:
            return

        try:
            for app_item in self.app_names:
                up = self._drive_uploaders_by_app.get(app_item, self.drive_uploader)
                if not up:
                    continue
                run_folder = self._drive_run_folders_by_app.get(app_item,
                                                                self.drive_run_folder_name)
                reserved = up.reserve_folder(run_folder)
                run_folder_id, run_url = reserved if reserved else (None, "")
                app_containers = self._container_paths_by_app.get(app_item) or (
                    self._container_paths if app_item == self.project_name else []
                )
                if app_containers:
                    target = (
                            self._drive_last_case_folder_id_by_app.get(app_item)
                            or self._drive_last_case_folder_id
                            or run_folder_id
                    )
                    if target:
                        up.upload_async(
                            target, extra_paths=app_containers, label=f"{app_item} app container"
                        )
                session_dir = self._app_session_dirs.get(app_item, constants.SESSION_LOG_DIR)
                if run_folder_id and os.path.isdir(session_dir):
                    session_files = [
                        os.path.join(session_dir, name)
                        for name in sorted(os.listdir(session_dir))
                        if
                        not name.startswith(".") and os.path.isfile(os.path.join(session_dir, name))
                    ]
                    if session_files:
                        up.upload_async(
                            run_folder_id, extra_paths=session_files,
                            label=f"{app_item} session logs"
                        )
                logger.info(f"[DRIVE] [{app_item}] Run folder: {run_url}")
            logger.info("[DRIVE] Waiting for uploads to finish... (Press Ctrl+C to skip)")
            for up in active_uploaders:
                up.wait_all(timeout_s=getattr(constants, "DRIVE_UPLOAD_WAIT_TIMEOUT_S", 1800))
        except KeyboardInterrupt:
            for up in active_uploaders:
                up.abort()
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

    def get_iteration_app(self, iteration: int) -> str:
        """Resolve the target project/app for the given 1-based iteration.

        Each app runs through all target devices (`len(self.device_names)`) before cycling
        to the next app in `self.app_names`, then loops back to the first app.
        """
        if not self.app_names:
            return self.project_name or "igha"
        if len(self.app_names) == 1:
            return self.app_names[0]
        devices_per_cycle = max(1, len(self.device_names))
        app_idx = ((max(1, iteration) - 1) // devices_per_cycle) % len(self.app_names)
        return self.app_names[app_idx]

    def _bundle_id_for_app(self, app_name: str, resolve_att: bool = True) -> str:
        """Return the iOS bundle identifier for the specified project name."""
        app_key = (app_name or "igha").lower()
        if app_key == "ighp":
            return getattr(
                constants, "iGHP_SAMPLE_APP_BUNDLE_ID",
                "com.google.homeplatform.sampleapp.gomezandres"
            )
        if app_key == "att":
            if resolve_att and self.driver is not None and resolve_att_bundle_id is not None:
                return resolve_att_bundle_id(self.driver)
            return getattr(constants, "ATT_BUNDLE_ID", "com.att.connectedlife")
        return getattr(constants, "GHA_BUNDLE_ID", "com.google.Chromecast.enterprise")

    def _activate_app_context(self, app_name: str) -> str:
        """Update active project, bundle ID markers, and version fields for `app_name`."""
        app_key = (app_name or "igha").lower()
        self.project_name = app_key
        active_bundle = self._bundle_id_for_app(app_key, resolve_att=True)
        constants.ACTIVE_APP_BUNDLE_ID = active_bundle
        if self.driver is not None:
            try:
                setattr(self.driver, "_active_app_bundle_id", active_bundle)
            except Exception:
                pass
        self._apply_app_version_fields(app_key)
        return active_bundle

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
        apps_banner = " -> ".join(self.app_names)
        if len(self.app_names) > 1:
            logger.info(
                f"       STARTING MULTI-APP TEST SESSION : {apps_banner} (loop per full device cycle)")
        else:
            logger.info(f"       STARTING TEST SESSION FOR APP: {self.project_name}        ")
        logger.info(f"       Execution Mode     : {mode_str}")
        logger.info(f"       Target iPhone UDID : {self.udid or '<auto>'}")
        logger.info(f"       WDA Local Port     : {self.wda_local_port}")
        if self.mjpeg_server_port is not None:
            logger.info(f"       WDA MJPEG Port     : {self.mjpeg_server_port}")
        if len(self.app_names) > 1:
            for app_item in self.app_names:
                logger.info(
                    f"       Session Log [{app_item}] : {self._app_session_dirs.get(app_item, constants.SESSION_LOG_DIR)}"
                )
        else:
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
        if any(self._drive_uploaders_by_app.values()) or self.drive_uploader:
            if len(self.app_names) > 1:
                for app_item in self.app_names:
                    if self._drive_uploaders_by_app.get(app_item):
                        logger.info(
                            f"       Drive Run [{app_item}]   : {self._drive_run_folders_by_app.get(app_item)}"
                        )
            else:
                logger.info(f"       Drive Run Folder   : {self.drive_run_folder_name}")
        targets = self.device_names or (
            [self.device_name] if isinstance(self.device_name, str) else [])
        first_adb = self.get_iteration_adb_serial(1)
        device_log_targets = [
            d for d in targets if self._device_log_config_for(d, adb_serial_override=first_adb)
        ]
        if device_log_targets:
            logger.info(f"       Device Log Capture : {', '.join(device_log_targets)}")
        if not self.adb_serials and any(a != "att" for a in self.app_names):
            online_adb = self._list_online_adb_serials()
            if len(online_adb) > 1:
                logger.warning(
                    f"[MULTI-DEVICE NOTICE] Detected {len(online_adb)} connected ADB devices {online_adb} "
                    "without --adb_serial. Post-test ADB reset will reset ALL connected ADB devices unless "
                    "you pass --adb_serial <serial>."
                )
        logger.info("=" * 65)
        logger.info(f"Connecting to Appium Server at: {constants.APPIUM_SERVER_URL}")
        active_bundle = self._bundle_id_for_app(self.project_name, resolve_att=False)
        constants.ACTIVE_APP_BUNDLE_ID = active_bundle
        options = AppiumOptions()
        options.load_capabilities(constants.IOS_CAPABILITIES)
        with self._interprocess_lock("ios_automation_wda_init.lock"):
            self.driver = webdriver.Remote(constants.APPIUM_SERVER_URL, options=options)
        self._activate_app_context(self.project_name)
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
            all_pulled: List[str] = []
            seen_bundles = set()
            for app_item in self.app_names:
                if app_item == "att":
                    target_bundle = (
                            getattr(self.driver, "_att_bundle_id", None)
                            or getattr(constants, "ATT_BUNDLE_ID", "com.att.connectedlife")
                    )
                else:
                    target_bundle = self._bundle_id_for_app(app_item, resolve_att=False)
                if not target_bundle or target_bundle in seen_bundles:
                    continue
                seen_bundles.add(target_bundle)
                dest = (
                        self._app_session_dirs.get(app_item)
                        or logging_utils._current_main_log_dir
                        or constants.SESSION_LOG_DIR
                )
                os.makedirs(dest, exist_ok=True)
                before = set(os.listdir(dest)) if os.path.isdir(dest) else set()
                try:
                    logging_utils.pull_ios_app_container(self.driver, target_bundle, dest)
                except Exception as e:
                    logger.error(f"Failed to pull {target_bundle} container: {e}")
                after = set(os.listdir(dest)) if os.path.isdir(dest) else set()
                newly_pulled = [os.path.join(dest, name) for name in sorted(after - before)]
                if newly_pulled:
                    self._container_paths_by_app[app_item] = newly_pulled
                    all_pulled.extend(newly_pulled)
            self._container_paths = all_pulled
            if self._container_paths:
                logger.info(
                    f"[DRIVE] App container artifacts queued for upload: {self._container_paths}")
            logger.info("Quitting Appium WebDriver...")
            self.driver.quit()
        if self.syslog_collector:
            self.syslog_collector.stop()
        self._stop_device_log()  # [DEVICE LOG]
        for s_dir in list(
                dict.fromkeys(list(self._app_session_dirs.values()) + [constants.SESSION_LOG_DIR])):
            for extra in [os.path.join(s_dir, "Main log"), os.path.join(s_dir, "Additional log")]:
                if os.path.exists(extra) and not os.listdir(extra):
                    try:
                        os.rmdir(extra)
                    except Exception:
                        pass
        logger.info("=" * 65)
        if len(self.app_names) > 1:
            for app_item in self.app_names:
                logger.info(
                    f"Artifacts and Logs [{app_item}] stored in: {self._app_session_dirs.get(app_item)}"
                )
        else:
            logger.info(f"Artifacts and Logs stored in: {constants.SESSION_LOG_DIR}")
        logger.info("=" * 65)

    def _get_project_suite(self, app_name: Optional[str] = None) -> Tuple[Any, List[Type]]:
        """Resolve session instance and test classes for the target project."""
        target_app = (app_name or self.project_name or "igha").lower()
        if target_app == "ighp":
            session_instance = GHPSession(self.driver)
            ghp_test_cls = TestGHPHome
            if ghp_test_cls is None:
                from testcase.iGHP.test_home import TestGHPHome as _TestGHPHome
                ghp_test_cls = _TestGHPHome
            test_classes = [ghp_test_cls]
        elif target_app == "att":
            att_sess_cls = ATTSession
            if att_sess_cls is None:
                from page_object.Partner.ATT.att_session import ATTSession as _ATTSession
                att_sess_cls = _ATTSession
            att_test_cls = TestATTHome
            if att_test_cls is None:
                from testcase.Partner.ATT.test_home import TestATTHome as _TestATTHome
                att_test_cls = _TestATTHome
            session_instance = att_sess_cls(self.driver)
            test_classes = [att_test_cls]
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
            app_suites: Dict[str, Tuple[Any, List[Type]]] = {}
            prev_app: Optional[str] = None
            last_failed_app: Optional[str] = None
            last_failed_device: Optional[str] = None
            last_failed_session: Optional[Any] = None
            while True:
                iteration += 1
                if self.count is not None and iteration > self.count:
                    break
                self._ensure_sufficient_disk_space()
                current_app = self.get_iteration_app(iteration)
                current_device, current_pairing_code = self.get_iteration_targets(iteration)
                current_adb_serial = self.get_iteration_adb_serial(iteration)
                if current_adb_serial:
                    self._sync_adb_reset_target(current_device, current_adb_serial)

                if prev_app != current_app:
                    if (
                            last_failed_session is not None
                            and last_failed_app == prev_app
                            and prev_app != "att"
                            and not getattr(last_failed_session, "_device_removed_in_emergency",
                                            False)
                            and hasattr(last_failed_session, "cleanup_leftover_device_if_present")
                    ):
                        logger.warning(
                            f"[MULTI-APP CLEANUP] Previous '{prev_app}' iteration failed without confirmed UI removal; "
                            f"checking for leftover '{last_failed_device}' before switching to '{current_app}'..."
                        )
                        try:
                            last_failed_session.cleanup_leftover_device_if_present(
                                last_failed_device)
                        except Exception as pre_clean_err:
                            logger.warning(
                                f"[MULTI-APP CLEANUP] Pre-switch cleanup error: {pre_clean_err}")
                    if prev_app is not None and self.driver is not None:
                        prev_bundle = self._bundle_id_for_app(prev_app, resolve_att=False)
                        if hasattr(self.driver, "terminate_app"):
                            try:
                                self.driver.terminate_app(prev_bundle)
                            except Exception:
                                pass
                        devices_per_cycle = max(1, len(self.device_names))
                        cycle_num = ((iteration - 1) // devices_per_cycle) + 1
                        logger.info(
                            f"\n[MULTI-APP] Completed all devices for '{prev_app}'. "
                            f"Switching to next app '{current_app}' (Cycle #{cycle_num})..."
                        )
                    self._switch_session_log_dir_for_app(current_app)
                    self._activate_app_context(current_app)
                    prev_app = current_app

                if current_app not in app_suites:
                    app_suites[current_app] = self._get_project_suite(current_app)
                session_instance, test_classes = app_suites[current_app]

                session_instance.device_name = current_device
                session_instance.pairing_code = current_pairing_code
                session_instance.iteration = iteration
                try:
                    setattr(session_instance, "_device_removed_in_emergency", False)
                except Exception:
                    pass
                last_failed_app = None
                last_failed_device = None
                last_failed_session = None
                iter_label = f"{iteration}/{self.count}" if self.count else f"{iteration} (Infinite)"
                logger.info("\n" + "=" * 65)
                logger.info(f"               STARTING ITERATION #{iter_label}")
                logger.info(f"               TARGET APP    : {current_app}")
                logger.info(f"               TARGET DEVICE : {current_device}")
                if current_app == "att":
                    logger.info(f"               TARGET ROOM   : {self.room_name}")
                else:
                    logger.info(f"               PAIRING CODE  : {current_pairing_code}")
                if current_adb_serial:
                    logger.info(f"               ADB SERIAL    : {current_adb_serial}")
                logger.info("=" * 65)
                for test_cls in test_classes:
                    test_instance = test_cls(
                        session=session_instance,
                        device_name=current_device,
                        pairing_code=current_pairing_code,
                        room_name=self.room_name,
                    )
                    try:
                        test_instance.iteration = iteration
                    except Exception:
                        pass
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
                        self._preflight_heal_wda_and_dismiss_system_modals(current_app)
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
                        if self.driver is not None:
                            try:
                                self.driver.implicitly_wait(
                                    getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
                                )
                            except Exception:
                                pass
                            for stale_attr in (
                                    "device_tech_info",
                                    "_commissioned_via_timeout_online",
                                    "_ghp_commissioned_tile_name",
                            ):
                                try:
                                    if hasattr(self.driver, stale_attr):
                                        delattr(self.driver, stale_attr)
                                except Exception:
                                    try:
                                        setattr(self.driver, stale_attr, None)
                                    except Exception:
                                        pass
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
                        self._app_stats.setdefault(current_app,
                                                   {"runs": 0, "passed": 0, "failed": 0})[
                            "runs"
                        ] += 1
                        try:
                            test_method()
                            elapsed = time.time() - start_time
                            BasePage.reset_failure_screenshot_state(self.driver,
                                                                    remove_existing=True)
                            logger.info(
                                f">>> [PASS] [Iter #{iteration}] {class_name}.{test_name} ({elapsed:.2f}s)")
                            total_passed += 1
                            self._app_stats[current_app]["passed"] += 1
                        except Exception as e:
                            elapsed = time.time() - start_time
                            caught_exception = e
                            test_status = "FAIL"
                            test_error = str(e)
                            self.last_error_message = test_error
                            last_failed_app = current_app
                            last_failed_device = current_device
                            last_failed_session = session_instance
                            logger.error(
                                f">>> [FAIL] [Iter #{iteration}] {class_name}.{test_name} ({elapsed:.2f}s) - Error: {e}"
                            )
                            total_failed += 1
                            self._app_stats[current_app]["failed"] += 1
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
                            app_ver_map = self._app_versions.setdefault(
                                current_app, self._default_versions_for_app(current_app)
                            )
                            self._apply_app_version_fields(current_app)
                            if current_app == "ighp":
                                drv_ver = getattr(self.driver, "_ghp_version_info",
                                                  None) if self.driver else None
                                if isinstance(drv_ver, dict):
                                    s_ver = str(drv_ver.get("sample_app_version") or "").strip()
                                    k_ver = str(drv_ver.get("sdk_version") or "").strip()
                                    if s_ver and s_ver.upper() not in ("UNKNOWN",
                                                                       "UNKNOWN / NOT INSTALLED"):
                                        app_ver_map["sample_app_version"] = s_ver
                                    if k_ver and k_ver.upper() not in ("UNKNOWN",
                                                                       "UNKNOWN / NOT INSTALLED"):
                                        app_ver_map["sdk_version"] = k_ver
                                sess_s_ver = str(getattr(session_instance, "sample_app_version",
                                                         "") or "").strip()
                                sess_k_ver = str(
                                    getattr(session_instance, "sdk_version", "") or "").strip()
                                if (
                                        sess_s_ver
                                        and sess_s_ver.upper() not in ("UNKNOWN",
                                                                       "UNKNOWN / NOT INSTALLED")
                                        and app_ver_map.get("sample_app_version", "").upper() in (
                                        "", "UNKNOWN")
                                ):
                                    app_ver_map["sample_app_version"] = sess_s_ver
                                if (
                                        sess_k_ver
                                        and sess_k_ver.upper() not in ("UNKNOWN",
                                                                       "UNKNOWN / NOT INSTALLED")
                                        and app_ver_map.get("sdk_version", "").upper() in ("",
                                                                                           "UNKNOWN")
                                ):
                                    app_ver_map["sdk_version"] = sess_k_ver
                                self._apply_app_version_fields(current_app)

                            keep_app_open_after_wifi = current_app == "att"
                            if not self._env_collected_by_app.get(current_app,
                                                                  False) and self.driver:
                                try:
                                    logger.info(
                                        f"[ENV INFO] First '{current_app}' testcase completed, collecting full environment info..."
                                    )
                                    env_info = self._call_env_fn(
                                        log_all_version_information,
                                        self.driver,
                                        return_to_app=keep_app_open_after_wifi,
                                    )
                                    if isinstance(env_info, dict):
                                        if current_app == "ighp":
                                            app_ver_map["gha_version"] = "N/A"
                                            env_sample = str(
                                                env_info.get("sample_app_version")
                                                or env_info.get("sample_version")
                                                or ""
                                            ).strip()
                                            env_sdk = str(env_info.get("sdk_version") or "").strip()
                                            if env_sample and env_sample.upper() not in ("UNKNOWN",
                                                                                         "UNKNOWN / NOT INSTALLED"):
                                                app_ver_map["sample_app_version"] = env_sample
                                            if env_sdk and env_sdk.upper() not in ("UNKNOWN",
                                                                                   "UNKNOWN / NOT INSTALLED"):
                                                app_ver_map["sdk_version"] = env_sdk
                                        elif current_app == "att":
                                            app_ver_map["gha_version"] = "N/A"
                                            app_ver_map["sample_app_version"] = "N/A"
                                            app_ver_map["sdk_version"] = "N/A"
                                            env_att = str(env_info.get("att_version") or "").strip()
                                            if env_att and env_att.upper() not in ("UNKNOWN",
                                                                                   "UNKNOWN / NOT INSTALLED"):
                                                app_ver_map["att_version"] = env_att
                                        else:
                                            if "gha_version" in env_info:
                                                app_ver_map["gha_version"] = str(
                                                    env_info["gha_version"])
                                            app_ver_map["sample_app_version"] = "N/A"
                                            app_ver_map["sdk_version"] = "N/A"
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
                                    if current_app == "ighp" and app_ver_map.get("sdk_version",
                                                                                 "").upper() in (
                                            "", "UNKNOWN", "UNKNOWN / NOT INSTALLED"
                                    ):
                                        syslog_sdk = self._extract_sdk_version_from_syslog(
                                            case_syslog_path)
                                        if syslog_sdk:
                                            app_ver_map["sdk_version"] = syslog_sdk
                                    self._env_collected_by_app[current_app] = True
                                    self.env_info_collected = all(
                                        self._env_collected_by_app.get(a, False) for a in
                                        self.app_names
                                    )
                                    self._apply_app_version_fields(current_app)
                                    if current_app == "ighp":
                                        logger.info(
                                            f"[ENV INFO] Initialized: Sample App {self.sample_app_version} | "
                                            f"SDK {self.sdk_version} | iOS {self.ios_version} | "
                                            f"SSID {self.wifi_ssid} | Phone IP {self.phone_ip} | Gateway {self.router_gateway}"
                                        )
                                    elif current_app == "att":
                                        logger.info(
                                            f"[ENV INFO] Initialized: AT&T Connected Life {self.att_version} | iOS {self.ios_version} | "
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
                                    self._env_collected_by_app[current_app] = True
                                    self.env_info_collected = all(
                                        self._env_collected_by_app.get(a, False) for a in
                                        self.app_names
                                    )
                            elif self.driver:
                                need_wifi_refresh = (
                                        test_status != "PASS"
                                        or not self.wifi_ssid
                                        or self.wifi_ssid.lower() == "unknown"
                                )
                                if need_wifi_refresh:
                                    try:
                                        logger.info(
                                            f"[ENV INFO] [Iter #{iteration}] Refreshing Wi-Fi details from iOS Settings..."
                                        )
                                        w_info = self._call_env_fn(
                                            get_wifi_information,
                                            self.driver,
                                            return_to_app=keep_app_open_after_wifi,
                                        )
                                        if isinstance(w_info, dict):
                                            self.wifi_ssid = str(w_info.get("ssid", self.wifi_ssid))
                                            self.phone_ip = str(
                                                w_info.get("ip_address", self.phone_ip))
                                            self.router_gateway = str(
                                                w_info.get("router_gateway", self.router_gateway)
                                            )
                                            self.subnet_mask = str(
                                                w_info.get("subnet_mask", self.subnet_mask))
                                        logger.info(
                                            f"[ENV INFO] [Iter #{iteration}] Updated Wi-Fi: SSID='{self.wifi_ssid}' | "
                                            f"Phone IP='{self.phone_ip}' | Gateway='{self.router_gateway}'"
                                        )
                                    except Exception as wifi_err:
                                        logger.warning(
                                            f"Failed to refresh Wi-Fi info for iteration #{iteration}: {wifi_err}"
                                        )
                                else:
                                    logger.info(
                                        f"[ENV INFO] [Iter #{iteration}] Reusing cached Wi-Fi: SSID='{self.wifi_ssid}' | "
                                        f"Phone IP='{self.phone_ip}' | Gateway='{self.router_gateway}'"
                                    )
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
                                iteration,
                                test_status,
                                current_device,
                                class_name,
                                test_name,
                                app_name=current_app,
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
                                csv_kwargs["app"] = current_app
                            if self._csv_accepts_param("sample_app_version") or accepts_var_kw:
                                csv_kwargs["sample_app_version"] = self.sample_app_version
                            if self._csv_accepts_param("sdk_version") or accepts_var_kw:
                                csv_kwargs["sdk_version"] = self.sdk_version
                            if self._csv_accepts_param("att_version") or accepts_var_kw:
                                csv_kwargs["att_version"] = self.att_version
                            if self._csv_accepts_drive_url:
                                csv_kwargs["drive_url"] = drive_url
                            try:
                                with self._interprocess_lock("ios_automation_csv_report.lock"):
                                    csv_report.append_test_result_to_csv(**csv_kwargs)
                            except Exception as csv_err:
                                logger.warning(
                                    f"Failed to record result to CSV / Google Sheet: {csv_err}")
                            self._drive_upload_case_dir(
                                drive_folder_id, case_dir, label=child_folder_name,
                                app_name=current_app
                            )
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
            if len(self.app_names) > 1:
                for app_item in self.app_names:
                    st = self._app_stats.get(app_item, {"runs": 0, "passed": 0, "failed": 0})
                    logger.info(
                        f"    - [{app_item}] Runs: {st['runs']} | Passed: {st['passed']} | Failed: {st['failed']}"
                    )
            logger.info(f"  Total Duration        : {total_duration:.2f}s")
            logger.info("=" * 65)
            self._drive_finalize()
            self._release_session_active()
        if total_failed > 0 and self.count is not None:
            exit(1)
