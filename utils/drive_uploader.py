"""Upload test artifacts to Google Drive via Google Drive for desktop (DriveFS).
Corp policy blocks custom OAuth clients (Error 400: access_not_configured), so instead of
calling the Drive API, artifacts are copied into the locally mounted Drive folder and
Google Drive for desktop syncs them to the cloud. No credentials are required.
The public API is identical to the former API-based uploader, so core/test_runner.py is
unchanged: create_if_enabled / reserve_folder / upload_async / wait_all / abort.
The "folder_id" values handed back to the runner are LOCAL folder paths.
"""
import glob
import os
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote
from common import constants
from utils import logging_utils
logger = logging_utils.get_logger(__name__, "runner")
DEFAULT_ROOT_FOLDER_ID = getattr(
    constants, "DRIVE_LOG_ROOT_FOLDER_ID", "1pc1A6ht1cIQCJhbl1wkK0JXyrr-fTHEm")
DEFAULT_LOCAL_ROOT = getattr(constants, "DRIVE_LOCAL_ROOT_PATH", "")
DRIVEFS_ITEM_ID_XATTR = "com.google.drivefs.item-id#S"
CLOUD_STORAGE_DIR = os.path.expanduser("~/Library/CloudStorage")
class _CopyAborted(Exception):
    """Raised inside worker threads when abort() has been requested."""
class DriveUploader:
    """Copies artifacts into a Drive-for-desktop folder tree: root / run / case."""
    FOLDER_URL_TEMPLATE = "https://drive.google.com/drive/folders/{}"
    SEARCH_URL_TEMPLATE = "https://drive.google.com/drive/search?q={}"
    SKIP_FILENAMES = {".DS_Store"}
    # App containers are pulled during teardown and copied separately (zipped),
    # so directory copies skip them to avoid copying half-written data twice.
    SKIP_NAME_MARKERS = (".xcappdata",)
    def __init__(
            self,
            local_root: str = DEFAULT_LOCAL_ROOT,
            root_folder_id: str = DEFAULT_ROOT_FOLDER_ID,
            max_workers: int = 1,
            zip_logs: bool = False,
            id_resolve_timeout_s: float = 2.0,
    ):
        local_root = os.path.expanduser(local_root or "")
        if not local_root or not os.path.isdir(local_root):
            raise FileNotFoundError(
                f"Drive-for-desktop folder not found: '{local_root}'. "
                f"Set constants.DRIVE_LOCAL_ROOT_PATH. Available roots: {self._candidate_roots()}")
        self.local_root = local_root
        self.root_folder_id = root_folder_id
        self.zip_logs = zip_logs
        self.id_resolve_timeout_s = id_resolve_timeout_s
        actual_id = self._read_item_id(local_root)
        if actual_id and root_folder_id and actual_id != root_folder_id:
            logger.warning(
                f"[DRIVE] '{local_root}' has Drive ID {actual_id}, expected {root_folder_id}. "
                "Artifacts will go to the local folder you configured.")
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="drive-copy")
        self._jobs: List[Tuple[str, Future]] = []
        self._abort_event = threading.Event()
        self._closed = False
    # ------------------------------------------------------------------ #
    # Factory
    # ------------------------------------------------------------------ #
    @classmethod
    def create_if_enabled(cls) -> Optional["DriveUploader"]:
        """Return an uploader, or None if disabled / misconfigured (never raises)."""
        if not getattr(constants, "DRIVE_UPLOAD_ENABLED", True):
            logger.info("[DRIVE] Upload disabled by constants.DRIVE_UPLOAD_ENABLED.")
            return None
        try:
            uploader = cls(
                zip_logs=getattr(constants, "DRIVE_UPLOAD_ZIP_LOGS", False),
                id_resolve_timeout_s=getattr(constants, "DRIVE_ID_RESOLVE_TIMEOUT_S", 2.0),
            )
            logger.info(f"[DRIVE] Upload enabled via Drive for desktop: {uploader.local_root}")
            return uploader
        except Exception as e:
            logger.warning(f"[DRIVE] Upload disabled (init failed): {e}")
            return None
    # ------------------------------------------------------------------ #
    # Public API (same as the former API-based uploader)
    # ------------------------------------------------------------------ #
    @classmethod
    def folder_url(cls, folder_id: str) -> str:
        return cls.FOLDER_URL_TEMPLATE.format(folder_id)
    def reserve_folder(self, run_folder: str, sub_folder: Optional[str] = None) -> Optional[Tuple[str, str]]:
        """Create local root/run_folder[/sub_folder]. Returns (local_path, url) or None."""
        try:
            path = os.path.join(self.local_root, run_folder)
            if sub_folder:
                path = os.path.join(path, sub_folder)
            os.makedirs(path, exist_ok=True)
            return path, self._resolve_url(path)
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
        """Queue a background copy into the Drive-for-desktop folder.
        Args:
            folder_id: Target LOCAL folder path (as returned by reserve_folder).
            local_dir: Directory whose CONTENTS are mirrored into folder_id.
            extra_paths: Files (copied as-is) or directories (zipped, then copied).
            label: Human-readable label for logs.
        """
        if self._closed:
            logger.warning(f"[DRIVE] Uploader closed; skipping '{label}'.")
            return False
        paths = [p for p in extra_paths if p and os.path.exists(p)]
        has_dir = bool(local_dir and os.path.isdir(local_dir))
        if not has_dir and not paths:
            return False
        label = label or os.path.basename(folder_id)
        try:
            future = self._executor.submit(
                self._copy_job, local_dir if has_dir else None, paths, folder_id, label)
        except RuntimeError as e:
            logger.warning(f"[DRIVE] Could not queue '{label}': {e}")
            return False
        self._jobs.append((label, future))
        return True
    def wait_all(self, timeout_s: float = 1800.0) -> Dict[str, int]:
        """Block until all local copies finish (or timeout). Cloud sync continues in DriveFS."""
        summary = {"ok": 0, "partial": 0, "pending": 0}
        if self._jobs:
            logger.info(f"[DRIVE] Waiting for {len(self._jobs)} copy job(s) (timeout {timeout_s:.0f}s)...")
        deadline = time.time() + timeout_s
        for label, future in self._jobs:
            try:
                result = future.result(timeout=max(0.0, deadline - time.time()))
                summary["partial" if result.get("failed") else "ok"] += 1
            except FutureTimeoutError:
                summary["pending"] += 1
                logger.error(f"[DRIVE] Copy still running after timeout: {label}")
            except Exception as e:
                summary["partial"] += 1
                logger.error(f"[DRIVE] Copy job crashed for {label}: {e}")
        if summary["pending"]:
            self._abort_event.set()
        self._jobs.clear()
        self._close()
        logger.info(f"[DRIVE] Copy summary: {summary}. Google Drive for desktop keeps syncing in the "
                    "background — keep it running (and the Mac awake) until sync completes.")
        return summary
    def abort(self) -> None:
        """Cancel queued jobs and make in-flight jobs stop at the next file."""
        self._abort_event.set()
        self._close()
        logger.warning("[DRIVE] Abort requested; remaining copies cancelled.")
    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    @staticmethod
    def _candidate_roots() -> List[str]:
        return sorted(glob.glob(os.path.join(CLOUD_STORAGE_DIR, "GoogleDrive-*", "*")))
    @staticmethod
    def _read_item_id(path: str) -> Optional[str]:
        """Read the Drive item ID DriveFS stores as an extended attribute (macOS)."""
        try:
            out = subprocess.run(
                ["xattr", "-p", DRIVEFS_ITEM_ID_XATTR, path],
                capture_output=True, text=True, timeout=2,
            )
        except Exception:
            return None
        item_id = out.stdout.strip() if out.returncode == 0 else ""
        if not item_id or item_id.lower().startswith("local"):
            return None  # not synced yet / no cloud ID assigned
        return item_id
    def _resolve_url(self, path: str) -> str:
        """Folder URL if DriveFS already assigned a cloud ID, else a Drive search URL by name."""
        deadline = time.time() + self.id_resolve_timeout_s
        while True:
            item_id = self._read_item_id(path)
            if item_id:
                return self.folder_url(item_id)
            if time.time() >= deadline:
                break
            time.sleep(0.5)
        return self.SEARCH_URL_TEMPLATE.format(quote(os.path.basename(path.rstrip(os.sep))))
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
            raise _CopyAborted()
    def _is_skipped(self, name: str) -> bool:
        return name in self.SKIP_FILENAMES or any(m in name for m in self.SKIP_NAME_MARKERS)
    def _copy_file(self, src: str, dst_dir: str) -> None:
        self._check_abort()
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copy2(src, os.path.join(dst_dir, os.path.basename(src)))
    def _copy_directory(self, src_dir: str, dst_dir: str) -> Tuple[int, List[str]]:
        """Mirror src_dir's contents into dst_dir (recursively)."""
        copied, failed = 0, []
        for dirpath, dirnames, filenames in os.walk(src_dir):
            dirnames[:] = sorted(d for d in dirnames if not self._is_skipped(d))
            rel = os.path.relpath(dirpath, src_dir)
            target = dst_dir if rel == "." else os.path.join(dst_dir, rel)
            for filename in sorted(filenames):
                if self._is_skipped(filename):
                    continue
                src = os.path.join(dirpath, filename)
                try:
                    self._copy_file(src, target)
                    copied += 1
                except _CopyAborted:
                    raise
                except Exception as e:
                    failed.append(f"{src}: {e}")
        return copied, failed
    def _copy_as_zip(self, src_dir: str, dst_dir: str) -> None:
        """Zip outside the log tree, then move the finished zip into the Drive folder."""
        self._check_abort()
        src_dir = src_dir.rstrip(os.sep)
        tmp_dir = tempfile.mkdtemp(prefix="drive_zip_")
        try:
            zip_path = os.path.join(tmp_dir, os.path.basename(src_dir) + ".zip")
            base = os.path.dirname(src_dir)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for dirpath, _, filenames in os.walk(src_dir):
                    for filename in filenames:
                        full = os.path.join(dirpath, filename)
                        zf.write(full, os.path.relpath(full, base))
            os.makedirs(dst_dir, exist_ok=True)
            shutil.move(zip_path, os.path.join(dst_dir, os.path.basename(zip_path)))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    def _copy_job(self, local_dir: Optional[str], paths: List[str], dst_dir: str, label: str) -> Dict:
        start = time.time()
        copied, failed = 0, []
        try:
            if local_dir:
                if self.zip_logs:
                    self._copy_as_zip(local_dir, dst_dir)
                    copied += 1
                else:
                    count, errors = self._copy_directory(local_dir, dst_dir)
                    copied += count
                    failed.extend(errors)
            for path in paths:
                try:
                    if os.path.isdir(path):
                        self._copy_as_zip(path, dst_dir)
                    else:
                        self._copy_file(path, dst_dir)
                    copied += 1
                except _CopyAborted:
                    raise
                except Exception as e:
                    failed.append(f"{path}: {e}")
        except _CopyAborted:
            failed.append("aborted")
        except Exception as e:
            failed.append(f"job error: {e}")
        elapsed = time.time() - start
        if failed:
            logger.warning(f"[DRIVE] {label}: copied={copied} failed={len(failed)} "
                           f"({elapsed:.1f}s). First error: {failed[0]}")
        else:
            logger.info(f"[DRIVE] {label}: copied {copied} item(s) to Drive folder in {elapsed:.1f}s.")
        return {"label": label, "copied": copied, "failed": failed}