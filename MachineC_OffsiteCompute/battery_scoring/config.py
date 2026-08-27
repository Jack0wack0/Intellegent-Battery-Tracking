"""Loads the versioned scoring configuration (weights/thresholds) from disk.

Keeping this in JSON (rather than hard-coded constants) is a direct requirement
of the spec: thresholds/weights must be calibratable without code changes, and
every score must record which algorithm version produced it.
"""

import json
import os

_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config(version: int = 1) -> dict:
    path = os.path.join(_CONFIG_DIR, f"scoring_config_v{version}.json")
    with open(path, "r") as f:
        config = json.load(f)
    if config.get("version") != version:
        raise ValueError(f"scoring_config_v{version}.json declares version {config.get('version')}, expected {version}")
    return config


CURRENT_VERSION = 1
