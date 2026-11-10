"""CSV Reporter and Google Sheet Webhook Sync for iOS Automation (iGHA -> Sheet 1, iGHP -> Sheet 2)."""
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import urllib.request

from common import constants
from utils import logging_utils

logger = logging_utils.get_logger(__name__, "csv_report")


def _get_project_root() -> Path:
    """Traverse upwards to locate the project root directory containing main.py or core/."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "main.py").exists() or (parent / "core").exists():
            return parent
    # Fallback to 3 levels up (utils/csv_report/csv_report.py -> project_root)
    return current.parents[2] if len(current.parents) > 2 else current.parent


# Dynamically resolve project root and log directory
PROJECT_ROOT = _get_project_root()
LOG_DIR = PROJECT_ROOT / "log"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Dynamic CSV file path (portable across any machine and user)
CSV_FILE_PATH = str(LOG_DIR / "test_results.csv")

# Local unified CSV headers (23 columns: includes GHA Version + Sample App Version + SDK Version)
CSV_HEADERS = [
    "Timestamp", "Iteration", "Test Name", "Status", "Duration (s)",
    "GHA Version", "Sample App Version", "SDK Version", "iOS Version",
    "Device Name", "Wi-Fi SSID", "Failure Stage", "Error Message",
    "Log Directory", "Video File", "Host Machine",
    "Phone IP Address", "Router Gateway", "Subnet Mask",
    "Device ID", "Serial Number", "Software Version", "Device IP",
]

# Sheet 1 (GHA) headers — preserves existing 21-column Google Sheet 1 layout so historical rows never shift
GHA_SHEET_HEADERS = [
    "Timestamp", "Iteration", "Test Name", "Status", "Duration (s)",
    "GHA Version", "iOS Version", "Device Name", "Wi-Fi SSID",
    "Failure Stage", "Error Message", "Log Directory", "Video File", "Host Machine",
    "Phone IP Address", "Router Gateway", "Subnet Mask",
    "Device ID", "Serial Number", "Software Version", "Device IP",
]

# Sheet 2 (GHP) headers — 22-column Google Sheet 2 layout dedicated to GHP Sample App + SDK Version
GHP_SHEET_HEADERS = [
    "Timestamp", "Iteration", "Test Name", "Status", "Duration (s)",
    "Sample App Version", "SDK Version", "iOS Version", "Device Name", "Wi-Fi SSID",
    "Failure Stage", "Error Message", "Log Directory", "Video File", "Host Machine",
    "Phone IP Address", "Router Gateway", "Subnet Mask",
    "Device ID", "Serial Number", "Software Version", "Device IP",
]


def _upgrade_legacy_csv_if_needed(csv_path: str) -> None:
    """Auto-migrate an existing 21-column test_results.csv to the 23-column header without misaligning old rows."""
    if not os.path.isfile(csv_path) or os.path.getsize(csv_path) == 0:
        return
    try:
        with open(csv_path, mode="r", newline="", encoding="utf-8") as rf:
            rows = list(csv.reader(rf))
        if not rows:
            return
        header = rows[0]
        if "Sample App Version" in header and "SDK Version" in header:
            return
        if "GHA Version" not in header:
            return

        gha_idx = header.index("GHA Version")
        upgraded_rows = [CSV_HEADERS]
        for old_row in rows[1:]:
            if len(old_row) == len(header):
                upgraded_rows.append(
                    old_row[: gha_idx + 1] + ["N/A", "N/A"] + old_row[gha_idx + 1:]
                )
            else:
                upgraded_rows.append(old_row)

        parent_dir = os.path.dirname(os.path.abspath(csv_path))
        fd, tmp_path = tempfile.mkstemp(prefix=".csv_upgrade_", suffix=".csv", dir=parent_dir)
        try:
            with os.fdopen(fd, mode="w", newline="", encoding="utf-8") as wf:
                writer = csv.writer(wf)
                writer.writerows(upgraded_rows)
            os.replace(tmp_path, csv_path)
            logger.info(
                f"[CSV] Upgraded legacy CSV schema ({len(header)} -> {len(CSV_HEADERS)} columns) at {csv_path}"
            )
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
    except Exception as err:
        logger.warning(f"[CSV] Skipped legacy CSV header migration check: {err}")


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
        device_ip: str = "UNKNOWN",
        app: str = "igha",
        sample_app_version: str = "N/A",
        sdk_version: str = "N/A",
) -> None:
    """Record testcase telemetry to local CSV and upload payload to Google Sheet Webhook.

    - Local CSV (`log/test_results.csv`): always writes all 23 unified columns.
    - Google Sheet Webhook:
      * `app == "igha"` -> routes to `Sheet 1` (21 columns, keeping existing GHA sheet intact).
      * `app == "ighp"` -> routes to `Sheet 2` (22 columns, with Sample App Version & SDK Version).
    """
    os.makedirs(os.path.dirname(os.path.abspath(CSV_FILE_PATH)), exist_ok=True)
    _upgrade_legacy_csv_if_needed(CSV_FILE_PATH)
    file_exists = os.path.isfile(CSV_FILE_PATH) and os.path.getsize(CSV_FILE_PATH) > 0

    app_norm = (app or "igha").strip().lower()
    is_ghp = app_norm == "ighp"

    if is_ghp:
        csv_gha_version = gha_version if (
                gha_version and gha_version not in ("4.29.25", "")) else "N/A"
        csv_sample_version = sample_app_version or "UNKNOWN"
        csv_sdk_version = sdk_version or "UNKNOWN"
    else:
        csv_gha_version = gha_version or "UNKNOWN"
        csv_sample_version = sample_app_version if sample_app_version else "N/A"
        csv_sdk_version = sdk_version if sdk_version else "N/A"

    duration_s = round((end_time - start_time).total_seconds(), 2)
    timestamp_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
    iteration_str = f"Iter {iteration}"

    csv_row = [
        timestamp_str,
        iteration_str,
        test_name,
        status,
        duration_s,
        csv_gha_version,
        csv_sample_version,
        csv_sdk_version,
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
        device_ip,
    ]

    try:
        with open(CSV_FILE_PATH, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(CSV_HEADERS)
            writer.writerow(csv_row)
        logger.info(
            f"[CSV] Appended telemetry row for '{test_name}' ({app_norm}) to {CSV_FILE_PATH}")
    except Exception as e:
        logger.error(f"[CSV] Failed to append row to CSV: {e}")

    if is_ghp:
        target_sheet_name = "Sheet 2"
        target_sheet_index = 2
        sheet_headers = GHP_SHEET_HEADERS
        sheet_row = [
            timestamp_str,
            iteration_str,
            test_name,
            status,
            duration_s,
            csv_sample_version,
            csv_sdk_version,
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
            device_ip,
        ]
    else:
        target_sheet_name = "Sheet 1"
        target_sheet_index = 1
        sheet_headers = GHA_SHEET_HEADERS
        sheet_row = [
            timestamp_str,
            iteration_str,
            test_name,
            status,
            duration_s,
            csv_gha_version,
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
            device_ip,
        ]

    payload_data = {
        "app": app_norm,
        "sheet_name": target_sheet_name,
        "sheet_index": target_sheet_index,
        "headers": sheet_headers,
        "timestamp": timestamp_str,
        "iteration": iteration_str,
        "test_name": test_name,
        "status": status,
        "duration_s": duration_s,
        "gha_version": csv_gha_version,
        "sample_app_version": csv_sample_version,
        "sdk_version": csv_sdk_version,
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
        "row": sheet_row,
        "values": sheet_row,
        "csv_row": csv_row,
    }

    webhook_url = getattr(constants, "GOOGLE_SHEET_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning(
            "[WEBHOOK] GOOGLE_SHEET_WEBHOOK_URL is not defined in constants. Skipping sync.")
        return

    try:
        logger.info(
            f"[WEBHOOK] Uploading telemetry for '{test_name}' (app={app_norm} -> {target_sheet_name}) to Google Sheet..."
        )
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload_data).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            res_body = response.read().decode("utf-8")
            logger.info(f"[GOOGLE SHEET SYNC] Webhook upload response: {res_body}")
    except Exception as e:
        logger.error(f"[GOOGLE SHEET SYNC] Webhook synchronization failed: {e}")
