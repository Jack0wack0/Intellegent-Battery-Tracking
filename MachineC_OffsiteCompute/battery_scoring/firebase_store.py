"""Firebase RTDB read/write helpers for the scoring engine.

Paths match Shared/battery_schema.md. Kept separate from the calculators so the
scoring math has no Firebase dependency and can be unit-tested in isolation.
"""

from datetime import datetime, timezone
from typing import List, Optional

from .models import Battery, CBATest, PullMeasurement

BATTERIES_PATH = "Batteries"
CYCLES_PATH = "Cycles"
MEASUREMENTS_PATH = "PullMeasurements"
CBA_PATH = "CBATests"
SCORES_PATH = "ScoreSnapshots"


def get_battery(root_ref, battery_id: str) -> Battery:
    data = root_ref.child(BATTERIES_PATH).child(battery_id).get()
    return Battery.from_dict(battery_id, data)


def list_battery_ids(root_ref) -> List[str]:
    data = root_ref.child(BATTERIES_PATH).get() or {}
    return list(data.keys())


def list_measurements(root_ref, battery_id: str) -> List[PullMeasurement]:
    data = root_ref.child(MEASUREMENTS_PATH).child(battery_id).get() or {}
    measurements = []
    for measurement_id, raw in data.items():
        parsed = PullMeasurement.from_dict(measurement_id, battery_id, raw)
        if parsed is not None:
            measurements.append(parsed)
    measurements.sort(key=lambda m: m.timestamp or datetime.min.replace(tzinfo=timezone.utc))
    return measurements


def list_cba_tests(root_ref, battery_id: str) -> List[CBATest]:
    data = root_ref.child(CBA_PATH).child(battery_id).get() or {}
    tests = []
    for test_id, raw in data.items():
        parsed = CBATest.from_dict(test_id, battery_id, raw)
        if parsed is not None:
            tests.append(parsed)
    tests.sort(key=lambda t: t.timestamp or datetime.min.replace(tzinfo=timezone.utc))
    return tests


def get_lifetime_cycle_count(root_ref, battery_id: str) -> int:
    query = root_ref.child(CYCLES_PATH).order_by_child("batteryId").equal_to(battery_id)
    data = query.get() or {}
    return len(data)


def write_score_snapshot(root_ref, battery_id: str, snapshot: dict) -> Optional[str]:
    new_ref = root_ref.child(SCORES_PATH).child(battery_id).push(snapshot)
    return new_ref.key


def update_battery_cache(root_ref, battery_id: str, cache_fields: dict) -> None:
    root_ref.child(BATTERIES_PATH).child(battery_id).child("cache").update(cache_fields)
