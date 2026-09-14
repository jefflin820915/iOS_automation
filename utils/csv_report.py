"""CSV Reporter and Google Sheet Webhook Sync for iOS Automation."""
import os
import csv
import json
import urllib.request
from datetime import datetime

from common import constants
from utils import logging_utils


logger = logging_utils.get_logger(__name__, "csv_report")

CSV_FILE_PATH = "/Users/enlin/iOS_Automation/log/test_results.csv"
WEBHOOK_URL = "https://script.google.com/a/macros/google.com/s/AKfycbxvNyA-SwUqsIxLa0svIX_SUm1reTtnpy1IZpWh12umN_V7OMC-0a8P6MSXaLbGAt_a/exec"
CSV_HEADERS = [
    "Timestamp", "Iteration", "Test Name", "Status", "Duration (s)",
    "GHA Version", "iOS Version", "Device Name", "Wi-Fi SSID",
    "Failure Stage", "Error Message", "Log Directory", "Video File", "Host Machine",
    "Device IP Address", "Router Gateway", "Subnet Mask"
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
        failure_stage: str = "",
        log_dir: str = "",
        video_file: str = "",
        host_machine: str = "",
        device_ip: str = "UNKNOWN",
        router_gateway: str = "UNKNOWN",
        subnet_mask: str = "UNKNOWN"
) -> None:
    """Record test result to local CSV and upload to Google Sheet Webhook."""
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
        device_ip,
        router_gateway,
        subnet_mask
    ]
    try:
        with open(CSV_FILE_PATH, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(CSV_HEADERS)
            writer.writerow(row)
        logger.info(f"Test result saved locally to {CSV_FILE_PATH}")
    except Exception as e:
        logger.error(f"Failed to write CSV: {e}")
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
        "device_ip": device_ip,
        "router_gateway": router_gateway,
        "subnet_mask": subnet_mask,
        "row": row,
        "values": row
    }
    try:
        req = urllib.request.Request(
            constants.GOOGLE_SHEET_WEBHOOK_URL,
            data=json.dumps(payload_data).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res_body = response.read().decode("utf-8")
            logger.info(f"Google Sheet Webhook sync success: {res_body}")
    except Exception as e:
        logger.error(f"Failed to sync with Google Sheet Webhook: {e}")