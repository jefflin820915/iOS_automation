"""Upload test artifacts (per-case log directories, app containers, session logs) to Google Drive.
Usage pattern (see core/test_runner.py):
    uploader = DriveUploader.create_if_enabled()
    folder_id, url = uploader.reserve_folder(run_folder_name, case_folder_name)  # sync, fast
    uploader.upload_async(folder_id, local_dir=case_dir)                         # background
    ...
    uploader.wait_all()                                                          # end of run
Any upload failure is logged and swallowed; it must never fail a test case.
"""
import os
import shutil
import tempfile
import threading
import time
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Dict, Iterable, List, Optional, Tuple
from common import constants
from utils import logging_utils
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    _DRIVE_LIBS_AVAILABLE = True
except ImportError:
    _DRIVE_LIBS_AVAILABLE = False
logger = logging_utils.get_logger(__name__, "runner")
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ROOT_FOLDER_ID = getattr(
    constants, "DRIVE_LOG_ROOT_FOLDER_ID", "1pc1A6ht1cIQCJhbl1wkK0JXyrr-fTHEm")
DEFAULT_CLIENT_SECRET_PATH = getattr(
    constants, "DRIVE_CLIENT_SECRET_PATH",
    os.path.join(_PROJECT_ROOT, "credentials", "drive_client_secret.json"))
DEFAULT_TOKEN_PATH = getattr(
    constants, "DRIVE_TOKEN_PATH",
    os.path.join(_PROJECT_ROOT, "credentials", "drive_token.json"))


class _UploadAborted(Exception):
    """Raised inside worker threads when abort() has been requested."""


class DriveUploader:
    """Uploads artifacts into a Drive folder tree: root / run / case."""
    SCOPES = ["https://www.googleapis.com/auth/drive"]
    FOLDER_MIME = "application/vnd.google-apps.folder"
    FOLDER_URL_TEMPLATE = "https://drive.google.com/drive/folders/{}"
    CHUNK_SIZE = 8 * 1024 * 1024
    RESUMABLE_THRESHOLD = 5 * 1024 * 1024
    NUM_RETRIES = 5
    SKIP_FILENAMES = {".DS_Store"}
    # App containers are pulled during teardown and uploaded separately (zipped),
    # so directory walks skip them to avoid uploading half-written data twice.
    SKIP_NAME_MARKERS = (".xcappdata",)
    def __init__(
            self,
            root_folder_id: str = DEFAULT_ROOT_FOLDER_ID,
            client_secret_path: str = DEFAULT_CLIENT_SECRET_PATH,
            token_path: str = DEFAULT_TOKEN_PATH,
            max_workers: int = 2,
            zip_logs: bool = False,
    ):
        if not _DRIVE_LIBS_AVAILABLE:
            raise RuntimeError(
                "Drive libraries missing. Run: pip install google-api-python-client "
                "google-auth-oauthlib google-auth-httplib2")
        self.root_folder_id = root_folder_id
        self.client_secret_path = client_secret_path
        self.token_path = token_path
        self.zip_logs = zip_logs
        self._creds = self._load_credentials()
        self._local = threading.local()  # googleapiclient service objects are NOT thread-safe
        self._folder_cache: Dict[Tuple[str, str], str] = {}
        self._folder_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="drive-upload")
        self._jobs: List[Tuple[str, Future]] = []
        self._abort_event = threading.Event()
        self._closed = False

    @classmethod
    def create_if_enabled(cls) -> Optional["DriveUploader"]:
        """Return an uploader, or None if disabled / misconfigured (never raises)."""
        if not getattr(constants, "DRIVE_UPLOAD_ENABLED", True):
            logger.info("[DRIVE] Upload disabled by constants.DRIVE_UPLOAD_ENABLED.")
            return None
        try:
            uploader = cls(zip_logs=getattr(constants, "DRIVE_UPLOAD_ZIP_LOGS", False))
            logger.info(f"[DRIVE] Upload enabled. Root folder: {cls.folder_url(uploader.root_folder_id)}")
            return uploader
        except Exception as e:
            logger.warning(f"[DRIVE] Upload disabled (init failed): {e}")
            return None

    @classmethod
    def folder_url(cls, folder_id: str) -> str:
        return cls.FOLDER_URL_TEMPLATE.format(folder_id)

    def reserve_folder(self, run_folder: str, sub_folder: Optional[str] = None) -> Optional[Tuple[str, str]]:
        """Synchronously find/create root/run_folder[/sub_folder]. Returns (folder_id, url) or None."""
        try:
            folder_id = self._ensure_folder(run_folder, self.root_folder_id)
            if sub_folder:
                folder_id = self._ensure_folder(sub_folder, folder_id)
            return folder_id, self.folder_url(folder_id)
        except Exception as e:
            logger.error(f"[DRIVE] Failed to create folder '{run_folder}/{sub_folder or ''}': {e}")
            return None

    def upload_async(
            self,
            folder_id: str,
            local_dir: Optional[str] = None,
            extra_paths: Iterable[Optional[str]] = (),
            label: str = "",
    ) -> bool:
        """Queue a background upload.
        Args:
            folder_id: Target Drive folder.
            local_dir: Directory whose CONTENTS are mirrored into folder_id.
            extra_paths: Files (uploaded as-is) or directories (zipped, then uploaded).
            label: Human-readable label for logs.
        """
        if self._closed:
            logger.warning(f"[DRIVE] Uploader closed; skipping upload '{label}'.")
            return False
        paths = [p for p in extra_paths if p and os.path.exists(p)]
        has_dir = bool(local_dir and os.path.isdir(local_dir))
        if not has_dir and not paths:
            return False
        label = label or folder_id
        try:
            future = self._executor.submit(
                self._upload_job, local_dir if has_dir else None, paths, folder_id, label)
        except RuntimeError as e:
            logger.warning(f"[DRIVE] Could not queue upload '{label}': {e}")
            return False
        self._jobs.append((label, future))
        return True

    def wait_all(self, timeout_s: float = 1800.0) -> Dict[str, int]:
        """Block until all queued uploads finish (or timeout). Returns a summary dict."""
        summary = {"ok": 0, "partial": 0, "pending": 0}
        if self._jobs:
            logger.info(f"[DRIVE] Waiting for {len(self._jobs)} upload job(s) (timeout {timeout_s:.0f}s)...")
        deadline = time.time() + timeout_s
        for label, future in self._jobs:
            try:
                result = future.result(timeout=max(0.0, deadline - time.time()))
                summary["partial" if result.get("failed") else "ok"] += 1
            except FutureTimeoutError:
                summary["pending"] += 1
                logger.error(f"[DRIVE] Upload still running after timeout: {label}")
            except Exception as e:
                summary["partial"] += 1
                logger.error(f"[DRIVE] Upload job crashed for {label}: {e}")
        if summary["pending"]:
            self._abort_event.set()  # let stuck workers exit so the process doesn't hang
        self._jobs.clear()
        self._close()
        logger.info(f"[DRIVE] Upload summary: {summary}")
        return summary

    def abort(self) -> None:
        """Cancel queued jobs and make in-flight jobs stop at the next file/chunk."""
        self._abort_event.set()
        self._close()
        logger.warning("[DRIVE] Abort requested; remaining uploads cancelled.")

    def _load_credentials(self) -> "Credentials":
        creds = None
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, self.SCOPES)
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_token(creds)
                return creds
            except Exception as e:
                logger.warning(f"[DRIVE] Token refresh failed, re-authenticating: {e}")
        if not os.path.exists(self.client_secret_path):
            raise FileNotFoundError(f"OAuth client secret not found: {self.client_secret_path}")
        flow = InstalledAppFlow.from_client_secrets_file(self.client_secret_path, self.SCOPES)
        creds = flow.run_local_server(port=0)  # opens browser once; token cached afterwards
        self._save_token(creds)
        return creds

    def _save_token(self, creds: "Credentials") -> None:
        os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
        with open(self.token_path, "w") as f:
            f.write(creds.to_json())
        os.chmod(self.token_path, 0o600)

    def _service(self):
        service = getattr(self._local, "service", None)
        if service is None:
            service = build("drive", "v3", credentials=self._creds, cache_discovery=False)
            self._local.service = service
        return service

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:  # Python < 3.9
            self._executor.shutdown(wait=False)

    def _check_abort(self) -> None:
        if self._abort_event.is_set():
            raise _UploadAborted()

    def _is_skipped(self, name: str) -> bool:
        return name in self.SKIP_FILENAMES or any(m in name for m in self.SKIP_NAME_MARKERS)

    def _ensure_folder(self, name: str, parent_id: str) -> str:
        """Find or create a folder by name under parent (serialized to avoid duplicates)."""
        key = (parent_id, name)
        with self._folder_lock:
            cached = self._folder_cache.get(key)
            if cached:
                return cached
            escaped = name.replace("\\", "\\\\").replace("'", "\\'")
            query = (f"name = '{escaped}' and '{parent_id}' in parents "
                     f"and mimeType = '{self.FOLDER_MIME}' and trashed = false")
            resp = self._service().files().list(
                q=query, fields="files(id)", pageSize=1,
                supportsAllDrives=True, includeItemsFromAllDrives=True,
            ).execute(num_retries=self.NUM_RETRIES)
            found = resp.get("files", [])
            if found:
                folder_id = found[0]["id"]
            else:
                body = {"name": name, "mimeType": self.FOLDER_MIME, "parents": [parent_id]}
                folder_id = self._service().files().create(
                    body=body, fields="id", supportsAllDrives=True,
                ).execute(num_retries=self.NUM_RETRIES)["id"]
            self._folder_cache[key] = folder_id
            return folder_id

    def _upload_file(self, local_path: str, parent_id: str) -> str:
        self._check_abort()
        size = os.path.getsize(local_path)
        resumable = size > self.RESUMABLE_THRESHOLD
        media = MediaFileUpload(local_path, resumable=resumable,
                                chunksize=self.CHUNK_SIZE if resumable else -1)
        request = self._service().files().create(
            body={"name": os.path.basename(local_path), "parents": [parent_id]},
            media_body=media, fields="id", supportsAllDrives=True,
        )
        if not resumable:
            return request.execute(num_retries=self.NUM_RETRIES)["id"]
        response = None
        while response is None:
            self._check_abort()
            _, response = request.next_chunk(num_retries=self.NUM_RETRIES)
        return response["id"]

    def _upload_directory(self, local_dir: str, parent_id: str) -> Tuple[int, List[str]]:
        """Mirror local_dir's contents into parent_id (recursively)."""
        uploaded, failed = 0, []
        for dirpath, dirnames, filenames in os.walk(local_dir):
            dirnames[:] = sorted(d for d in dirnames if not self._is_skipped(d))
            rel = os.path.relpath(dirpath, local_dir)
            target_id = parent_id
            try:
                if rel != ".":
                    for part in rel.split(os.sep):
                        target_id = self._ensure_folder(part, target_id)
            except Exception as e:
                failed.append(f"{dirpath}/ (folder): {e}")
                continue
            for filename in sorted(filenames):
                if self._is_skipped(filename):
                    continue
                path = os.path.join(dirpath, filename)
                try:
                    self._upload_file(path, target_id)
                    uploaded += 1
                except _UploadAborted:
                    raise
                except Exception as e:
                    failed.append(f"{path}: {e}")
        return uploaded, failed

    @staticmethod
    def _zip_directory(local_dir: str, out_dir: str) -> str:
        local_dir = local_dir.rstrip(os.sep)
        zip_path = os.path.join(out_dir, os.path.basename(local_dir) + ".zip")
        base = os.path.dirname(local_dir)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, _, filenames in os.walk(local_dir):
                for filename in filenames:
                    full = os.path.join(dirpath, filename)
                    zf.write(full, os.path.relpath(full, base))
        return zip_path

    def _upload_as_zip(self, local_dir: str, parent_id: str) -> None:
        tmp_dir = tempfile.mkdtemp(prefix="drive_zip_")  # outside the log tree on purpose
        try:
            self._upload_file(self._zip_directory(local_dir, tmp_dir), parent_id)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _upload_job(self, local_dir: Optional[str], paths: List[str], folder_id: str, label: str) -> Dict:
        start = time.time()
        uploaded, failed = 0, []
        try:
            if local_dir:
                if self.zip_logs:
                    self._upload_as_zip(local_dir, folder_id)
                    uploaded += 1
                else:
                    count, errors = self._upload_directory(local_dir, folder_id)
                    uploaded += count
                    failed.extend(errors)
            for path in paths:
                try:
                    if os.path.isdir(path):
                        self._upload_as_zip(path, folder_id)
                    else:
                        self._upload_file(path, folder_id)
                    uploaded += 1
                except _UploadAborted:
                    raise
                except Exception as e:
                    failed.append(f"{path}: {e}")
        except _UploadAborted:
            failed.append("aborted")
        except Exception as e:
            failed.append(f"job error: {e}")
        elapsed = time.time() - start
        if failed:
            logger.warning(f"[DRIVE] {label}: uploaded={uploaded} failed={len(failed)} "
                           f"({elapsed:.1f}s). First error: {failed[0]}")
        else:
            logger.info(f"[DRIVE] {label}: uploaded {uploaded} item(s) in {elapsed:.1f}s.")
        return {"label": label, "uploaded": uploaded, "failed": failed}