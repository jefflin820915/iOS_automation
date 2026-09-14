"""Main entry point for iOS Automation Test Execution."""

import argparse
from core.test_runner import MultiProjectTestRunner


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="iOS Automation Multi-Project Test Runner")
    parser.add_argument("-a", "--app",
        choices=["igha", "ighp"],
        help="Target project to test: 'igha' (Google Home App) or 'ighp' (Home Platform Sample App)")
    parser.add_argument('-d','--device_name',
                        type=str,
                        help='(Optional) Enable account switching, --device_name="device1"')
    parser.add_argument('-p', '--pairing_code',
                        type=str,
                        help='(Optional) Enable account switching, --pairing_code="34970112332"')
    parser.add_argument(
        "-c", "--count",
        type=int,
        default=None,
        help="(Optional) Number of iterations to run. If omitted, runs indefinitely in an infinite loop.")
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
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    runner = MultiProjectTestRunner(**vars(args))
    runner.run()