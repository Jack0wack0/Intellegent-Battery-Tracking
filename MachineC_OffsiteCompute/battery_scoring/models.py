"""Typed views over the raw Firebase RTDB dicts used by the scoring engine.

These are thin parsing helpers, not an ORM -- Firebase remains the source of
truth and raw dicts are read/written directly by firebase_store.py. Dataclasses
here just give the scoring calculators a stable, documented shape to work with.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class PullMeasurement:
    measurement_id: str
    battery_id: str
    timestamp: Optional[datetime]
    current_voltage: float
    soc_percent: Optional[float] = None
    internal_resistance_milliohm: Optional[float] = None
    voltage_1a: Optional[float] = None
    voltage_18a: Optional[float] = None
    cycle_id: Optional[str] = None

    @classmethod
    def from_dict(cls, measurement_id: str, battery_id: str, data: dict) -> Optional["PullMeasurement"]:
        if data is None or data.get("currentVoltage") is None:
            # currentVoltage is required; a record without it is not a valid pull measurement.
            return None
        return cls(
            measurement_id=measurement_id,
            battery_id=battery_id,
            timestamp=_parse_timestamp(data.get("timestamp")),
            current_voltage=float(data["currentVoltage"]),
            soc_percent=data.get("socPercent"),
            internal_resistance_milliohm=data.get("internalResistanceMilliOhm"),
            voltage_1a=data.get("voltage1A"),
            voltage_18a=data.get("voltage18A"),
            cycle_id=data.get("cycleId"),
        )


@dataclass
class CBATest:
    test_id: str
    battery_id: str
    timestamp: Optional[datetime]
    season: Optional[str]
    capacity_ah: float
    notes: Optional[str] = None

    @classmethod
    def from_dict(cls, test_id: str, battery_id: str, data: dict) -> Optional["CBATest"]:
        if data is None or data.get("capacityAh") is None:
            return None
        return cls(
            test_id=test_id,
            battery_id=battery_id,
            timestamp=_parse_timestamp(data.get("timestamp")),
            season=data.get("season"),
            capacity_ah=float(data["capacityAh"]),
            notes=data.get("notes"),
        )


@dataclass
class Battery:
    battery_id: str
    name: Optional[str] = None
    brand: Optional[str] = None
    purchase_date: Optional[datetime] = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, battery_id: str, data: dict) -> "Battery":
        data = data or {}
        return cls(
            battery_id=battery_id,
            name=data.get("name"),
            brand=data.get("brand"),
            purchase_date=_parse_timestamp(data.get("purchaseDate")),
            raw=data,
        )


@dataclass
class ScoreComponent:
    metric: str
    raw_value: Optional[float]
    normalized_value: Optional[float]
    weight: float
    contribution: float
    freshness: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "rawValue": self.raw_value,
            "normalizedValue": self.normalized_value,
            "weight": self.weight,
            "contribution": self.contribution,
            "freshness": self.freshness,
        }


@dataclass
class ScoreResult:
    score: float
    confidence: float
    components: list
    explanation: list

    def to_dict(self, component_key: str, explanation_key: str) -> dict:
        return {
            component_key: [c.to_dict() for c in self.components],
            explanation_key: list(self.explanation),
        }
