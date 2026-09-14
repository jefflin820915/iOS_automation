"""Base test class providing automatic session delegation and CLI arguments to all test classes."""

from typing import Any, Optional


class BaseTestCase:
    """Base class for all test classes."""

    def __init__(
            self,
            session: Optional[Any] = None,
            device_name: Optional[str] = None,
            pairing_code: Optional[str] = None,
            room_name: Optional[str] = None,
    ) -> None:
        """Initialize BaseTestCase with active session and CLI parameters.

        Args:
            session: The active GHASession or GHPSession instance.
            device_name (str, optional): Target device name from CLI.
            pairing_code (str, optional): Pairing code from CLI.
        """
        self.session = session
        self.device_name = device_name
        self.pairing_code = pairing_code
        self.room_name = room_name

    def __getattr__(self, name: str) -> Any:
        """Automatically delegate any missing attribute or method lookup to self.session."""
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)

        if self.session and hasattr(self.session, name):
            return getattr(self.session, name)

        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")