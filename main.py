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
    args = parser.parse_args()
    if args.device_name:
        args.device_name = _parse_list_arg(args.device_name)
    if args.pairing_code:
        args.pairing_code = _parse_list_arg(args.pairing_code)
    return args

if __name__ == "__main__":
    args = parse_arguments()
    runner = MultiProjectTestRunner(**vars(args))
    runner.run()