"""Unified device reset utility: Smart plug power-cycle + ADB factory reset for post-test cleanup."""
import os
import re
import shutil
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from common import constants
from utils import logging_utils
logger = logging_utils.get_logger(__name__, "device_reset")
RESET_METHOD_ADB = "adb_factory_reset"
DEFAULT_ADB_RESET_COMMAND = "ftsmisc -s reboot_mode factory_reset; reboot -f"
# Default ADB factory-reset configuration applied to all test runs regardless of device_name.
DEFAULT_ADB_RESET_CONFIG: Dict[str, Any] = {
    "method": RESET_METHOD_ADB,
    "adb_serial": "S1B1D22607000063",    # "" = default adb device (only one connected)
    "shell_command": DEFAULT_ADB_RESET_COMMAND,
    "ready_timeout_s": 60,       # wait for the device on adb before sending the command
    "command_timeout_s": 15,     # `reboot -f` cuts the adb connection, so the call may hang
    "offline_timeout_s": 30,     # the device must drop off adb, otherwise the reboot is not confirmed
    "wait_for_adb": True,        # block until the device is back on adb
    "online_timeout_s": 300,     # max wait for the device to come back after the reboot
    "post_reset_wait_s": 30,     # extra wait after adb is back so Matter/BLE advertising can start
}
# Kept for backward compatibility with any external references.
DEFAULT_DEVICE_RESET_CONFIG: Dict[str, Dict[str, Any]] = {
    "Ref2 Battery Camera": dict(DEFAULT_ADB_RESET_CONFIG),
}
_FTSMISC_ERROR_MARKERS = ("not found", "no such file", "denied", "usage", "invalid", "fail", "error")
# /proc/sys/kernel/random/boot_id, e.g. '5f9d3c2a-8b1e-4f7a-9c3d-2e1f0a9b8c7d'. Anything else = unreadable.
_BOOT_ID_RE = re.compile(r"^[0-9a-fA-F-]{16,}$")


class DeviceResetUtils:
    """Run Smart plug power-cycle + ADB factory reset without filtering by device name."""

    @staticmethod
    def _normalize(name: Optional[str]) -> str:
        """Case-insensitive key; ignores stray commas from the CLI (e.g. 'Onn Wired Indoor Camera,')."""
        return (name or "").strip().strip(",").strip().lower()

    @classmethod
    def get_config(cls, device_name: Optional[str] = None) -> Dict[str, Any]:
        """Return the ADB reset config (always returns a valid config dict regardless of device_name)."""
        cfg = dict(DEFAULT_ADB_RESET_CONFIG)
        custom = getattr(constants, "DEVICE_RESET_CONFIG", None)
        if isinstance(custom, dict) and custom:
            if any(k in custom for k in ("adb_serial", "shell_command", "ready_timeout_s", "wait_for_adb", "method")):
                cfg.update(custom)
            else:
                key = cls._normalize(device_name)
                matched = None
                if key:
                    for name, sub_cfg in custom.items():
                        if cls._normalize(name) == key and isinstance(sub_cfg, dict):
                            matched = sub_cfg
                            break
                if matched is None:
                    first_val = next(iter(custom.values()), None)
                    if isinstance(first_val, dict):
                        matched = first_val
                if matched:
                    cfg.update(matched)
        return cfg

    @classmethod
    def uses_adb_reset(cls, device_name: Optional[str] = None) -> bool:
        """True when ADB factory reset is enabled (always True by default)."""
        cfg = cls.get_config(device_name)
        return str(cfg.get("method", RESET_METHOD_ADB)) == RESET_METHOD_ADB

    @classmethod
    def describe(cls, device_name: Optional[str] = None) -> str:
        """Human-readable reset description used in logs."""
        return "Smart plug power-cycle + ADB factory reset"

    @classmethod
    def reset_device(
            cls, device_name: Optional[str], smart_plug_reset: Callable[[], Any], reason: str = "post-test cleanup"
    ) -> bool:
        """Run BOTH Smart plug power-cycle and ADB factory reset regardless of device_name.
        Args:
            device_name: Target device name (for logging only; does not filter behavior).
            smart_plug_reset: Callable that power-cycles the smart plug.
            reason: Short context for the log.
        Returns:
            True if both smart plug power-cycle and ADB factory reset succeeded.
        """
        label = str(device_name or "ALL").strip() or "ALL"
        tag = f"[DeviceReset:{label}]"
        plug_ok = False
        try:
            logger.info(f"{tag} Step 1/2: Running Smart plug power-cycle ({reason or 'n/a'})...")
            smart_plug_reset()
            plug_ok = True
            logger.info(f"{tag} Step 1/2: Smart plug power-cycle SUCCESS.")
        except Exception as e:
            logger.error(f"{tag} Step 1/2: Smart plug power-cycle FAILED: {e}")
        logger.info(f"{tag} Step 2/2: Running ADB factory reset ({reason or 'n/a'})...")
        adb_ok = cls.adb_factory_reset(label, reason=reason)
        logger.info(f"{tag} Step 2/2: ADB factory reset {'SUCCESS' if adb_ok else 'FAILED'}.")
        return plug_ok and adb_ok

    @staticmethod
    def _adb_binary() -> Optional[str]:
        """constants.ADB_PATH if set (must exist), otherwise `adb` from PATH."""
        configured = str(getattr(constants, "ADB_PATH", "") or "").strip()
        if configured:
            return configured if os.path.isfile(configured) else None
        return shutil.which("adb")

    @staticmethod
    def _run(cmd: List[str], timeout: float) -> Tuple[Optional[int], str]:
        """Run a command and capture stdout+stderr. Returns (returncode, output); returncode is None on timeout."""
        try:
            proc = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                timeout=timeout,
            )
            return proc.returncode, (proc.stdout or "").strip()
        except subprocess.TimeoutExpired as e:
            partial = e.stdout or b""
            if isinstance(partial, bytes):
                partial = partial.decode("utf-8", "replace")
            return None, partial.strip()
        except OSError as e:
            return -1, str(e)

    @classmethod
    def _adb_state(cls, base: List[str]) -> str:
        """'device' when online, otherwise 'offline' / 'unauthorized' / 'missing' / other adb state."""
        rc, out = cls._run(base + ["get-state"], timeout=10)
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        if rc == 0 and lines:
            return lines[-1]
        lowered = out.lower()
        for state in ("unauthorized", "offline"):
            if state in lowered:
                return state
        return "missing"

    @classmethod
    def _wait_for_state(
            cls, base: List[str], online: bool, timeout_s: float, poll_s: float, tag: str,
            also_online: Tuple[str, ...] = ()
    ) -> Tuple[bool, float, str]:
        """Poll `adb get-state` until the device is online (online=True) or gone (online=False).
        Args:
            also_online: Extra states that count as online (e.g. 'unauthorized' after a factory reset).
        Returns:
            (reached, elapsed_seconds, last_state)
        """
        start = time.time()
        next_report = 30.0
        while True:
            state = cls._adb_state(base)
            elapsed = time.time() - start
            is_online = state == "device" or state in also_online
            if is_online == online:
                return True, elapsed, state
            if elapsed >= timeout_s:
                return False, elapsed, state
            if elapsed >= next_report:
                target = "back online" if online else "offline"
                logger.info(
                    f"{tag} Waiting for device to be {target}... {elapsed:.0f}s/{timeout_s:.0f}s (state='{state}')"
                )
                next_report += 30.0
            time.sleep(poll_s)

    @staticmethod
    def _find_ftsmisc_error(output: str) -> str:
        """Return the first output line that looks like an ftsmisc failure, or ''. Best effort."""
        for line in (output or "").splitlines():
            lowered = line.lower()
            if ("ftsmisc" in lowered or "reboot_mode" in lowered) and \
                    any(marker in lowered for marker in _FTSMISC_ERROR_MARKERS):
                return line.strip()
        return ""

    @classmethod
    def _read_boot_id(cls, base: List[str]) -> str:
        """Linux kernel boot id (changes on every boot), or '' if it cannot be read."""
        rc, out = cls._run(base + ["shell", "cat /proc/sys/kernel/random/boot_id"], timeout=10)
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        if rc == 0 and lines and _BOOT_ID_RE.match(lines[-1]):
            return lines[-1]
        return ""

    @classmethod
    def adb_factory_reset(cls, device_name: str = "ALL", reason: str = "") -> bool:
        """Send the configured adb factory-reset command and wait for the device to come back.
        Flow: device online on adb -> read boot_id -> send command -> device drops off adb
              -> device back on adb -> boot_id changed (reboot confirmed) -> post_reset_wait_s.
        Never raises (KeyboardInterrupt still propagates).
        Returns:
            True if the reboot was confirmed, ftsmisc printed no error and (when wait_for_adb)
            the device came back on adb in time.
        """
        label = str(device_name or "ALL").strip() or "ALL"
        tag = f"[DeviceReset:{label}]"
        try:
            return cls._adb_factory_reset(label, reason, tag)
        except Exception as e:
            logger.error(f"{tag} Unexpected error during adb factory reset: {e}")
            return False

    @classmethod
    def _adb_factory_reset(cls, device_name: str, reason: str, tag: str) -> bool:
        started = time.time()
        cfg = cls.get_config(device_name) or {}
        adb = cls._adb_binary()
        if not adb:
            logger.error(f"{tag} 'adb' not found (PATH / constants.ADB_PATH). Factory reset NOT sent.")
            return False
        serial = str(cfg.get("adb_serial") or "").strip()
        base = [adb] + (["-s", serial] if serial else [])
        shell_cmd = str(cfg.get("shell_command") or DEFAULT_ADB_RESET_COMMAND).strip()
        ready_timeout = float(cfg.get("ready_timeout_s", 60))
        command_timeout = float(cfg.get("command_timeout_s", 15))
        offline_timeout = float(cfg.get("offline_timeout_s", 30))
        wait_for_adb = bool(cfg.get("wait_for_adb", True))
        online_timeout = float(cfg.get("online_timeout_s", 300))
        post_wait = float(cfg.get("post_reset_wait_s", 15))
        printable = f"adb{' -s ' + serial if serial else ''} shell \"{shell_cmd}\""
        logger.info(f"{tag} Factory reset requested ({reason or 'n/a'}): {printable}")
        try:
            subprocess.run(
                [adb, "start-server"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning(f"{tag} 'adb start-server' failed: {e}")
        online, waited, state = cls._wait_for_state(base, True, ready_timeout, 2.0, tag)
        if not online:
            _, devices = cls._run([adb, "devices", "-l"], timeout=10)
            logger.error(
                f"{tag} Device not online on adb after {waited:.0f}s (state='{state}'). Factory reset NOT sent.\n"
                f"`adb devices -l`:\n{devices}"
            )
            return False
        boot_id_before = cls._read_boot_id(base)
        logger.info(f"{tag} boot_id before reset: {boot_id_before or '<unavailable>'}")
        rc, output = cls._run(base + ["shell", shell_cmd], timeout=command_timeout)
        rc_text = "timeout" if rc is None else str(rc)
        logger.info(f"{tag} adb shell finished (rc={rc_text}). Output: {output[-500:] or '<empty>'}")
        ftsmisc_error = cls._find_ftsmisc_error(output)
        if ftsmisc_error:
            logger.error(
                f"{tag} ftsmisc reported an error; the device may reboot WITHOUT factory reset: {ftsmisc_error}"
            )
        already_back = False
        went_offline, t_offline, state = cls._wait_for_state(base, False, offline_timeout, 0.5, tag)
        if went_offline:
            logger.info(f"{tag} Device dropped off adb (state='{state}'). Factory reset in progress...")
        else:
            boot_id_now = cls._read_boot_id(base) if boot_id_before else ""
            if boot_id_now and boot_id_now != boot_id_before:
                logger.warning(f"{tag} Offline window missed, but boot_id changed: reboot confirmed.")
                already_back = True
            else:
                logger.error(
                    f"{tag} Device still online {t_offline:.0f}s after the command"
                    f"{' and boot_id unchanged' if boot_id_now else ''}. Reboot NOT confirmed."
                )
                return False
        # 4. Wait for the device to come back.
        back = True
        adb_authorized = True
        if wait_for_adb and not already_back:
            back, t_back, state = cls._wait_for_state(
                base, True, online_timeout, 2.0, tag, also_online=("unauthorized",)
            )
            if back and state == "unauthorized":
                adb_authorized = False
                logger.warning(
                    f"{tag} Device back on adb {t_back:.0f}s after the reboot, but adb is UNAUTHORIZED "
                    "(adb keys wiped by the factory reset?). boot_id cannot be verified; device log capture "
                    "and the next adb reset will fail until adb is authorized again."
                )
            elif back:
                logger.info(f"{tag} Device back on adb {t_back:.0f}s after the reboot.")
            else:
                _, devices = cls._run([adb, "devices", "-l"], timeout=10)
                logger.error(
                    f"{tag} Device NOT back on adb within {online_timeout:.0f}s (state='{state}'). "
                    "If adb is disabled after factory reset, set wait_for_adb=False and raise post_reset_wait_s.\n"
                    f"`adb devices -l`:\n{devices}"
                )
        rebooted = True
        if back and adb_authorized and boot_id_before and (already_back or wait_for_adb):
            boot_id_after = cls._read_boot_id(base)
            if boot_id_after and boot_id_after == boot_id_before:
                logger.error(f"{tag} boot_id unchanged after reconnect; the device did NOT reboot.")
                rebooted = False
            elif boot_id_after:
                logger.info(f"{tag} boot_id after reset: {boot_id_after} (changed).")
            else:
                logger.warning(f"{tag} boot_id unreadable after reconnect; relying on the offline/online transition.")
        if back and rebooted and post_wait > 0:
            logger.info(f"{tag} Waiting {post_wait:.0f}s for the device to start advertising...")
            time.sleep(post_wait)
        ok = back and rebooted and not ftsmisc_error
        logger.info(
            f"{tag} Factory reset {'COMPLETED' if ok else 'FINISHED WITH ERRORS'} "
            f"(total {time.time() - started:.0f}s)."
        )
        return ok