"""Unified device reset utility: Smart plug power-cycle + ADB factory reset for post-test cleanup."""

import os
import re
import shlex
import shutil
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from common import constants
from utils import logging_utils

logger = logging_utils.get_logger(__name__, "device_reset")
RESET_METHOD_ADB = "adb_factory_reset"
DEFAULT_ADB_RESET_COMMAND = "ftsmisc -s reboot_mode factory_reset; reboot -f"
DEFAULT_ADB_RESET_ALL_PIPELINE = (
    "{adb} devices | grep -v List | awk '{{print $1}}' | grep -v '^$' | "
    "xargs -I {{}} sh -c 'echo \"reset device: {{}}\"; {adb} -s {{}} shell \"{shell_cmd}\"'"
)
# Default ADB factory-reset configuration applied to all test runs regardless of device_name.
DEFAULT_ADB_RESET_CONFIG: Dict[str, Any] = {
    "method": RESET_METHOD_ADB,
    "adb_serial": "",  # "" = reset ALL connected adb devices
    "shell_command": DEFAULT_ADB_RESET_COMMAND,
    "ready_timeout_s": 60,  # wait for adb device(s) before sending the command
    "command_timeout_s": 15,  # `reboot -f` cuts the adb connection, so the call may hang
    "offline_timeout_s": 30,  # devices must drop off adb, otherwise the reboot is not confirmed
    "wait_for_adb": True,  # block until devices are back on adb
    "online_timeout_s": 300,  # max wait for devices to come back after the reboot
    "post_reset_wait_s": 30,  # extra wait after adb is back so Matter/BLE advertising can start
}
# Kept for backward compatibility with any external references.
DEFAULT_DEVICE_RESET_CONFIG: Dict[str, Dict[str, Any]] = {
    "Ref2 Battery Camera": dict(DEFAULT_ADB_RESET_CONFIG),
}
_FTSMISC_ERROR_MARKERS = (
    "not found",
    "no such file",
    "denied",
    "usage",
    "invalid",
    "fail",
    "error",
)
# /proc/sys/kernel/random/boot_id, e.g. '5f9d3c2a-8b1e-4f7a-9c3d-2e1f0a9b8c7d'. Anything else = unreadable.
_BOOT_ID_RE = re.compile(r"^[0-9a-fA-F-]{16,}$")


class DeviceResetUtils:
    """Run Smart plug power-cycle + ADB factory reset across all connected ADB devices."""

    @staticmethod
    def _normalize(name: Optional[str]) -> str:
        """Case-insensitive key; ignores stray commas from the CLI (e.g. 'Onn Wired Indoor Camera,')."""
        return (name or "").strip().strip(",").strip().lower()

    @classmethod
    def get_config(cls, device_name: Optional[str] = None) -> Dict[str, Any]:
        """Return the ADB reset config (defaults to resetting ALL connected `adb devices`).

        Note: Legacy per-device `adb_serial` values in `constants.DEVICE_RESET_CONFIG`
        (e.g. an older `'Ref2 Battery Camera': {'adb_serial': 'S1B1...'}`) are ignored so that
        all connected ADB cameras are always factory-reset together, unless `--adb_serial` was
        explicitly passed on the CLI (which writes `constants.DEVICE_RESET_CONFIG['*']`).
        """
        cfg = dict(DEFAULT_ADB_RESET_CONFIG)
        custom = getattr(constants, "DEVICE_RESET_CONFIG", None)
        if isinstance(custom, dict) and custom:
            if any(
                    k in custom
                    for k in
                    ("adb_serial", "shell_command", "ready_timeout_s", "wait_for_adb", "method")
            ):
                for k, v in custom.items():
                    if k == "adb_serial" and not custom.get("force_adb_serial"):
                        continue
                    cfg[k] = v
            else:
                key = cls._normalize(device_name)
                if key:
                    for name, sub_cfg in custom.items():
                        if cls._normalize(name) == key and isinstance(sub_cfg, dict):
                            for k, v in sub_cfg.items():
                                if k != "adb_serial":
                                    cfg[k] = v
                            break
                for wildcard_key in ("*", "__default__"):
                    wildcard_cfg = custom.get(wildcard_key)
                    if isinstance(wildcard_cfg, dict):
                        cfg.update(wildcard_cfg)
                        break
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
            cls,
            device_name: Optional[str],
            smart_plug_reset: Callable[[], Any],
            reason: str = "post-test cleanup",
    ) -> bool:
        """Run BOTH Smart plug power-cycle and ADB factory reset regardless of device_name."""
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

    COMMON_ADB_PATHS: Tuple[str, ...] = (
        "/opt/homebrew/bin/adb",
        "/usr/local/bin/adb",
        "~/Library/Android/sdk/platform-tools/adb",
        "/Library/Android/sdk/platform-tools/adb",
        "~/Android/Sdk/platform-tools/adb",
    )

    @classmethod
    def _adb_binary(cls) -> Optional[str]:
        """Resolve `adb` binary across constants.ADB_PATH, system PATH, and common macOS/SDK locations."""
        candidates: List[str] = []
        configured = getattr(constants, "ADB_PATH", None)
        if isinstance(configured, (list, tuple)):
            candidates.extend(str(p).strip() for p in configured if str(p).strip())
        elif configured:
            for part in str(configured).split(os.pathsep):
                if part.strip():
                    candidates.append(part.strip())
        which_adb = shutil.which("adb")
        if which_adb:
            candidates.append(which_adb)
        candidates.extend(cls.COMMON_ADB_PATHS)
        seen = set()
        for raw_path in candidates:
            expanded = os.path.expanduser(raw_path)
            if expanded in seen:
                continue
            seen.add(expanded)
            if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
                return expanded
        for raw_path in candidates:
            expanded = os.path.expanduser(raw_path)
            if os.path.isfile(expanded):
                return expanded
        return None

    @staticmethod
    def _run(
            cmd: List[str], timeout: float, extra_path_dir: Optional[str] = None
    ) -> Tuple[Optional[int], str]:
        """Run a command and capture stdout+stderr. Returns (returncode, output); returncode is None on timeout."""
        env = None
        if extra_path_dir:
            env = dict(os.environ)
            cur_path = env.get("PATH", "")
            env["PATH"] = f"{extra_path_dir}{os.pathsep}{cur_path}" if cur_path else extra_path_dir
        try:
            proc = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                timeout=timeout,
                env=env,
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
    def _list_adb_devices(cls, adb: str) -> Dict[str, str]:
        """Return {serial: state} for all entries in `adb devices`."""
        rc, out = cls._run([adb, "devices"], timeout=10)
        devices: Dict[str, str] = {}
        if rc != 0 and not out:
            return devices
        for raw_line in out.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("List of devices") or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                devices[parts[0]] = parts[1]
        return devices

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
    def _parse_target_serials(cls, raw_serial: Any) -> List[str]:
        """Normalize configured adb_serial (str or list/tuple) into an ordered list of unique serials."""
        if not raw_serial:
            return []
        if isinstance(raw_serial, (list, tuple, set)):
            parts = []
            for item in raw_serial:
                parts.extend(s.strip() for s in str(item).split(",") if s.strip())
        else:
            parts = [s.strip() for s in str(raw_serial).split(",") if s.strip()]
        seen = set()
        result: List[str] = []
        for s in parts:
            if s not in seen:
                seen.add(s)
                result.append(s)
        return result

    @classmethod
    def _wait_for_target_online_devices(
            cls, adb: str, target_serials: List[str], timeout_s: float, poll_s: float, tag: str
    ) -> Tuple[List[str], float, Dict[str, str]]:
        """Poll `adb devices` until all requested target_serials have state == 'device' (or timeout)."""
        start = time.time()
        next_report = 30.0
        while True:
            dev_map = cls._list_adb_devices(adb)
            online_targets = [s for s in target_serials if dev_map.get(s) == "device"]
            elapsed = time.time() - start
            if len(online_targets) == len(target_serials):
                return online_targets, elapsed, dev_map
            if elapsed >= timeout_s:
                return online_targets, elapsed, dev_map
            if elapsed >= next_report:
                logger.info(
                    f"{tag} Waiting for target adb device(s) {target_serials} to be online... "
                    f"{elapsed:.0f}s/{timeout_s:.0f}s (devices={dev_map})"
                )
                next_report += 30.0
            time.sleep(poll_s)

    @classmethod
    def _wait_for_any_online_devices(
            cls, adb: str, timeout_s: float, poll_s: float, tag: str
    ) -> Tuple[List[str], float, Dict[str, str]]:
        """Poll `adb devices` until at least one device has state == 'device'."""
        start = time.time()
        next_report = 30.0
        while True:
            dev_map = cls._list_adb_devices(adb)
            online_serials = [s for s, st in dev_map.items() if st == "device"]
            elapsed = time.time() - start
            if online_serials:
                return online_serials, elapsed, dev_map
            if elapsed >= timeout_s:
                return [], elapsed, dev_map
            if elapsed >= next_report:
                logger.info(
                    f"{tag} Waiting for adb devices to be online... {elapsed:.0f}s/{timeout_s:.0f}s (devices={dev_map})"
                )
                next_report += 30.0
            time.sleep(poll_s)

    @classmethod
    def _wait_for_state(
            cls,
            base: List[str],
            online: bool,
            timeout_s: float,
            poll_s: float,
            tag: str,
            also_online: Tuple[str, ...] = (),
    ) -> Tuple[bool, float, str]:
        """Poll `adb get-state` until the device is online (online=True) or gone (online=False)."""
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
            if ("ftsmisc" in lowered or "reboot_mode" in lowered) and any(
                    marker in lowered for marker in _FTSMISC_ERROR_MARKERS
            ):
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
        """Send the configured adb factory-reset command to all connected adb devices and wait for them to come back."""
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
            logger.error(
                f"{tag} 'adb' not found (PATH / constants.ADB_PATH). Factory reset NOT sent."
            )
            return False
        shell_cmd = str(cfg.get("shell_command") or DEFAULT_ADB_RESET_COMMAND).strip()
        ready_timeout = float(cfg.get("ready_timeout_s", 60))
        command_timeout = float(cfg.get("command_timeout_s", 15))
        offline_timeout = float(cfg.get("offline_timeout_s", 30))
        wait_for_adb = bool(cfg.get("wait_for_adb", True))
        online_timeout = float(cfg.get("online_timeout_s", 300))
        post_wait = float(cfg.get("post_reset_wait_s", 30))
        target_serials = cls._parse_target_serials(cfg.get("adb_serial"))

        if target_serials:
            printable = " && ".join(f'adb -s {s} shell "{shell_cmd}"' for s in target_serials)
        else:
            printable = DEFAULT_ADB_RESET_ALL_PIPELINE.format(adb="adb", shell_cmd=shell_cmd)
        logger.info(f"{tag} Factory reset requested ({reason or 'n/a'}): {printable}")

        try:
            subprocess.run(
                [adb, "start-server"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning(f"{tag} 'adb start-server' failed: {e}")

        if target_serials:
            serials, waited, dev_map = cls._wait_for_target_online_devices(
                adb, target_serials, ready_timeout, 2.0, tag
            )
            missing_targets = [s for s in target_serials if s not in serials]
            if missing_targets:
                _, devices = cls._run([adb, "devices", "-l"], timeout=10)
                logger.error(
                    f"{tag} Target adb device(s) {missing_targets} not online after {waited:.0f}s "
                    f"(devices={dev_map}).\n`adb devices -l`:\n{devices}"
                )
                if not serials:
                    return False
        else:
            missing_targets = []
            serials, waited, dev_map = cls._wait_for_any_online_devices(
                adb, ready_timeout, 2.0, tag
            )
            if not serials:
                _, devices = cls._run([adb, "devices", "-l"], timeout=10)
                logger.error(
                    f"{tag} No online adb devices after {waited:.0f}s (devices={dev_map}). "
                    f"Factory reset NOT sent.\n`adb devices -l`:\n{devices}"
                )
                return False

        logger.info(f"{tag} Online adb device(s) to reset ({len(serials)}): {serials}")
        boot_ids_before: Dict[str, str] = {}
        for s in serials:
            bid = cls._read_boot_id([adb, "-s", s])
            boot_ids_before[s] = bid
            logger.info(f"{tag} [{s}] boot_id before reset: {bid or '<unavailable>'}")

        if target_serials:
            chunks: List[str] = []
            for s in serials:
                s_rc, s_out = cls._run([adb, "-s", s, "shell", shell_cmd], timeout=command_timeout)
                s_rc_text = "timeout" if s_rc is None else str(s_rc)
                chunks.append(f"reset device: {s}\n{s_out}".strip())
                logger.info(
                    f"{tag} [{s}] targeted adb reset finished (rc={s_rc_text}). "
                    f"Output: {s_out[-300:] or '<empty>'}"
                )
            output = "\n".join(chunks)
        else:
            adb_dir = os.path.dirname(os.path.abspath(adb))
            if os.path.basename(adb) == "adb":
                exec_pipeline = DEFAULT_ADB_RESET_ALL_PIPELINE.format(
                    adb="adb", shell_cmd=shell_cmd
                )
                rc, output = cls._run(
                    ["sh", "-c", exec_pipeline],
                    timeout=command_timeout * max(1, len(serials)),
                    extra_path_dir=adb_dir,
                )
            else:
                exec_pipeline = DEFAULT_ADB_RESET_ALL_PIPELINE.format(
                    adb=shlex.quote(adb), shell_cmd=shell_cmd
                )
                rc, output = cls._run(
                    ["sh", "-c", exec_pipeline],
                    timeout=command_timeout * max(1, len(serials)),
                )
            rc_text = "timeout" if rc is None else str(rc)
            logger.info(
                f"{tag} adb reset pipeline finished (rc={rc_text}). Output:\n{output[-1000:] or '<empty>'}"
            )
            # If `reboot -f` on an earlier device hung xargs before a later device was reached, send directly to remaining serials.
            for s in serials:
                if f"reset device: {s}" not in (output or "") and f"reset devices: {s}" not in (
                        output or ""
                ):
                    logger.warning(
                        f"{tag} [{s}] Not reached in pipeline before timeout; sending direct adb reset..."
                    )
                    s_rc, s_out = cls._run(
                        [adb, "-s", s, "shell", shell_cmd], timeout=command_timeout
                    )
                    output = f"{output}\nreset device: {s}\n{s_out}".strip()
                    logger.info(
                        f"{tag} [{s}] direct adb shell finished (rc={s_rc}). Output: {s_out[-300:] or '<empty>'}"
                    )

        ftsmisc_error = cls._find_ftsmisc_error(output)
        if ftsmisc_error:
            logger.error(
                f"{tag} ftsmisc reported an error; device(s) may reboot WITHOUT factory reset: {ftsmisc_error}"
            )
        all_ok = (not ftsmisc_error) and (not missing_targets)

        # Phase 1: Confirm all reset devices drop off adb right after the reset command (parallel reboot window).
        offline_confirmed: Dict[str, bool] = {}
        already_back_map: Dict[str, bool] = {}
        for s in serials:
            s_base = [adb, "-s", s]
            s_tag = f"{tag}[{s}]"
            boot_id_before = boot_ids_before.get(s, "")
            went_offline, t_offline, state = cls._wait_for_state(
                s_base, False, offline_timeout, 0.5, s_tag
            )
            if went_offline:
                logger.info(
                    f"{s_tag} Device dropped off adb (state='{state}'). Factory reset in progress..."
                )
                offline_confirmed[s] = True
                already_back_map[s] = False
            else:
                boot_id_now = cls._read_boot_id(s_base) if boot_id_before else ""
                if boot_id_now and boot_id_now != boot_id_before:
                    logger.warning(
                        f"{s_tag} Offline window missed, but boot_id changed: reboot confirmed."
                    )
                    offline_confirmed[s] = True
                    already_back_map[s] = True
                else:
                    logger.error(
                        f"{s_tag} Device still online {t_offline:.0f}s after the command"
                        f"{' and boot_id unchanged' if boot_id_now else ''}. Reboot NOT confirmed."
                    )
                    offline_confirmed[s] = False
                    all_ok = False

        # Phase 2: Wait for all confirmed-rebooting devices to come back online and verify boot_id changed.
        online_deadline = time.time() + online_timeout
        for s in serials:
            if not offline_confirmed.get(s):
                continue
            s_base = [adb, "-s", s]
            s_tag = f"{tag}[{s}]"
            boot_id_before = boot_ids_before.get(s, "")
            already_back = already_back_map.get(s, False)
            back = True
            adb_authorized = True
            if wait_for_adb and not already_back:
                remaining_online_wait = max(5.0, online_deadline - time.time())
                back, t_back, state = cls._wait_for_state(
                    s_base,
                    True,
                    remaining_online_wait,
                    2.0,
                    s_tag,
                    also_online=("unauthorized",),
                )
                if back and state == "unauthorized":
                    adb_authorized = False
                    logger.warning(
                        f"{s_tag} Device back on adb {t_back:.0f}s after the reboot, but adb is UNAUTHORIZED "
                        "(adb keys wiped by the factory reset?). boot_id cannot be verified; device log capture "
                        "and the next adb reset will fail until adb is authorized again."
                    )
                elif back:
                    logger.info(f"{s_tag} Device back on adb {t_back:.0f}s after the reboot.")
                else:
                    _, devices = cls._run([adb, "devices", "-l"], timeout=10)
                    logger.error(
                        f"{s_tag} Device NOT back on adb within {online_timeout:.0f}s (state='{state}'). "
                        "If adb is disabled after factory reset, set wait_for_adb=False and raise post_reset_wait_s.\n"
                        f"`adb devices -l`:\n{devices}"
                    )
            rebooted = True
            if back and adb_authorized and boot_id_before and (already_back or wait_for_adb):
                boot_id_after = cls._read_boot_id(s_base)
                if boot_id_after and boot_id_after == boot_id_before:
                    logger.error(
                        f"{s_tag} boot_id unchanged after reconnect; the device did NOT reboot."
                    )
                    rebooted = False
                elif boot_id_after:
                    logger.info(f"{s_tag} boot_id after reset: {boot_id_after} (changed).")
                else:
                    logger.warning(
                        f"{s_tag} boot_id unreadable after reconnect; relying on the offline/online transition."
                    )
            if not (back and rebooted):
                all_ok = False

        if all_ok and post_wait > 0:
            logger.info(f"{tag} Waiting {post_wait:.0f}s for device(s) to start advertising...")
            time.sleep(post_wait)
        logger.info(
            f"{tag} Factory reset {'COMPLETED' if all_ok else 'FINISHED WITH ERRORS'} "
            f"(total {time.time() - started:.0f}s)."
        )
        return all_ok
