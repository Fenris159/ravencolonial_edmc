"""Shared logging helpers for the RavenColonial EDMC plugin."""

from __future__ import annotations

import logging


DEFAULT_LOG_FORMAT = "%(name)s: %(levelname)s - %(message)s"
DEFAULT_LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_LOG_TIME_MSEC_FORMAT = "%s.%03d"


def configure_standalone_logger(
    logger: logging.Logger,
    *,
    level: int = logging.INFO,
    propagate: bool = False,
    fmt: str = DEFAULT_LOG_FORMAT,
) -> logging.Logger:
    """
    Configure a simple fallback logger for plugin modules.

    EDMC usually configures plugin loggers itself. This fallback keeps local test
    runs readable and avoids relying on EDMC formatter fields that are not always
    available outside the main application process.
    """
    logger.propagate = propagate
    if not logger.hasHandlers():
        logger.setLevel(level)
        handler = logging.StreamHandler()
        formatter = logging.Formatter(fmt)
        formatter.default_time_format = DEFAULT_LOG_TIME_FORMAT
        formatter.default_msec_format = DEFAULT_LOG_TIME_MSEC_FORMAT
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger
