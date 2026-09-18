"""CSV Reporter and Google Sheet Webhook Sync for iOS Automation."""
import os
import csv
import json
import urllib.request
from datetime import datetime
from pathlib import Path
from common import constants
from utils import logging_utils


logger = logging_utils.get_logger(__name__, "csv_report")

def _get_project_root() -> Path:
    """Traverse upwards to locate the project root directory containing main.py or core/."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "main.py").exists() or (parent / "core").exists():
            return parent
    return current.parents[2] if len(current.parents) > 2 else current.parent

PROJECT_ROOT = _get_project_root()
LOG_DIR = PROJECT_ROOT / "log"
LOG_DIR.mkdir(parents=True, exist_ok=True)
CSV_FILE_PATH = str(LOG_DIR / "test_results.csv")

CSV_HEADERS = [
    "Timestamp", "Iteration", "Test Name", "Status", "Duration (s)",
    "GHA Version", "iOS Version", "Device Name", "Wi-Fi SSID",
    "Failure Stage", "Error Message", "Log Directory", "Video File", "Host Machine",
    "Phone IP Address", "Router Gateway", "Subnet Mask",
    "Device ID", "Serial Number", "Software Version", "Device IP"
]

def append_test_result_to_csv(
        test_name: str,
        device_name: str,
        gha_version: str,
        status: str,
        start_time: datetime,
        end_time: datetime,
        error_msg: str = "",
        iteration: int = 1,
        ios_version: str = "",
        wifi_ssid: str = "",
        failure_stage: str = "No errors",
        log_dir: str = "",
        video_file: str = "",
        host_machine: str = "",
        phone_ip: str = "UNKNOWN",
        router_gateway: str = "UNKNOWN",
        subnet_mask: str = "UNKNOWN",
        device_id: str = "UNKNOWN",
        serial_number: str = "UNKNOWN",
        software_version: str = "UNKNOWN",
        device_ip: str = "UNKNOWN"
) -> None:
    """Record testcase telemetry to local CSV and upload payload to Google Sheet Webhook."""
    file_exists = os.path.isfile(CSV_FILE_PATH)
    os.makedirs(os.path.dirname(CSV_FILE_PATH), exist_ok=True)
    duration_s = round((end_time - start_time).total_seconds(), 2)
    timestamp_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
    iteration_str = f"Iter {iteration}"
    row = [
        timestamp_str,
        iteration_str,
        test_name,
        status,
        duration_s,
        gha_version,
        ios_version,
        device_name,
        wifi_ssid,
        failure_stage,
        error_msg,
        log_dir,
        video_file,
        host_machine,
        phone_ip,
        router_gateway,
        subnet_mask,
        device_id,
        serial_number,
        software_version,
        device_ip
    ]
    try:
        with open(CSV_FILE_PATH, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(CSV_HEADERS)
            writer.writerow(row)
        logger.info(f"[CSV] Appended telemetry row for '{test_name}' to {CSV_FILE_PATH}")
    except Exception as e:
        logger.error(f"[CSV] Failed to append row to CSV: {e}")
    payload_data = {
        "timestamp": timestamp_str,
        "iteration": iteration_str,
        "test_name": test_name,
        "status": status,
        "duration_s": duration_s,
        "gha_version": gha_version,
        "ios_version": ios_version,
        "device_name": device_name,
        "wifi_ssid": wifi_ssid,
        "failure_stage": failure_stage,
        "error_message": error_msg,
        "log_directory": log_dir,
        "video_file": video_file,
        "host_machine": host_machine,
        "phone_ip": phone_ip,
        "router_gateway": router_gateway,
        "subnet_mask": subnet_mask,
        "device_id": device_id,
        "serial_number": serial_number,
        "software_version": software_version,
        "device_ip": device_ip,
        "row": row,
        "values": row
    }
    webhook_url = getattr(constants, "GOOGLE_SHEET_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("[WEBHOOK] GOOGLE_SHEET_WEBHOOK_URL is not defined in constants. Skipping sync.")
        return
    try:
        logger.info(f"[WEBHOOK] Uploading telemetry for '{test_name}' to Google Sheet...")
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload_data).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            res_body = response.read().decode("utf-8")
            logger.info(f"[GOOGLE SHEET SYNC] Webhook upload response: {res_body}")
    except Exception as e:
        logger.error(f"[GOOGLE SHEET SYNC] Webhook synchronization failed: {e}")