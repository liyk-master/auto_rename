"""
Logging configuration setup.
"""

import logging
import logging.handlers
from pathlib import Path
from typing import Dict


def setup_logging(config: Dict):
    """
    Set up logging based on configuration.

    Args:
        config: Application configuration dictionary
    """
    log_level = config["logging"].get("level", "INFO").upper()
    log_file = config["logging"].get("file")

    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level))

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler if specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=10485760, backupCount=5
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
