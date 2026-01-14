"""
Configuration loading utilities.
"""

import configparser
import os
from pathlib import Path
from typing import Dict


def load_config(config_path: str = None) -> Dict:
    """
    Load configuration from file and environment variables.

    Args:
        config_path: Path to config file. If None, searches default locations.

    Returns:
        Dictionary with configuration values
    """
    # Determine config file path
    if config_path is None:
        config_path = _find_config_file()

    # Parse config file
    config = configparser.ConfigParser()
    if config_path and Path(config_path).exists():
        config.read(config_path)

    # Convert to dictionary and apply environment variables
    config_dict = _config_to_dict(config)
    _apply_environment_overrides(config_dict)

    return config_dict


def _find_config_file() -> str:
    """Find configuration file in common locations."""
    possible_paths = [
        "/etc/video-organizer/config.ini",
        str(Path.home() / ".config" / "video-organizer" / "config.ini"),
        "config.ini",
    ]

    for path in possible_paths:
        if Path(path).exists():
            return path

    return ""


def _config_to_dict(config: configparser.ConfigParser) -> Dict:
    """Convert ConfigParser object to nested dictionary."""
    config_dict = {}
    for section in config.sections():
        config_dict[section] = {}
        for key, value in config.items(section):
            config_dict[section][key] = value

    # Parse naming rules configuration
    if "naming" in config_dict:
        naming_rules = {
            "tv_show": config_dict["naming"].get(
                "tv_show_format",
                "{show_name}/Season {season:02d}/{show_name} - S{season:02d}E{episode:02d} - {episode_name}",
            ),
            "movie": config_dict["naming"].get("movie_format", "{movie_name} ({year})"),
            "anime": config_dict["naming"].get(
                "anime_format",
                "{anime_name}/{season_name}/{anime_name} - S{season:02d}E{episode:02d}",
            ),
            "simple": config_dict["naming"].get("simple_format", "{title}"),
        }
        config_dict["naming_rules"] = naming_rules

    return config_dict


def _apply_environment_overrides(config_dict: Dict):
    """Override config values with environment variables."""
    env_prefix = "VIDEO_ORGANIZER_"

    for section in config_dict:
        for key in config_dict[section]:
            env_var = f"{env_prefix}{section.upper()}_{key.upper()}"
            if env_var in os.environ:
                config_dict[section][key] = os.environ[env_var]
