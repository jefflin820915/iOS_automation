"""Logging utilities for the automation project."""
import base64
import io
import logging
import os
import sys
import zipfile
from common import constants

_current_main_log_dir = None
_current_additional_log_dir = None
_registered_loggers = {}  # {logger_name: (logger, tag, formatter)}

def set_current_test_dirs(main_dir: str, additional_dir: str) -> None:
    """Activates log directories inside the current testcase and attaches file handlers."""
    global _current_main_log_dir, _current_additional_log_dir
    _current_main_log_dir = main_dir
    _current_additional_log_dir = additional_dir

    constants.MAIN_LOG_DIR = main_dir
    constants.ADDITIONAL_LOG_DIR = additional_dir
    os.makedirs(main_dir, exist_ok=True)
    os.makedirs(additional_dir, exist_ok=True)
    for logger_name, (logger, tag, formatter) in _registered_loggers.items():
        for h in list(logger.handlers):
            if isinstance(h, logging.FileHandler):
                h.close()
                logger.removeHandler(h)
        target_dir = main_dir if tag in ("env_info", "syslog", "console", "container") else additional_dir
        log_file = os.path.join(target_dir, f"LOG_{constants.TIMESTAMP}_{tag}.log")

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

def get_logger(name: str, tag: str = "general") -> logging.Logger:
    """Create and return a logger. Defers FileHandler until testcase directory is active."""
    logger_name = f"{name}.{tag}"
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    _registered_loggers[logger_name] = (logger, tag, formatter)
    if _current_main_log_dir and _current_additional_log_dir:
        target_dir = _current_main_log_dir if tag in ("env_info", "syslog", "console", "container") else _current_additional_log_dir
        log_file = os.path.join(target_dir, f"LOG_{constants.TIMESTAMP}_{tag}.log")
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger
def pull_ios_app_container(driver, bundle_id: str, dest_dir: str = None) -> None:
    """Pull sandbox folders from iOS device into Main log."""
    target_dir = dest_dir or _current_main_log_dir or constants.SESSION_LOG_DIR
    logger = get_logger(__name__, "container")
    logger.info(f"Starting to pull sandbox container folders for '{bundle_id}' into {target_dir}...")

    xcappdata_dir = os.path.join(target_dir, f"{bundle_id}.xcappdata")
    app_data_dir = os.path.join(xcappdata_dir, "AppData")
    plist_content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Version</key>
	<integer>1</integer>
</dict>
</plist>
"""
    try:
        os.makedirs(app_data_dir, exist_ok=True)
        plist_path = os.path.join(xcappdata_dir, "AppDataInfo.plist")
        with open(plist_path, "w", encoding="utf-8") as f:
            f.write(plist_content)
        logger.info("Created AppDataInfo.plist successfully.")
    except Exception as e:
        logger.warning(f"Failed to create AppDataInfo.plist: {e}")

    target_folders = ["Documents", "Library", "tmp"]
    for folder in target_folders:
        container_path = f"@{bundle_id}/{folder}"
        local_extract_path = os.path.join(app_data_dir, folder)
        logger.info(f"Pulling {container_path} from device...")
        try:
            zip_b64 = driver.pull_folder(container_path)
            if not zip_b64:
                logger.warning(f"Folder '{folder}' returned empty data.")
                continue
            zip_bytes = base64.b64decode(zip_b64)
            os.makedirs(local_extract_path, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                z.extractall(local_extract_path)
            logger.info(f"Successfully saved '{folder}' into xcappdata.")
        except Exception as e:
            logger.error(f"Failed to pull folder '{folder}': {e}")