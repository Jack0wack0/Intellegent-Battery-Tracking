"""Single-writer, periodically reconciled scoring; no fragile background stream callbacks."""
import hashlib
import json
import logging
import os
import signal
import threading
import time
import uuid
from datetime import datetime, timezone

from . import firebase_store as store
from .config import CURRENT_VERSION, load_config
from .health_score import compute_health_score
from .match_score import compute_match_score
from .models import PullMeasurement, CBATest

log = logging.getLogger("scoring")


def recompute_battery(root_ref, battery_id, config, now=None, before_publish=lambda: True, inputs=None, battery_data=None):
    now = now or datetime.now(timezone.utc)
    from .models import Battery
    battery = Battery.from_dict(battery_id, battery_data) if battery_data is not None else store.get_battery(root_ref, battery_id)
    if inputs is None:
        inputs = {}
    if not inputs:
        inputs.update(raw_measurements=root_ref.child(store.MEASUREMENTS_PATH).child(battery_id).get() or {},
                      raw_tests=root_ref.child(store.CBA_PATH).child(battery_id).get() or {},
                      cycles=store.get_cycles(root_ref, battery_id))
    raw_measurements, raw_tests = inputs['raw_measurements'], inputs['raw_tests']
    measurements, warnings = store.parse_records(raw_measurements, battery_id, PullMeasurement, now)
    cba_tests, cba_warnings = store.parse_records(raw_tests, battery_id, CBATest, now)
    cycles = inputs['cycles']
    warnings += [f"Cycle {identity}: timestamp estimated or affected by clock change" for identity, cycle in cycles.items()
                 if cycle.get('clockAnomaly') or cycle.get('endTimeEstimated')]
    latest = measurements[-1] if measurements else None
    match = compute_match_score(latest, config, now=now, history=measurements) if latest else None
    health = compute_health_score(battery, measurements, cba_tests, len(cycles), config, now=now)
    source = {'measurements': raw_measurements, 'cbaTests': raw_tests, 'cycles': cycles,
              'metadata': {k: v for k, v in battery.raw.items() if k != 'cache'}, 'config': config}
    # Fingerprint raw invalid values without publishing them; quarantined NaN cannot block valid history.
    fingerprint = hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode()).hexdigest()
    snapshot = {"timestamp": now.isoformat(), "algorithmVersion": config["version"],
                "matchScore": match.score if match and match.confidence > 0 else None,
                "matchConfidence": match.confidence if match else 0,
                "healthScore": health.score, "healthConfidence": health.confidence,
                "sourceFingerprint": fingerprint, "config": config,
                "inputRefs": {"measurementIds": [m.measurement_id for m in measurements],
                              "cbaTestIds": [t.test_id for t in cba_tests], "cycleIds": sorted(cycles),
                              "measurementId": latest.measurement_id if latest else None,
                              "baselineCBATestId": battery.raw.get('baselineCBATestId') or (cba_tests[0].test_id if cba_tests else None)}}
    if match:
        snapshot.update(match.to_dict("matchComponents", "matchExplanation"))
    else:
        snapshot.update(matchComponents=[], matchExplanation=["No valid dated pull voltage; readiness unknown."])
    snapshot.update(health.to_dict("healthComponents", "healthExplanation"))
    seasons = {}
    for cycle in cycles.values():
        season = str(cycle.get('season') or cycle['endTime'][:4])
        seasons[season] = seasons.get(season, 0) + 1
    cache = {"latestVoltage": latest.current_voltage if latest else None,
             "latestVoltageAt": latest.timestamp.isoformat() if latest else None,
             "latestMatchScore": snapshot['matchScore'], "latestMatchConfidence": snapshot['matchConfidence'],
             "latestHealthScore": health.score, "latestHealthConfidence": health.confidence,
             "latestCBACapacityAh": cba_tests[-1].capacity_ah if cba_tests else None,
             "latestCBATestAt": cba_tests[-1].timestamp.isoformat() if cba_tests else None,
             "totalCycleCount": len(cycles), "seasonCycleCount": seasons,
             "scoreAlgorithmVersion": config['version'], "sourceFingerprint": fingerprint,
             "scoreComputedAt": now.isoformat(), "inputWarnings": (warnings + cba_warnings)[:50]}
    for field, attr in [('latestSOC', 'soc_percent'), ('latestInternalResistanceMilliOhm', 'internal_resistance_milliohm'),
                        ('latest1AVoltage', 'voltage_1a'), ('latest18AVoltage', 'voltage_18a')]:
        reading = next((m for m in reversed(measurements) if getattr(m, attr) is not None), None)
        cache[field] = getattr(reading, attr) if reading else None
        cache[field + 'At'] = reading.timestamp.isoformat() if reading else None
    sag = next((m for m in reversed(measurements) if m.voltage_1a is not None and m.voltage_18a is not None), None)
    cache['latestLoadSag'] = sag.voltage_1a - sag.voltage_18a if sag else None
    cache['latestLoadSagAt'] = sag.timestamp.isoformat() if sag else None
    old = battery.raw.get('cache') or {}
    changed = any(old.get(k) != v for k, v in cache.items() if k != 'scoreComputedAt')
    if changed:
        if not before_publish():
            raise RuntimeError('Scoring writer lease lost; refusing stale publication')
        store.publish(root_ref, battery_id, snapshot, cache)
    return snapshot, cache


def recompute_all(root_ref, config, before_publish=lambda: True, input_cache=None):
    failures = []
    batteries = root_ref.child(store.BATTERIES_PATH).get() or {}
    revisions = root_ref.child('ScoringRevisions').get() or {}
    if not isinstance(batteries, dict) or not isinstance(revisions, dict):
        raise ValueError('Invalid battery/revision collection')
    for identity, battery_data in batteries.items():
        try:
            entry = input_cache.get(identity) if input_cache is not None else None
            metadata = {k: v for k, v in battery_data.items() if k != 'cache'}
            refresh = entry is None or entry['revision'] != revisions.get(identity) or entry['metadata'] != metadata or time.monotonic() - entry['readAt'] >= 600
            if refresh:
                entry = {'inputs': {}, 'revision': revisions.get(identity), 'metadata': metadata, 'readAt': time.monotonic()}
            recompute_battery(root_ref, identity, config, before_publish=before_publish,
                              inputs=entry['inputs'], battery_data=battery_data)
            if input_cache is not None:
                input_cache[identity] = entry
        except Exception:
            failures.append(identity)
            log.exception('Battery %s failed; retrying next reconciliation', identity)
    return failures


class WriterLease:
    def __init__(self, root):
        self.reference = root.child('ScoreEngineLease')
        self.owner = uuid.uuid4().hex

    def renew(self):
        now = time.time()
        def update(current):
            if current and current.get('owner') != self.owner and current.get('expires', 0) > now:
                return current
            return {'owner': self.owner, 'expires': now + 60}
        result = self.reference.transaction(update)
        return isinstance(result, dict) and result.get('owner') == self.owner


def main():
    import dotenv
    import firebase_admin
    from firebase_admin import credentials, db
    dotenv.load_dotenv()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    firebase_admin.initialize_app(credentials.Certificate(os.environ['FIREBASE_CREDS_FILE']),
                                  {'databaseURL': os.environ['FIREBASE_DB_BASE_URL'], 'httpTimeout': 10})
    root = db.reference('/')
    config, stop = load_config(CURRENT_VERSION), threading.Event()
    lease, input_cache = WriterLease(root), {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        try:
            if lease.renew():
                failures = recompute_all(root, config, before_publish=lease.renew, input_cache=input_cache)
                root.child('status/Scoring').update({'LastUpdated': datetime.now(timezone.utc).isoformat(),
                                                    'AlgorithmVersion': config['version'], 'FailedBatteryIds': failures})
        except Exception:
            log.exception('Scoring reconciliation failed; will retry')
        stop.wait(15)


if __name__ == '__main__':
    main()
