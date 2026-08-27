"""Health Score: "how healthy is this battery relative to when it was new?"

Long-term condition score built from internal-resistance trend, load-voltage
trend, CBA capacity state-of-health, and age/cycle count as supporting context.
Each dimension is scored independently and combined only from what data is
actually available -- sparse data (e.g. no CBA test yet) lowers confidence
rather than being treated as a bad reading.
"""

from datetime import datetime, timezone
from statistics import mean
from typing import List, Optional

from .models import Battery, CBATest, PullMeasurement, ScoreComponent, ScoreResult
from .score_utils import normalize_linear, weighted_average


def _trend_change_pct(values: List[float], baseline_n: int, recent_n: int, min_points: int) -> Optional[float]:
    if len(values) < min_points:
        return None
    baseline = mean(values[:baseline_n]) if len(values) >= baseline_n else values[0]
    recent = mean(values[-recent_n:]) if len(values) >= recent_n else values[-1]
    if baseline == 0:
        return None
    return (recent - baseline) / baseline * 100.0


def compute_health_score(
    battery: Battery,
    measurements: List[PullMeasurement],
    cba_tests: List[CBATest],
    lifetime_cycle_count: int,
    config: dict,
    now: Optional[datetime] = None,
) -> ScoreResult:
    now = now or datetime.now(timezone.utc)
    cfg = config["health_score"]
    weights = cfg["weights"]
    baseline_n = cfg["baseline_sample_size"]
    recent_n = cfg["recent_sample_size"]
    min_points = cfg["min_points_for_trend"]

    components = []
    explanation = []

    # measurements are expected sorted ascending by timestamp by the caller.
    ir_values = [m.internal_resistance_milliohm for m in measurements if m.internal_resistance_milliohm is not None]
    v18_values = [m.voltage_18a for m in measurements if m.voltage_18a is not None]

    ir_change = _trend_change_pct(ir_values, baseline_n, recent_n, min_points)
    if ir_change is None:
        components.append(ScoreComponent("internalResistanceTrendPct", None, None, weights["internal_resistance_trend"], 0.0))
        explanation.append("Not enough internal-resistance history yet; Health Score confidence reduced.")
    else:
        rng = cfg["internal_resistance_change_range_pct"]
        norm = normalize_linear(ir_change, rng["good"], rng["bad"], invert=True)
        components.append(ScoreComponent("internalResistanceTrendPct", ir_change, norm, weights["internal_resistance_trend"], 0.0))
        if norm < 50:
            explanation.append(f"Internal resistance has risen {ir_change:.1f}% from baseline.")

    v18_change = _trend_change_pct(v18_values, baseline_n, recent_n, min_points)
    if v18_change is None:
        components.append(ScoreComponent("voltage18ATrendPct", None, None, weights["voltage_18a_trend"], 0.0))
        explanation.append("Not enough 18A load-voltage history yet; Health Score confidence reduced.")
    else:
        rng = cfg["voltage_18a_change_range_pct"]
        norm = normalize_linear(v18_change, rng["bad"], rng["good"])
        components.append(ScoreComponent("voltage18ATrendPct", v18_change, norm, weights["voltage_18a_trend"], 0.0))
        if norm < 50:
            explanation.append(f"18A load voltage has dropped {abs(v18_change):.1f}% from baseline.")

    if not cba_tests:
        components.append(ScoreComponent("capacitySOHPct", None, None, weights["capacity_soh"], 0.0))
        explanation.append("No CBA capacity test on record yet; Health Score confidence reduced.")
    else:
        cba_sorted = sorted(cba_tests, key=lambda t: t.timestamp or datetime.min.replace(tzinfo=timezone.utc))
        baseline_capacity = cba_sorted[0].capacity_ah
        latest_capacity = cba_sorted[-1].capacity_ah
        soh_pct = (latest_capacity / baseline_capacity * 100.0) if baseline_capacity else None
        if soh_pct is None:
            components.append(ScoreComponent("capacitySOHPct", None, None, weights["capacity_soh"], 0.0))
        else:
            rng = cfg["capacity_soh_range_pct"]
            norm = normalize_linear(soh_pct, rng["bad"], rng["good"])
            components.append(ScoreComponent("capacitySOHPct", soh_pct, norm, weights["capacity_soh"], 0.0))
            if norm < 50:
                explanation.append(f"Measured capacity has fallen to {soh_pct:.0f}% of baseline.")
            last_test_at = cba_sorted[-1].timestamp
            if last_test_at:
                explanation.append(f"Last CBA test: {last_test_at.date().isoformat()}.")

    age_days = (now - battery.purchase_date).days if battery.purchase_date else None
    age_rng = cfg["age_days_range"]
    cycles_rng = cfg["cycles_range"]
    if age_days is None:
        age_norm = None
    else:
        age_norm = normalize_linear(age_days, age_rng["full_score"], age_rng["zero_score"], invert=True)
    cycles_norm = normalize_linear(lifetime_cycle_count, cycles_rng["full_score"], cycles_rng["zero_score"], invert=True)
    sub_norms = [n for n in (age_norm, cycles_norm) if n is not None]
    age_cycles_norm = mean(sub_norms) if sub_norms else None
    components.append(ScoreComponent(
        "ageAndCyclesContext", lifetime_cycle_count, age_cycles_norm, weights["age_and_cycles"], 0.0
    ))

    entries = [(c.normalized_value, c.weight) for c in components if c.normalized_value is not None]
    score, used_weight = weighted_average(entries)
    if score is None:
        score = 0.0

    for c in components:
        if c.normalized_value is not None:
            c.contribution = (c.normalized_value * c.weight / used_weight) if used_weight else 0.0

    total_possible_weight = sum(weights.values())
    confidence = used_weight / total_possible_weight if total_possible_weight else 0.0

    if not explanation:
        explanation.append("Health Score based on resistance/voltage trends and CBA capacity history.")

    return ScoreResult(score=round(score, 1), confidence=round(confidence, 3), components=components, explanation=explanation)
