"""Module for managing test execution lifecycles, iterations, session setup, teardown, and reporting."""
import os
import re
import signal
import socket
import subprocess
import time
import traceback
from datetime import datetime
from typing import Any, List, Optional, Tuple, Type, Union
from appium import webdriver
from appium.options.common import AppiumOptions
from common import constants
from core.syslog_collector import SyslogCollector
from page_object.iGHA.gha_session import GHASession
from page_object.iGHP.ghp_session import GHPSession
from testcase.iGHA.test_home import TestGHAHome
from utils import logging_utils
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
            if frame.name not in ("find_element", "find_elements", "click", "send_keys", "__getattr__"):
                return frame.name.upper()
        if "testcase" in frame.filename and frame.line:
            matches = re.findall(r"\.([a-zA-Z0-9_]+)\s*\(", frame.line)
            if matches:
                return matches[-1].upper()
            return frame.name.upper()
    return "UNKNOWN"


class MultiProjectTestRunner:
    """Class managing complete test execution lifecycle, multi-iteration runs, and automated reporting."""
    def __init__(
            self,
            app: Optional[str] = "igha",
            device_name: Optional[Union[str, List[str]]] = None,
            pairing_code: Optional[Union[str, List[str]]] = None,
            count: Optional[int] = None,
            room_name: Optional[str] = "Attic",
            gemini_api_key: Optional[str] = constants.GEMINI_API_KEY,
            component_id: Optional[str] = "1796386",
            **kwargs: Any
    ) -> None:
        self.project_name = (app or "igha").lower()
        self.device_name = device_name
        self.pairing_code = pairing_code
        self.count = count
        self.room_name = room_name or "Attic"
        if isinstance(device_name, list):
            self.device_names: List[str] = [str(d).strip() for d in device_name if str(d).strip()]
        elif isinstance(device_name, str) and device_name.strip():
            if "," in device_name:
                self.device_names = [d.strip() for d in device_name.split(",") if d.strip()]
            else:
                self.device_names = [device_name.strip()]
        else:
            self.device_names = []
        if isinstance(pairing_code, list):
            self.pairing_codes: List[str] = [str(c).strip() for c in pairing_code if str(c).strip()]
        elif isinstance(pairing_code, str) and pairing_code.strip():
            if "," in pairing_code:
                self.pairing_codes = [c.strip() for c in pairing_code.split(",") if c.strip()]
            else:
                self.pairing_codes = [pairing_code.strip()]
        else:
            self.pairing_codes = []
        self.udid = constants.IOS_CAPABILITIES.get("appium:udid", "")
        self.driver: Optional[webdriver.Remote] = None
        self.syslog_collector: Optional[SyslogCollector] = None
        self.syslog_file_paths: List[str] = []
        self.failure_screenshots: List[str] = []
        self.screen_recordings: List[str] = []
        self.last_error_message: Optional[str] = None
        self.component_id = component_id
        self.gemini_reporter = GeminiReporter(api_key=gemini_api_key)
        self.gha_version: str = "4.29.25"
        self.ios_version: str = "iOS 17+"
        self.wifi_ssid: str = "Atelier320482024g"
        self.phone_ip: str = "192.168.1.113"
        self.router_gateway: str = "192.168.1.1"
        self.subnet_mask: str = "255.255.255.0"
        self.device_id: str = "UNKNOWN"
        self.serial_number: str = "UNKNOWN"
        self.software_version: str = "UNKNOWN"
        self.device_ip: str = "UNKNOWN"
        self.env_info_collected: bool = False

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

    def setup(self) -> None:
        """Initialize Appium session and configure implicit wait."""
        mode_str = f"{self.count} times" if self.count else "INFINITE LOOP (Press Ctrl+C to stop)"
        logger.info("=" * 65)
        logger.info(f"       STARTING TEST SESSION FOR APP: {self.project_name}        ")
        logger.info(f"       Execution Mode     : {mode_str}")
        if self.device_names:
            logger.info(f"       Target Devices     : {', '.join(self.device_names)}")
        elif self.device_name:
            logger.info(f"       Target Device Name : {self.device_name}")
        if self.pairing_codes:
            logger.info(f"       Pairing Codes      : {', '.join(self.pairing_codes)}")
        elif self.pairing_code:
            logger.info(f"       Pairing Code       : {self.pairing_code}")
        if self.device_names and self.pairing_codes:
            logger.info("-" * 65)
            logger.info("       Device <===> Pairing Code Mapping:")
            for idx, d_name in enumerate(self.device_names):
                p_code = (
                    self.pairing_codes[idx]
                    if idx < len(self.pairing_codes)
                    else self.pairing_codes[idx % len(self.pairing_codes)]
                )
                logger.info(f"         [{idx + 1}] '{d_name}'  <===>  '{p_code}'")
            logger.info("-" * 65)
        if self.room_name:
            logger.info(f"       Assigned Room Name : {self.room_name}")
        logger.info("=" * 65)
        logger.info(f"Connecting to Appium Server at: {constants.APPIUM_SERVER_URL}")
        options = AppiumOptions()
        options.load_capabilities(constants.IOS_CAPABILITIES)
        self.driver = webdriver.Remote(constants.APPIUM_SERVER_URL, options=options)
        implicit_wait = getattr(constants, "DEFAULT_IMPLICIT_WAIT_SECONDS", 10.0)
        self.driver.implicitly_wait(implicit_wait)
        logger.info(f"Global driver implicit wait configured to: {implicit_wait}s")

    def teardown(self) -> None:
        """Collect .xcappdata container, quit Appium WebDriver, and stop syslog collector."""
        logger.info("=" * 65)
        logger.info("            TEARDOWN & COLLECTING ARTIFACTS                  ")
        logger.info("=" * 65)
        if self.driver:
            target_bundle = (
                constants.iGHP_SAMPLE_APP_BUNDLE_ID if self.project_name == "ighp" else constants.GHA_BUNDLE_ID
            )
            try:
                dest = logging_utils._current_main_log_dir or constants.SESSION_LOG_DIR
                logging_utils.pull_ios_app_container(self.driver, target_bundle, dest)
            except Exception as e:
                logger.error(f"Failed to pull {target_bundle} container: {e}")
            logger.info("Quitting Appium WebDriver...")
            self.driver.quit()
        if self.syslog_collector:
            self.syslog_collector.stop()
        for extra in [os.path.join(constants.SESSION_LOG_DIR, "Main log"), os.path.join(constants.SESSION_LOG_DIR, "Additional log")]:
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
            test_classes = [TestGHAHome]
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
                current_device, current_pairing_code = self.get_iteration_targets(iteration)
                session_instance.device_name = current_device
                session_instance.pairing_code = current_pairing_code
                iter_label = f"{iteration}/{self.count}" if self.count else f"{iteration} (Infinite)"
                logger.info("\n" + "=" * 65)
                logger.info(f"               STARTING ITERATION #{iter_label}")
                logger.info(f"               TARGET DEVICE : {current_device}")
                logger.info(f"               PAIRING CODE  : {current_pairing_code}")
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
                        logging_utils.set_current_test_dirs(case_main_log_dir, case_additional_log_dir)
                        logger.info(
                            f"\n>>> [RUNNING] [Iter #{iteration}] {class_name}.{test_name} "
                            f"(Device: '{current_device}', Code: '{current_pairing_code}')"
                        )
                        logger.info(f">>> [TARGET DIR] {case_dir}")
                        current_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        case_syslog_path = None
                        if self.udid:
                            case_syslog_path = os.path.join(case_main_log_dir, f"LOG_{current_ts}_syslog.log")
                            self.syslog_collector = SyslogCollector(self.udid, case_syslog_path)
                            self.syslog_collector.start()
                        screen_recorder = ScreenRecorder(output_dir=case_additional_log_dir)
                        if self.driver:
                            try:
                                screen_recorder.start_recording(self.driver)
                                logger.info(f"[REC] Screen recording started for: {class_name}.{test_name}")
                            except Exception as rec_err:
                                logger.warning(f"Failed to start screen recording: {rec_err}")
                        self.device_id = "UNKNOWN"
                        self.serial_number = "UNKNOWN"
                        self.software_version = "UNKNOWN"
                        self.device_ip = "UNKNOWN"
                        start_time = time.time()
                        start_dt = datetime.now()
                        test_status = "PASS"
                        test_error = ""
                        caught_exception = None
                        try:
                            test_method()
                            elapsed = time.time() - start_time
                            logger.info(f">>> [PASS] [Iter #{iteration}] {class_name}.{test_name} ({elapsed:.2f}s)")
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
                                screenshot_file = os.path.join(
                                    case_additional_log_dir,
                                    f"FAILED_iter{iteration}_{current_ts}_{class_name}_{test_name}.png"
                                )
                                try:
                                    self.driver.save_screenshot(screenshot_file)
                                    self.failure_screenshots.append(screenshot_file)
                                    logger.info(f"Saved failure screenshot to: {screenshot_file}")
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
                                        logger.info(f"[REC] Screen recording saved: {video_filename}")
                                except Exception as rec_stop_err:
                                    logger.warning(f"Failed to save screen recording: {rec_stop_err}")
                            if self.syslog_collector:
                                self.syslog_collector.stop()
                                if case_syslog_path and os.path.exists(case_syslog_path):
                                    self.syslog_file_paths.append(case_syslog_path)
                                self.syslog_collector = None
                            if not self.env_info_collected and self.driver:
                                try:
                                    logger.info("[ENV INFO] First testcase completed, collecting full environment info...")
                                    env_info = log_all_version_information(self.driver)
                                    if isinstance(env_info, dict):
                                        if "gha_version" in env_info:
                                            self.gha_version = str(env_info["gha_version"])
                                        if "device_info" in env_info and "platform_version" in env_info["device_info"]:
                                            self.ios_version = str(env_info["device_info"]["platform_version"])
                                        if "wifi_info" in env_info and isinstance(env_info["wifi_info"], dict):
                                            w_info = env_info["wifi_info"]
                                            self.wifi_ssid = str(w_info.get("ssid", self.wifi_ssid))
                                            self.phone_ip = str(w_info.get("ip_address", self.phone_ip))
                                            self.router_gateway = str(w_info.get("router_gateway", self.router_gateway))
                                            self.subnet_mask = str(w_info.get("subnet_mask", self.subnet_mask))
                                    self.env_info_collected = True
                                    logger.info(
                                        f"[ENV INFO] Initialized: GHA {self.gha_version} | iOS {self.ios_version} | "
                                        f"SSID {self.wifi_ssid} | Phone IP {self.phone_ip} | Gateway {self.router_gateway}"
                                    )
                                except Exception as env_err:
                                    logger.warning(f"Failed to collect version information: {env_err}")
                                    self.env_info_collected = True
                            elif self.driver:
                                try:
                                    logger.info(f"[ENV INFO] [Iter #{iteration}] Fetching latest Wi-Fi details for current run...")
                                    w_info = get_wifi_information(self.driver)
                                    if isinstance(w_info, dict):
                                        self.wifi_ssid = str(w_info.get("ssid", self.wifi_ssid))
                                        self.phone_ip = str(w_info.get("ip_address", self.phone_ip))
                                        self.router_gateway = str(w_info.get("router_gateway", self.router_gateway))
                                        self.subnet_mask = str(w_info.get("subnet_mask", self.subnet_mask))
                                    logger.info(
                                        f"[ENV INFO] [Iter #{iteration}] Updated Wi-Fi: SSID='{self.wifi_ssid}' | "
                                        f"Phone IP='{self.phone_ip}' | Gateway='{self.router_gateway}'"
                                    )
                                except Exception as wifi_err:
                                    logger.warning(f"Failed to refresh Wi-Fi info for iteration #{iteration}: {wifi_err}")
                            dev_tech = (
                                    getattr(self.driver, "device_tech_info", None)
                                    or getattr(test_instance, "device_tech_info", None)
                                    or getattr(session_instance, "device_tech_info", None)
                                    or getattr(getattr(test_instance, "session", None), "device_tech_info", None)
                            )
                            if isinstance(dev_tech, dict) and dev_tech:
                                for key, val in dev_tech.items():
                                    if val and str(val).upper() != "UNKNOWN":
                                        if key in ("device_id", "Device ID"):
                                            self.device_id = str(val)
                                        elif key in ("serial_number", "serial_no", "Serial Number"):
                                            self.serial_number = str(val)
                                        elif key in ("software_version", "Software Version", "firmware_version"):
                                            self.software_version = str(val)
                                        elif key in ("device_ip", "camera_ip", "Device IP", "ip_address"):
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
                            try:
                                csv_report.append_test_result_to_csv(
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
                            except Exception as csv_err:
                                logger.warning(f"Failed to record result to CSV / Google Sheet: {csv_err}")
        except KeyboardInterrupt:
            logger.info("\n[INTERRUPT] Received KeyboardInterrupt (Ctrl+C). Terminating test execution gracefully...")
        finally:
            total_duration = time.time() - session_start_time
            self.teardown()
        completed_iterations = iteration if self.count is None else min(iteration, self.count)
        logger.info("\n" + "=" * 65)
        logger.info(f"Final Execution Summary ({completed_iterations} total iterations completed):")
        logger.info(f"  Total Test Executions : {total_runs}")
        logger.info(f"  Total Passed          : {total_passed}")
        logger.info(f"  Total Failed          : {total_failed}")
        logger.info(f"  Total Duration        : {total_duration:.2f}s")
        logger.info("=" * 65)
        if total_failed > 0 and self.count is not None:
            exit(1)
