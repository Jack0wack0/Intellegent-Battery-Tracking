"""Small numeric helpers shared by the match/health score calculators."""

from datetime import datetime, timezone
from typing import Optional


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize_linear(value: float, low: float, high: float, invert: bool = False) -> float:
    """Map value in [low, high] to a 0-100 scale, clamped at the edges.

    If invert is True, lower raw values score higher (e.g. internal resistance).
    """
    if high == low:
        return 50.0
    pct = (value - low) / (high - low)
    pct = clamp(pct, 0.0, 1.0)
    if invert:
        pct = 1.0 - pct
    return pct * 100.0


def freshness_weight(timestamp: Optional[datetime], now: Optional[datetime], full_weight_hours: float, zero_weight_hours: float) -> float:
    """Linear decay from 1.0 (fresh) to 0.0 (stale) between the two age thresholds."""
    if timestamp is None:
        return 0.0
    now = now or datetime.now(timezone.utc)
    age_hours = (now - timestamp).total_seconds() / 3600.0
    if age_hours <= full_weight_hours:
        return 1.0
    if age_hours >= zero_weight_hours:
        return 0.0
    span = zero_weight_hours - full_weight_hours
    return clamp(1.0 - (age_hours - full_weight_hours) / span, 0.0, 1.0)


def weighted_average(entries):
    """entries: iterable of (value, weight). Returns (weighted_avg, total_weight_used)."""
    total_weight = sum(weight for _, weight in entries if weight > 0)
    if total_weight <= 0:
        return None, 0.0
    total = sum(value * weight for value, weight in entries if weight > 0)
    return total / total_weight, total_weight
