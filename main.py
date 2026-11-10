"""Main entry point for iOS Automation Test Execution."""
import argparse
from typing import Any, List, Optional
from core.test_runner import MultiProjectTestRunner


def _parse_list_arg(raw_value: Any) -> Optional[List[str]]:
    """Parse command line list arguments supporting comma or space separation.
    Preserves single device names with spaces (e.g. 'Living Room Camera') when no comma is present.
    """
    if not raw_value:
        return None
    if isinstance(raw_value, list):
        joined = " ".join(raw_value)
    else:
        joined = str(raw_value).strip()
    if "," in joined:
        items = [item.strip() for item in joined.split(",") if item.strip()]
    elif isinstance(raw_value, list) and len(raw_value) > 1:
        items = [str(item).strip() for item in raw_value if str(item).strip()]
    else:
        items = [joined.strip()] if joined.strip() else []
    return items if items else None


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="iOS Automation Multi-Project Test Runner")
    parser.add_argument(
        "-a", "--app",
        choices=["igha", "ighp"],
        help="Target project to test: 'igha' (Google Home App) or 'ighp' (Home Platform Sample App)"
    )
    parser.add_argument(
        "-d", "--device_name",
        type=str,
        nargs="+",
        help='(Optional) Target device name(s). Accepts multiple comma-separated names, e.g. --device_name="device1, device2"'
    )
    parser.add_argument(
        "-p", "--pairing_code",
        type=str,
        nargs="+",
        help='(Optional) Pairing code(s) for target devices, e.g. --pairing_code="34970112332, 12345678901"'
    )
    parser.add_argument(
        "-c", "--count",
        type=int,
        default=None,
        help="(Optional) Number of iterations to run. If omitted, runs indefinitely in an infinite loop."
    )
    parser.add_argument(
        "-r", "--room_name",
        type=str,
        default="Attic",
        help="(Optional) Target room name to select or create, e.g. --room_name='Attic' or --room_name='Living Room'",
    )
    parser.add_argument(
        "-b", "--component_id",
        type=str,
        default="1796386",
        help="Target Buganizer Component ID to file a new issue (e.g. 1453086)"
    )
    # Multi-phone / multi-terminal isolation options (all optional; backward-compatible when omitted)
    parser.add_argument(
        "-u", "--udid",
        type=str,
        default=None,
        help="(Optional) Target iPhone UDID for this terminal (overrides constants.IOS_CAPABILITIES['appium:udid'])."
    )
    parser.add_argument(
        "--wda_port",
        type=int,
        default=None,
        help="(Optional) Local port forwarded to WebDriverAgent (e.g. 8100 for Phone A, 8101 for Phone B)."
    )
    parser.add_argument(
        "--mjpeg_port",
        type=int,
        default=None,
        help="(Optional) Local port for WDA MJPEG stream. Auto-derived from --wda_port (9100, 9101, ...) if omitted."
    )
    parser.add_argument(
        "--ios_version",
        type=str,
        default=None,
        help="(Optional) Target iPhone iOS version (auto-detected via tidevice when --udid differs from default)."
    )
    parser.add_argument(
        "--appium_url",
        type=str,
        default=None,
        help="(Optional) Appium server URL for this terminal (default: constants.APPIUM_SERVER_URL, e.g. http://localhost:4723)."
    )
    parser.add_argument(
        "-s", "--adb_serial",
        type=str,
        nargs="+",
        default=None,
        help='(Optional) Target camera ADB serial(s) so ADB reset & log capture only touch this camera, e.g. --adb_serial="S1B1D22607000063".'
    )
    parser.add_argument(
        "--plug_name",
        type=str,
        nargs="+",
        default=None,
        help='(Optional) Specific Smart Plug name(s) to power-cycle in this terminal, e.g. --plug_name="Plug A".'
    )
    args = parser.parse_args()
    if args.device_name:
        args.device_name = _parse_list_arg(args.device_name)
    if args.pairing_code:
        args.pairing_code = _parse_list_arg(args.pairing_code)
    if args.adb_serial:
        args.adb_serial = _parse_list_arg(args.adb_serial)
    if args.plug_name:
        args.plug_name = _parse_list_arg(args.plug_name)
    return args


if __name__ == "__main__":
    args = parse_arguments()
    runner = MultiProjectTestRunner(**vars(args))
    runner.run()
