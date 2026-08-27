"""Scoring engine service.

Listens to Firebase RTDB for new PullMeasurements/CBATests writes and
recomputes Match Score + Health Score for the affected battery, writing a new
ScoreSnapshot and refreshing the cached fields on Batteries/{id}. Runs
continuously on MachineC (offsite) so the Raspberry Pi cart never has to run
scoring logic.
"""

import logging
import sys
import time
from datetime import datetime, timezone
from os import getenv

import dotenv
import firebase_admin
from firebase_admin import credentials, db

from . import firebase_store as store
from .config import CURRENT_VERSION, load_config
from .health_score import compute_health_score
from .match_score import compute_match_score

dotenv.load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("SCORING_ENGINE")

FIREBASE_DB_BASE_URL = getenv("FIREBASE_DB_BASE_URL")
FIREBASE_CREDS_FILE = getenv("FIREBASE_CREDS_FILE")


def init_firebase():
    if not FIREBASE_DB_BASE_URL or not FIREBASE_CREDS_FILE:
        log.critical("Missing FIREBASE_DB_BASE_URL / FIREBASE_CREDS_FILE in environment.")
        sys.exit(1)
    try:
        firebase_admin.get_app()
    except ValueError:
        cred = credentials.Certificate(FIREBASE_CREDS_FILE)
        firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_BASE_URL})
    return db.reference("/")


def recompute_battery(root_ref, battery_id: str, config: dict) -> None:
    measurements = store.list_measurements(root_ref, battery_id)
    if not measurements:
        log.debug(f"No valid pull measurements yet for {battery_id}; skipping.")
        return

    battery = store.get_battery(root_ref, battery_id)
    cba_tests = store.list_cba_tests(root_ref, battery_id)
    lifetime_cycles = store.get_lifetime_cycle_count(root_ref, battery_id)

    now = datetime.now(timezone.utc)
    latest = measurements[-1]

    match_result = compute_match_score(latest, config, now=now)
    health_result = compute_health_score(battery, measurements, cba_tests, lifetime_cycles, config, now=now)

    snapshot = {
        "timestamp": now.isoformat(),
        "algorithmVersion": config["version"],
        "matchScore": match_result.score,
        "matchConfidence": match_result.confidence,
        "healthScore": health_result.score,
        "healthConfidence": health_result.confidence,
        "inputRefs": {
            "measurementId": latest.measurement_id,
            "cbaTestId": cba_tests[-1].test_id if cba_tests else None,
        },
    }
    snapshot.update(match_result.to_dict("matchComponents", "matchExplanation"))
    snapshot.update(health_result.to_dict("healthComponents", "healthExplanation"))

    store.write_score_snapshot(root_ref, battery_id, snapshot)
    store.update_battery_cache(root_ref, battery_id, {
        "latestVoltage": latest.current_voltage,
        "latestVoltageAt": latest.timestamp.isoformat() if latest.timestamp else None,
        "latestSOC": latest.soc_percent,
        "latestInternalResistanceMilliOhm": latest.internal_resistance_milliohm,
        "latest1AVoltage": latest.voltage_1a,
        "latest18AVoltage": latest.voltage_18a,
        "latestCBACapacityAh": cba_tests[-1].capacity_ah if cba_tests else None,
        "latestCBATestAt": cba_tests[-1].timestamp.isoformat() if cba_tests and cba_tests[-1].timestamp else None,
        "latestMatchScore": match_result.score,
        "latestMatchConfidence": match_result.confidence,
        "latestHealthScore": health_result.score,
        "latestHealthConfidence": health_result.confidence,
        "totalCycleCount": lifetime_cycles,
        "scoreAlgorithmVersion": config["version"],
    })
    log.info(
        f"{battery_id}: Match={match_result.score} (conf {match_result.confidence}) "
        f"Health={health_result.score} (conf {health_result.confidence})"
    )


def recompute_all(root_ref, config: dict) -> None:
    for battery_id in store.list_battery_ids(root_ref):
        try:
            recompute_battery(root_ref, battery_id, config)
        except Exception as e:
            log.error(f"Failed to recompute scores for {battery_id}: {e}")


def _battery_id_from_event_path(path: str):
    # RTDB stream events fire with path like "/{batteryId}" or "/{batteryId}/{childId}".
    parts = [p for p in path.split("/") if p]
    return parts[0] if parts else None


def main():
    root_ref = init_firebase()
    config = load_config(CURRENT_VERSION)
    log.info(f"Scoring engine started (algorithm v{config['version']}).")

    log.info("Running initial full recompute for all enrolled batteries...")
    recompute_all(root_ref, config)

    def on_measurement_event(event):
        battery_id = _battery_id_from_event_path(event.path)
        if battery_id:
            recompute_battery(root_ref, battery_id, config)

    def on_cba_event(event):
        battery_id = _battery_id_from_event_path(event.path)
        if battery_id:
            recompute_battery(root_ref, battery_id, config)

    root_ref.child(store.MEASUREMENTS_PATH).listen(on_measurement_event)
    root_ref.child(store.CBA_PATH).listen(on_cba_event)
    log.info("Listening for PullMeasurements/CBATests changes. Ctrl+C to stop.")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("Shutting down scoring engine.")


if __name__ == "__main__":
    main()
