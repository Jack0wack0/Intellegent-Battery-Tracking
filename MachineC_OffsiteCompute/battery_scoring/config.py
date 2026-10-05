"""Loads the versioned scoring configuration (weights/thresholds) from disk.

Keeping this in JSON (rather than hard-coded constants) is a direct requirement
of the spec: thresholds/weights must be calibratable without code changes, and
every score must record which algorithm version produced it.
"""

import json
import os
import math

_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config(version: int = 1) -> dict:
    path = os.path.join(_CONFIG_DIR, f"scoring_config_v{version}.json")
    with open(path, "r") as f:
        config = json.load(f)
    if config.get("version") != version:
        raise ValueError(f"scoring_config_v{version}.json declares version {config.get('version')}, expected {version}")
    validate_config(config)
    return config


def validate_config(config):
    for section in ("match_score", "health_score"):
        weights = config[section]["weights"]
        if not weights or any(type(w) not in (int, float) or not math.isfinite(w) or w < 0 for w in weights.values()) or sum(weights.values()) <= 0:
            raise ValueError("Weights must be finite, nonnegative and have a positive total")
        for key, value in config[section].items():
            if isinstance(value, dict) and {"min", "max"} <= value.keys():
                if not all(type(value[k]) in (int, float) and math.isfinite(value[k]) for k in ("min", "max")) or value["min"] >= value["max"]:
                    raise ValueError(f"Invalid range: {key}")
            if isinstance(value, dict):
                for lower, upper in (("good", "bad"), ("bad", "good"), ("full_score", "zero_score")):
                    if lower in value and upper in value:
                        a, b = value[lower], value[upper]
                        if not all(type(v) in (int, float) and math.isfinite(v) for v in (a, b)) or a == b:
                            raise ValueError(f"Invalid range: {key}")
    freshness = config["match_score"]["freshness_hours"]
    if not 0 <= freshness["full_weight_within"] < freshness["zero_weight_after"]:
        raise ValueError("Freshness thresholds must increase")
    for key in ("baseline_sample_size", "recent_sample_size", "min_points_for_trend"):
        if type(config["health_score"][key]) is not int or config["health_score"][key] < 1:
            raise ValueError("Trend sizes must be positive integers")
    ranges = [(config['match_score']['internal_resistance_range_milliohm'], 'good', 'bad'),
              (config['health_score']['internal_resistance_change_range_pct'], 'good', 'bad'),
              (config['health_score']['voltage_18a_change_range_pct'], 'bad', 'good'),
              (config['health_score']['capacity_soh_range_pct'], 'bad', 'good'),
              (config['health_score']['age_days_range'], 'full_score', 'zero_score'),
              (config['health_score']['cycles_range'], 'full_score', 'zero_score')]
    if any(values[low] >= values[high] for values, low, high in ranges):
        raise ValueError('Good/bad normalization ranges have the wrong direction')
    health = config['health_score']
    if not 0 <= health.get('cba_full_weight_days', 180) < health.get('cba_zero_weight_days', 540):
        raise ValueError('CBA freshness thresholds must increase')


CURRENT_VERSION = 2
