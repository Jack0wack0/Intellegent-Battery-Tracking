"""Connectivity monitor. Never invent removals or erase physical charging history."""
from datetime import datetime, timezone
import logging
import os
import signal
import threading
import time


def heartbeat_online(value, now=None, timeout=30):
    try:
        at = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if at.tzinfo is None:
            return False
        age = ((now or datetime.now(timezone.utc)) - at).total_seconds()
        return 0 <= age <= timeout
    except (ValueError, TypeError, AttributeError):
        return False


def main():
    import dotenv
    import firebase_admin
    from firebase_admin import credentials, db
    dotenv.load_dotenv()
    firebase_admin.initialize_app(credentials.Certificate(os.environ['FIREBASE_CREDS_FILE']),
                                  {'databaseURL': os.environ['FIREBASE_DB_BASE_URL'], 'httpTimeout': 10})
    root, stop = db.reference('/'), threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        try:
            online = heartbeat_online(root.child('status/LastUpdated').get())
            root.child('status/Monitor').update({'CartOnline': online,
                                               'CheckedAt': datetime.now(timezone.utc).isoformat()})
        except Exception:
            logging.exception('Connectivity check failed; leaving battery/session history untouched')
        stop.wait(30)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
