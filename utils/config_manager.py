"""Module for managing application configuration.

This module provides a singleton class `ConfigManager` that handles loading,
validating, and retrieving application configuration settings. It supports
loading configuration from JSON files, validating the structure and types of
the configuration, and providing access to specific configuration values.
"""
import dataclasses
# Standard library imports
import json
import pathlib
from typing import Any, ClassVar, Optional, List, Dict

# Local application imports
from utils import logging_utils
dataclass = dataclasses.dataclass
Path = pathlib.Path

# Constants
CONFIG_DIR = 'config'
PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / CONFIG_DIR

# Initialize logger
logger = logging_utils.get_logger(__name__)


# Type definitions
@dataclass
class Config:
    """Main configuration structure data class.

    This class represents the main configuration file using dataclass
    to provide type checking for configuration keys and values.

    Attributes:
        login_account: Account for authentication
        login_password: Password for authentication
        package_name: Name of the application package
        pin_code: PIN code for authentication
        personal_profile_id: ID of the personal profile
        test_serial: Optional test serial number
        devices: Dictionary mapping device types to lists of device names
    """
    login_account: str
    login_password: str
    package_name: str
    pin_code: str
    personal_profile_id: int
    devices: Dict[str, List[str]]
    test_serial: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Config':
        """Create a Config instance from a dictionary.

        Args:
            data: Dictionary containing configuration data

        Returns:
            Config instance
        """

        return cls(
            login_account=data.get('login_account', ''),
            login_password=data.get('login_password', ''),
            package_name=data.get('package_name', ''),
            pin_code=data.get('pin_code', ''),
            personal_profile_id=data.get('personal_profile_id', 0),
            devices=data.get('devices', {}),
            test_serial=data.get('test_serial'),
        )


class ConfigManager:
    """Singleton class for managing application configuration.

    This class implements the Singleton pattern to ensure only one instance
    of the configuration manager exists throughout the application lifecycle.

    Attributes:
        _instance: Class variable holding the singleton instance
        _config: Class variable holding the current configuration
    """

    _instance: ClassVar[Optional['ConfigManager']] = None
    """Singleton instance of the class"""
    _config: ClassVar[Optional[Config]] = None
    """Current configuration data"""

    def __new__(cls) -> 'ConfigManager':
        """Create or return the singleton instance.

        Returns:
            The singleton instance of ConfigManager
        """
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
        return cls._instance

    @classmethod
    def _validate_config(cls, config: Config) -> None:
        """Validate the loaded configuration.

        Args:
            config: Config object containing configuration settings

        Raises:
            ValueError: If configuration is invalid
        """
        if not isinstance(config, Config):
            raise ValueError('Invalid configuration type')
        if not config.login_account:
            raise ValueError('login_account is required')
        if not config.login_password:
            raise ValueError('login_password is required')
        if not config.package_name:
            raise ValueError('package_name is required')

        # Validate device configurations
        for device_type, device_list in config.devices.items():
            if not isinstance(device_list, list):
                raise ValueError(f'Invalid device config type for {device_type}')

    @classmethod
    def set_config(cls, config: Config) -> None:
        """Set the current configuration.

        Args:
            config: Config object containing configuration settings

        Raises:
        """
        cls._validate_config(config)
        cls._config = config
        logger.info('Configuration loaded successfully')

    @classmethod
    def get_config(cls, config_file: Optional[str] = None) -> Optional[Config]:
        """Retrieve the current configuration.

        Args:
            config_file: Optional path to configuration file

        Returns:
            Current configuration dictionary or None if not loaded

        Raises:
            ValueError: If configuration file cannot be loaded
        """
        if config_file and not cls._config:
            cls.load_config(config_file)
        return cls._config

    @classmethod
    def get_value(cls, key: str, default: Any = None) -> Any:
        """Get a specific configuration value.

        Args:
            key: Configuration key to retrieve
            default: Default value if key not found

        Returns:
            Configuration value or default if not found

        Raises:
            ValueError: If configuration is not loaded
        """
        if cls._config is None:
            raise ValueError('Configuration not loaded')
        return getattr(cls._config, key, default)

    @classmethod
    def load_from_file(cls, file_path: str) -> None:
        """Load configuration from a JSON file.

        Args:
            file_path: Path to the configuration file

        Raises:
            FileNotFoundError: If configuration file does not exist
            json.JSONDecodeError: If file contains invalid JSON
            ValueError: If configuration validation fails
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            config = Config.from_dict(config_data)
            cls.set_config(config)
        except FileNotFoundError:
            logger.error(f'Configuration file not found: {file_path}')
            raise
        except json.decoder.JSONDecodeError:
            logger.error(f'Invalid JSON in configuration file: {file_path}')
            raise
        except TypeError as e:
            logger.error(f'Invalid config data: {str(e)}')
            raise ValueError(f'Invalid config data: {str(e)}') from e
        except ValueError as e:
            logger.error(f'Invalid config value: {str(e)}')
            raise
        except Exception as e:
            logger.error(f'Error loading config file: {str(e)}')
            raise

    @classmethod
    def get_device_config(cls, device_type: str) -> Optional[List[str]]:
        """Get configuration for a specific device type."""
        return (
            cls._config.devices.get(device_type)
            if cls._config and cls._config.devices
            else None
        )

    @classmethod
    def get_agent_id(cls) -> str:
        """Get agent ID from configuration.

        Returns:
            Agent ID or empty string if not found
        """
        return getattr(cls._config, 'agent_id', '') if cls._config else ''

    @classmethod
    def get_login_account(cls) -> str:
        """Get login account from configuration.

        Returns:
            Login account or empty string if not found
        """
        return getattr(cls._config, 'login_account', '') if cls._config else ''

    @classmethod
    def get_login_password(cls) -> str:
        """Get login password from configuration.

        Returns:
            Login password or empty string if not found
        """
        return getattr(cls._config, 'login_password', '') if cls._config else ''

    @classmethod
    def get_package_name(cls) -> str:
        """Get package name from configuration.

        Returns:
            Package name or empty string if not found
        """
        return getattr(cls._config, 'package_name', '') if cls._config else ''

    @classmethod
    def get_personal_profile_id(cls) -> int:
        """Get personal profile ID from configuration.

        Returns:
            Personal profile ID or 0 if not found
        """
        return getattr(cls._config, 'personal_profile_id', 0) if cls._config else 0

    @classmethod
    def get_test_serial(cls) -> str:
        """Get test serial from configuration.

        Returns:
            Test serial or empty string if not found
        """
        return getattr(cls._config, 'test_serial', '') if cls._config else ''

    @classmethod
    def load_config(cls, config_file: str) -> None:
        """Load configuration from file.

        Args:
            config_file: Name of the configuration file

        Raises:
            ValueError: If configuration file cannot be loaded
        """
        try:
            # First try to find the config file in the current directory
            config_path = Path(config_file)
            if not config_path.exists():
                # If not found, try the default config directory
                config_path = DEFAULT_CONFIG_PATH / config_file

            if not config_path.exists():
                raise FileNotFoundError(f'Configuration file not found: {config_file}')

            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            config = Config.from_dict(config_data)
            cls.set_config(config)
        except Exception as e:
            logger.error(f'Error loading config file {config_file}: {str(e)}')
            raise ValueError(
                f'Error loading config file {config_file}: {str(e)}'
            ) from e

    @classmethod
    def get_pin_code(cls) -> str:
        """Get test serial from configuration.

        Returns:`
            Test serial or empty string if not found
        """
        return getattr(cls._config, 'pin_code', '') if cls._config else ''

    @classmethod
    def get_starter_device_list(cls) -> List[str]:
        """Get starter device from configuration.

        Returns:
            List of starter devices or empty list if not found
        """
        return cls._config.devices.get('starter_device', []) if cls._config else []

    @classmethod
    def get_action_device_list(cls) -> List[str]:
        """Get action device from configuration.

        Returns:
            List of action devices or empty list if not found
        """
        return cls._config.devices.get('action_device', []) if cls._config else []

    @classmethod
    def get_action_device_status_list(cls) -> List[str]:
        """Get action device status from configuration.

        Returns:
            List of action device statuses or empty list if not found
        """
        return (
            cls._config.devices.get('action_device_status', [])
            if cls._config
            else []
        )

    @classmethod
    def get_action_device_list(cls) -> List[str]:
        """Get action device from configuration.

        Returns:
            List of action devices or empty list if not found
        """
        return cls._config.devices.get('action_device', []) if cls._config else []

    @classmethod
    def get_action_device_status_list(cls) -> List[str]:
        """Get action device status from configuration.

        Returns:
            List of action device statuses or empty list if not found
        """
        return (
            cls._config.devices.get('action_device_status', [])
            if cls._config
            else []
        )
