import time
import logging
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, db
from os import getenv
import dotenv

dotenv.load_dotenv()

FIREBASE_DB_BASE_URL = getenv('FIREBASE_DB_BASE_URL')
FIREBASE_CREDS_FILE = getenv('FIREBASE_CREDS_FILE')

LOG_FILE = "Correction.log"         # log file path
CHECK_INTERVAL = 3600                 # seconds between checks
UNCHANGED_LIMIT = 24                 # consecutive unchanged checks before reset


logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

logger.info("==================================================================")

try:
    firebase_admin.get_app()
except ValueError:
    cred = credentials.Certificate(FIREBASE_CREDS_FILE)
    firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_BASE_URL})

status_ref = db.reference("status")
last_updated_ref = db.reference("status/LastUpdated")
battery_next_up_ref = db.reference("BatteryNextUp")
battery_list_ref = db.reference("BatteryList")


def update_status_field(field, value):
    #Safely update a specific field under /status.
    try:
        status_ref.update({field: value})
        logger.info(f"Updated status/{field} to {value}")
    except Exception as e:
        logger.error(f"Error updating status/{field}: {e}")

def perform_reset():
    #Clears BatteryNextUp and sets all 10-digit batteries to IsCharging = false.
    try:
        # Delete BatteryNextUp
        battery_next_up_ref.delete()
        logger.info("Cleared BatteryNextUp entries.")

        # Update all 10-digit BatteryList entries
        battery_list = battery_list_ref.get() or {}
        for battery_id, data in battery_list.items():
            if battery_id.isdigit() and len(battery_id) == 10:
                battery_list_ref.child(battery_id).update({"IsCharging": False})
            else:
                logger.info(f"Skipping non-10-digit entry: {battery_id}")

        logger.info("All 10-digit batteries set to IsCharging = false.")

        # Mark the wipe in status
        update_status_field("wiped", True)
        update_status_field("COM_PORT1", "Disconnected")
        update_status_field("COM_PORT2", "Disconnected")
        update_status_field("CPU_Temp", "0, offline")
        global last_wiped_value
        last_wiped_value = last_updated_ref.get()


    except Exception as e:
        logger.error(f"Reset failed: {e}")


def monitor_status():
    unchanged_count = 0
    last_seen = None

    logger.info("Firebase monitor started.")
    logger.info(f"Checking every {CHECK_INTERVAL}s, reset after {UNCHANGED_LIMIT} identical timestamps.")

    while True:
        try:
            # Record that we're alive
            update_status_field("LastCheckedForWipe", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            # Read the current LastUpdated
            current = last_updated_ref.get()
            if current is None:
                logger.warning("LastUpdated is missing or None.")
                time.sleep(CHECK_INTERVAL)
                continue

            # If LastUpdated changed, reset wipe flag
            # If LastUpdated changed
            if current != last_seen:
                unchanged_count = 0
                # Only clear "wiped" if this update is newer than the one that triggered the wipe
                global last_wiped_value
                if 'last_wiped_value' in globals() and current == last_wiped_value:
                    # Still same timestamp that caused the wipe → don't reset yet
                    logger.info(f"Detected same LastUpdated as wipe ({current}), keeping wiped=True.")
                else:
                    last_seen = current
                    logger.info(f"Detected new update: {current}")
                    update_status_field("wiped", False)
            else:
                unchanged_count += 1
                logger.info(f"Unchanged for {unchanged_count}/{UNCHANGED_LIMIT} checks.")

            # Perform wipe if stale
            if unchanged_count >= UNCHANGED_LIMIT:
                logger.warning("Detected stale state. Performing database reset...")
                perform_reset()
                unchanged_count = 0
                last_seen = None

        except Exception as e:
            logger.error(f"Error in monitor loop: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    monitor_status()
