"""Match Score: "how suitable is this battery for the next match, right now?"

Current voltage is required for every input measurement; all other fields
(SOC, internal resistance, 1A/18A load voltage) are optional and only
contribute when present and reasonably fresh. Missing optional data lowers
confidence instead of being treated as a bad reading.
"""

from datetime import datetime, timezone
from typing import Optional

from .models import PullMeasurement, ScoreComponent, ScoreResult
from .score_utils import freshness_weight, normalize_linear, weighted_average


def compute_match_score(measurement: PullMeasurement, config: dict, now: Optional[datetime] = None) -> ScoreResult:
    now = now or datetime.now(timezone.utc)
    cfg = config["match_score"]
    weights = cfg["weights"]
    full_h = cfg["freshness_hours"]["full_weight_within"]
    zero_h = cfg["freshness_hours"]["zero_weight_after"]

    components = []
    explanation = []

    # Voltage is required and always present on a valid PullMeasurement, so it is
    # always fresh relative to its own timestamp.
    fresh = freshness_weight(measurement.timestamp, now, full_h, zero_h) if measurement.timestamp else 1.0
    v_norm = normalize_linear(measurement.current_voltage, cfg["voltage_range"]["min"], cfg["voltage_range"]["max"])
    components.append(ScoreComponent("currentVoltage", measurement.current_voltage, v_norm, weights["voltage"], 0.0, fresh))

    optional_specs = [
        ("socPercent", measurement.soc_percent, cfg["soc_range"], False, "soc"),
        ("internalResistanceMilliOhm", measurement.internal_resistance_milliohm,
         {"min": cfg["internal_resistance_range_milliohm"]["good"], "max": cfg["internal_resistance_range_milliohm"]["bad"]},
         True, "internal_resistance"),
        ("voltage18A", measurement.voltage_18a, cfg["voltage_18a_range"], False, "voltage_18a"),
    ]

    for field_name, raw_value, rng, invert, weight_key in optional_specs:
        if raw_value is None:
            components.append(ScoreComponent(field_name, None, None, weights[weight_key], 0.0, 0.0))
            explanation.append(f"{field_name} not provided; Match Score confidence reduced.")
            continue
        norm = normalize_linear(raw_value, rng["min"], rng["max"], invert=invert)
        components.append(ScoreComponent(field_name, raw_value, norm, weights[weight_key], 0.0, fresh))

    # Weighted average over whatever is present; weight for missing/stale inputs is
    # effectively zero, which raises the relative contribution of what IS present
    # while confidence (below) reflects how much of the total possible weight was used.
    entries = []
    for c in components:
        if c.normalized_value is None:
            continue
        effective_weight = c.weight * (c.freshness if c.freshness is not None else 1.0)
        entries.append((c.normalized_value, effective_weight))

    score, used_weight = weighted_average(entries)
    if score is None:
        score = 0.0

    for c in components:
        if c.normalized_value is not None:
            effective_weight = c.weight * (c.freshness if c.freshness is not None else 1.0)
            c.contribution = (c.normalized_value * effective_weight / used_weight) if used_weight else 0.0

    total_possible_weight = sum(weights.values())
    confidence = used_weight / total_possible_weight if total_possible_weight else 0.0

    if measurement.internal_resistance_milliohm is not None:
        good = cfg["internal_resistance_range_milliohm"]["good"]
        bad = cfg["internal_resistance_range_milliohm"]["bad"]
        if measurement.internal_resistance_milliohm >= (good + bad) / 2:
            explanation.append("High internal resistance reduced Match Score.")
    if measurement.voltage_18a is not None:
        rng = cfg["voltage_18a_range"]
        if measurement.voltage_18a <= (rng["min"] + rng["max"]) / 2:
            explanation.append("Low voltage under 18A load reduced Match Score.")
    if not explanation:
        explanation.append("Match Score based on available current-voltage and Battery Beak readings.")

    return ScoreResult(score=round(score, 1), confidence=round(confidence, 3), components=components, explanation=explanation)
