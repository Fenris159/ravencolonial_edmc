"""
Configuration settings for Ravencolonial EDMC Plugin
"""

import os
import sys
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PluginConfig:
    """Configuration management for the Ravencolonial plugin"""
    
    # Plugin metadata
    NAME = os.path.basename(os.path.dirname(os.path.dirname(__file__)))
    VERSION = "1.6.5-dev"
    
    # API configuration
    DEFAULT_API_BASE = "https://ravencolonial100-awcbdvabgze4c5cq.canadacentral-01.azurewebsites.net"
    
    # Logging configuration
    LOG_LEVEL = logging.INFO
    # Use simple format - EDMC will handle the full formatting
    LOG_FORMAT = '%(name)s: %(levelname)s - %(message)s'
    LOG_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'
    LOG_TIME_MSEC_FORMAT = '%s.%03d'
    
    @staticmethod
    def get_api_base() -> str:
        """Get the API base URL from config or use default"""
        try:
            from config import config

            return config.get_str("ravencolonial_api_url") or PluginConfig.DEFAULT_API_BASE
        except (ImportError, AttributeError):
            # Fallback if EDMC config is not available
            return PluginConfig.DEFAULT_API_BASE
    
    @staticmethod
    def get_user_agent() -> str:
        """User-Agent for HTTP: EDMC core value plus plugin suffix (see PLUGINS.md)."""
        try:
            from config import user_agent as edmc_ua

            return f"{edmc_ua} Ravencolonial-Plugin/{PluginConfig.VERSION}"
        except ImportError:
            return f"EDMC-Ravencolonial/{PluginConfig.VERSION}"
    
    @staticmethod
    def setup_logging():
        """Setup logging configuration"""
        # If the Logger has handlers then it was already set up by the core code, else
        # it needs setting up here.
        try:
            from config import appname
            logger_name = f'{appname}.{PluginConfig.NAME}'
        except ImportError:
            # Fallback if EDMC config is not available
            logger_name = f'EDMC.{PluginConfig.NAME}'
        
        logger = logging.getLogger(logger_name)
        
        if not logger.hasHandlers():
            level = PluginConfig.LOG_LEVEL
            logger.setLevel(level)
            logger_channel = logging.StreamHandler()
            logger_formatter = logging.Formatter(PluginConfig.LOG_FORMAT)
            logger_formatter.default_time_format = PluginConfig.LOG_TIME_FORMAT
            logger_formatter.default_msec_format = PluginConfig.LOG_TIME_MSEC_FORMAT
            logger_channel.setFormatter(logger_formatter)
            logger.addHandler(logger_channel)
        
        return logger
    
    @staticmethod
    def get_check_updates() -> bool:
        """Get whether to check for updates on startup"""
        try:
            from config import config
            return config.get_bool('ravencolonial_check_updates', default=True)
        except (ImportError, AttributeError):
            return True
    
    @staticmethod
    def set_check_updates(value: bool):
        """Set whether to check for updates on startup"""
        try:
            from config import config
            config.set('ravencolonial_check_updates', value)
        except (ImportError, AttributeError):
            pass
    
    @staticmethod
    def get_autoupdate() -> bool:
        """Get whether to automatically install updates"""
        try:
            from config import config
            return config.get_bool('ravencolonial_autoupdate', default=False)
        except (ImportError, AttributeError):
            return False
    
    @staticmethod
    def set_autoupdate(value: bool):
        """Set whether to automatically install updates"""
        try:
            from config import config
            config.set('ravencolonial_autoupdate', value)
        except (ImportError, AttributeError):
            pass
    
    @staticmethod
    def get_check_prerelease() -> bool:
        """Get whether to check for pre-release versions"""
        try:
            from config import config
            return config.get_bool('ravencolonial_check_prerelease', default=False)
        except (ImportError, AttributeError):
            return False
    
    @staticmethod
    def set_check_prerelease(value: bool):
        """Set whether to check for pre-release versions"""
        try:
            from config import config
            config.set('ravencolonial_check_prerelease', value)
        except (ImportError, AttributeError):
            pass


def plugin_issue_log_path_hint(plugin_dir: str) -> str:
    """Path to this plugin's dedicated issue log (same folder layout as at runtime)."""
    return os.path.join(plugin_dir, "logs", "RavenColonial_EDMC.log")


def edmc_log_path_hint() -> str:
    """Typical EDMC main log path for user-facing hints (varies by OS)."""
    if sys.platform == "darwin":
        return os.path.join(
            os.path.expanduser("~"),
            "Library",
            "Application Support",
            "EDMarketConnector",
            "EDMarketConnector.log",
        )
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return os.path.join(local, "EDMarketConnector", "EDMarketConnector.log")
        temp = os.environ.get("TEMP") or os.environ.get("TMP")
        if temp:
            return os.path.join(temp, "EDMarketConnector", "EDMarketConnector.log")
        return os.path.join(os.path.expanduser("~"), "EDMarketConnector", "EDMarketConnector.log")
    xdg = (os.environ.get("XDG_DATA_HOME") or "").strip()
    if xdg:
        return os.path.join(xdg, "EDMarketConnector", "EDMarketConnector.log")
    return os.path.join(
        os.path.expanduser("~"),
        ".local",
        "share",
        "EDMarketConnector",
        "EDMarketConnector.log",
    )
