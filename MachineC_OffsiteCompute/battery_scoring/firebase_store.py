"""RTDB input parsing, completed-cycle counts and atomic score publication."""
from datetime import datetime, timedelta, timezone
import logging
from .models import Battery, CBATest, PullMeasurement

BATTERIES_PATH, CYCLES_PATH = "Batteries", "Cycles"
MEASUREMENTS_PATH, CBA_PATH, SCORES_PATH = "PullMeasurements", "CBATests", "ScoreSnapshots"
log = logging.getLogger(__name__)


def get_battery(root_ref, battery_id):
    return Battery.from_dict(battery_id, root_ref.child(BATTERIES_PATH).child(battery_id).get())


def list_battery_ids(root_ref):
    data = root_ref.child(BATTERIES_PATH).get() or {}
    if not isinstance(data, dict):
        raise ValueError("Batteries must be an object")
    return sorted(data)


def parse_records(data, battery_id, model, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(data, dict):
        log.error("Invalid history shape for %s", battery_id)
        return [], ["History is not an object"]
    records, warnings = [], []
    for identity, raw in data.items():
        if isinstance(raw, dict) and raw.get("supersededBy"):
            continue  # Audit-friendly correction keeps raw originals but excludes them from calculations.
        try:
            parsed = model.from_dict(identity, battery_id, raw)
            if parsed is None or parsed.timestamp is None or parsed.timestamp > now + timedelta(minutes=5):
                raise ValueError("Missing required input or invalid/future timestamp")
            records.append(parsed)
        except (ValueError, TypeError, OverflowError) as error:
            warnings.append(f"{identity}: {error}")
    records.sort(key=lambda record: (record.timestamp, getattr(record, 'measurement_id', getattr(record, 'test_id', ''))))
    return records, warnings


def list_measurements(root_ref, battery_id):
    data = root_ref.child(MEASUREMENTS_PATH).child(battery_id).get() or {}
    return parse_records(data, battery_id, PullMeasurement)[0]


def list_cba_tests(root_ref, battery_id):
    data = root_ref.child(CBA_PATH).child(battery_id).get() or {}
    return parse_records(data, battery_id, CBATest)[0]


def completed_cycles(data):
    if not isinstance(data, dict):
        return {}
    result = {}
    for identity, raw in data.items():
        if not isinstance(raw, dict) or raw.get("completed") is False or not raw.get("endTime") or raw.get("voided"):
            continue
        try:
            from .models import _parse_timestamp
            end = _parse_timestamp(raw['endTime'])
            start = _parse_timestamp(raw.get('startTime'))
            if end and (start is None or end >= start):
                result[identity] = raw
        except (ValueError, TypeError):
            continue
    return result


def get_cycles(root_ref, battery_id):
    raw = root_ref.child(CYCLES_PATH).order_by_child("batteryId").equal_to(battery_id).get() or {}
    return completed_cycles(raw)


def get_lifetime_cycle_count(root_ref, battery_id):
    return len(get_cycles(root_ref, battery_id))


def publish(root_ref, battery_id, snapshot, cache):
    identity = root_ref.child(SCORES_PATH).child(battery_id).push().key
    patch = {f"{SCORES_PATH}/{battery_id}/{identity}": snapshot}
    patch.update({f"{BATTERIES_PATH}/{battery_id}/cache/{key}": value for key, value in cache.items()})
    root_ref.update(patch)
    return identity
