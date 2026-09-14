# """Buganizer client for creating new issues and uploading log attachments with proper Google auth."""
# import json
# import os
# import re
# import shutil
# import subprocess
# import urllib.error
# import urllib.request
# from typing import List, Optional, Any
# from common import constants
# from utils import logging_utils
#
#
# logger = logging_utils.get_logger(__name__, "buganizer_client")
#
# class BuganizerClient:
#     """Client for creating new issues and uploading attachments in Google Buganizer."""
#     BUGANIZER_SCOPE = "https://www.googleapis.com/auth/buganizer"
#
#     def __init__(
#             self,
#             host: str = "enlin.c.googlers.com",
#             component_id: Optional[str] = None,
#             assignee: Optional[str] = None
#     ) -> None:
#         """Initialize Buganizer client.
#         Args:
#             component_id (str, optional): Target Component ID where new bugs are filed.
#             assignee (str, optional): Default assignee email. Defaults to enlin@google.com.
#         """
#         self.component_id = component_id or "1796386"
#         self.default_assignee = assignee or getattr(constants, "BUGANIZER_DEFAULT_ASSIGNEE", "enlin@google.com")
#         self.service = self._init_google_api_service()
#         self.host = host
#
#     def create_issue_via_cloudtop(self, title: str, description: str, assignee: str = "enlin@google.com") -> str:
#         """Execute buganizer-cli on Cloudtop via SSH."""
#         safe_title = title.replace('"', '\\"')
#         safe_desc = description.replace('"', '\\"')
#         cmd = [
#             "ssh", self.host,
#             f'/google/bin/releases/issue-tracker/buganizer-cli create '
#             f'--component {self.component_id} '
#             f'--title "{safe_title}" '
#             f'--body "{safe_desc}" '
#             f'--assignee "{assignee}" '
#             f'--priority P2 --severity S2'
#         ]
#         res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
#         return res.stdout
#
#     def _init_google_api_service(self) -> Optional[Any]:
#         """Initialize the official Google Issue Tracker API service client."""
#         try:
#             import google.auth
#             from googleapiclient.discovery import build
#             credentials, _ = google.auth.default(scopes=[self.BUGANIZER_SCOPE])
#             service = build("issuetracker", "v1", credentials=credentials, cache_discovery=False)
#             logger.info("Initialized Google Issue Tracker API service successfully.")
#             return service
#         except ImportError:
#             logger.warning(
#                 "google-api-python-client or google-auth not installed. "
#                 "Install via: pip install google-api-python-client google-auth"
#             )
#         except Exception as e:
#             logger.warning(f"Could not initialize Google API client: {e}")
#         return None
#
#     def _get_gcloud_token(self) -> Optional[str]:
#         """Fetch gcloud access token with Buganizer scope as fallback."""
#         try:
#             return subprocess.check_output(
#                 [
#                     "gcloud", "auth", "print-access-token",
#                     f"--scopes={self.BUGANIZER_SCOPE},https://www.googleapis.com/auth/cloud-platform"
#                 ],
#                 text=True,
#                 stderr=subprocess.DEVNULL
#             ).strip()
#         except Exception:
#             try:
#                 return subprocess.check_output(
#                     ["gcloud", "auth", "print-access-token"],
#                     text=True,
#                     stderr=subprocess.DEVNULL
#                 ).strip()
#             except Exception as e:
#                 logger.error(f"Failed to fetch gcloud token: {e}")
#                 return None
#
#     def create_issue(
#             self,
#             title: str,
#             description: str,
#             component_id: Optional[str] = None,
#             assignee: Optional[str] = None,
#             priority: str = "P2",
#             severity: str = "S2",
#             issue_type: str = "BUG"
#     ) -> Optional[str]:
#         """Create a brand new Buganizer issue via Cloudtop buganizer-cli bridge.
#         Args:
#             title (str): Issue title.
#             description (str): Issue description (Gemini Markdown).
#             component_id (str, optional): Buganizer component ID. Defaults to self.default_component_id.
#             assignee (str, optional): Assignee email. Defaults to self.default_assignee.
#             priority (str): Priority level (P0-P4). Defaults to 'P2'.
#             severity (str): Severity level (S0-S4). Defaults to 'S2'.
#             issue_type (str): Issue type. Defaults to 'BUG'.
#         Returns:
#             Optional[str]: Created Issue ID (e.g. '555600103') if successful, else None.
#         """
#         target_component = str(component_id or self.component_id)
#         target_assignee = assignee or self.default_assignee
#         logger.info(
#             f"Filing new Buganizer issue under component {target_component} "
#             f"(Assignee: {target_assignee}) via Cloudtop bridge '{self.host}'..."
#         )
#         local_temp_file = "/tmp/buganizer_description.md"
#         remote_temp_file = "/tmp/buganizer_description.md"
#         try:
#             with open(local_temp_file, "w", encoding="utf-8") as f:
#                 f.write(description)
#             scp_cmd = ["scp", local_temp_file, f"{self.host}:{remote_temp_file}"]
#             subprocess.run(scp_cmd, check=True, capture_output=True, timeout=15)
#             remote_cmd = (
#                 f"/google/bin/releases/issue-tracker/buganizer-cli create "
#                 f"--component {target_component} "
#                 f"--title '{title}' "
#                 f"--body_file '{remote_temp_file}' "
#                 f"--assignee '{target_assignee}' "
#                 f"--priority {priority} "
#                 f"--severity {severity}"
#             )
#             ssh_cmd = ["ssh", self.host, remote_cmd]
#             res = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30)
#             output = res.stdout + res.stderr
#             if res.returncode == 0:
#                 if match := re.search(r"(?:b/|issue\s+|issue:\s*)(\d{8,10})", output, re.IGNORECASE):
#                     issue_id = match.group(1)
#                     logger.info(f"Successfully created new Buganizer issue: b/{issue_id} (Assigned to {target_assignee})")
#                     return issue_id
#                 elif match := re.search(r"(\d{8,10})", output):
#                     issue_id = match.group(1)
#                     logger.info(f"Successfully created new Buganizer issue: b/{issue_id}")
#                     return issue_id
#             else:
#                 logger.error(f"Cloudtop buganizer-cli failed (exit code {res.returncode}): {output.strip()}")
#         except Exception as e:
#             logger.error(f"Failed to create Buganizer issue via Cloudtop bridge: {e}")
#         return None
#     def upload_attachments(self, issue_id: str, file_paths: List[str]) -> List[str]:
#         """Upload log files and screenshots to the newly created Buganizer issue via Cloudtop.
#         Args:
#             issue_id (str): Target Buganizer Issue ID.
#             file_paths (List[str]): List of absolute file paths on Mac.
#         Returns:
#             List[str]: List of uploaded file names.
#         """
#         uploaded: List[str] = []
#         for path in file_paths:
#             if not os.path.exists(path):
#                 continue
#             file_name = os.path.basename(path)
#             remote_path = f"/tmp/{file_name}"
#             logger.info(f"Uploading attachment '{file_name}' to b/{issue_id} via Cloudtop...")
#             try:
#                 scp_cmd = ["scp", path, f"{self.host}:{remote_path}"]
#                 subprocess.run(scp_cmd, check=True, capture_output=True, timeout=30)
#                 attach_cmd = [
#                     "ssh", self.host,
#                     f"/google/bin/releases/issue-tracker/buganizer-cli attachment add {issue_id} '{remote_path}'"
#                 ]
#                 attach_res = subprocess.run(attach_cmd, capture_output=True, text=True, timeout=60)
#                 if attach_res.returncode == 0:
#                     logger.info(f"Successfully uploaded attachment '{file_name}' to b/{issue_id}")
#                     uploaded.append(file_name)
#                 else:
#                     logger.warning(f"Failed to attach '{file_name}': {attach_res.stderr}")
#             except Exception as e:
#                 logger.error(f"Error uploading attachment '{file_name}': {e}")
#         return uploaded