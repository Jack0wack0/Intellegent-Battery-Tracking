# Machine C: scoring and durable Drive ingestion

Python 3.10+ on Linux, with the pinned requirements installed into a virtualenv.
The new installer replaces units deliberately, verifies required services start, and disables
the legacy live-source auto-pull timer. Updates are explicit validated releases with rollback.

## Configure

```dotenv
FIREBASE_DB_BASE_URL=https://YOUR_DATABASE.firebasedatabase.app
FIREBASE_CREDS_FILE=/absolute/path/to/service-account.json
GOOGLE_CREDS_PATH=creds/credentials.json
GOOGLE_TOKEN_PATH=creds/token.json
DRIVE_FOLDER_ID=YOUR_EXACT_FOLDER_ID
LOCAL_STORAGE_PATH=/absolute/path/to/mounted/persistent/csvlogs
```

Both machines and the website must target the same database. Create/mount persistent storage
before installation; the pipeline refuses to fabricate a missing backup directory on the root
disk. Authorize Drive interactively once:

```sh
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
venv/bin/python drive_sync.py --authorize
./install.sh
```

Legacy executable `token.pickle` is not loaded. Reauthorize to JSON. Headless deployments can
authorize locally and copy the resulting private JSON token to the service user's configured path.

## Scoring

`offsite-scoring-engine.service` uses algorithm/config version 2. It periodically reconciles
Batteries, completed Cycles, PullMeasurements and CBATests, including metadata changes and
age/freshness decay. A renewable writer lease prevents normal simultaneous writers; each score
snapshot and cache update publishes atomically. Invalid observations are retained as raw data,
excluded from computation and surfaced in `cache/inputWarnings`. Removing the last valid voltage
clears readiness instead of retaining the old score. Optional latest values retain individual dates.

`ScoringRevisions/{batteryId}` increments with coordinated writers. History is cached locally
between revision/metadata changes, reducing repeated lifetime-history downloads. A ten-minute
full reconciliation covers legacy/admin writes that omitted revision markers. New writes should
include the marker in the same multipath update. Status is published under `status/Scoring`.

Health uses distinct median baseline/recent windows with sufficient samples, separates resistance
and capacity dimensions, reduces stale CBA confidence and records the chosen baseline. Values
are operational defaults requiring team calibration; no exact remaining-life prediction is made.
Snapshots include configuration, all measurement/CBA/cycle references and a source fingerprint.

`offsite-firebase-scraper.service` reports connectivity only. It never wipes physical charging
state, invents a removal or deletes battery history after a stale heartbeat.

## Drive

`offsite-check.timer` runs one bounded ingestion pass ten minutes after the previous pass ends.
A failed stage exits nonzero and is retried. Manual entrypoint: `venv/bin/python main.py`.

Files are identified by Drive ID/revision metadata, not filenames. Listing is paginated; downloads
are checksum/size validated and atomically published. Raw DS files and full CSV are immutable;
quality flags and derived current go into separate CSV. Missing/invalid current remains unknown,
not zero. Truncated/unsupported DS records fail visibly instead of becoming successful partial CSVs.
Raw and derived artifacts, metadata and hashes are verified in persistent storage before the
SQLite ledger marks a revision complete. Verified staging copies are then removed. Insufficient
storage headroom fails visibly; durable raw history is never silently deleted.

Binary dsevents are parsed with exact tagged-ID matching and retain every event/message.
Unique same-stem log/event pairs produce provenance-rich `.binding.json`; ambiguous/unmatched
pairs remain unassigned. Robot-generated event text must match the documented `Battery ID:`/
`Battery Tag:`/`BAT:` convention to identify tags. Actual paired robot logs still require acceptance;
telemetry is not silently used as a substitute for the required manual measurements.

## Verify and update

```sh
journalctl -u offsite-scoring-engine.service -f
journalctl -u offsite-check.service -f
systemctl list-timers --all
```

`deploy.sh` checks clean main/fast-forward topology, stages dependencies/tests, stops services
before source replacement, refreshes dependencies and rolls back on failure. Changed installer/unit
migrations require reviewed maintenance installation instead of silently retaining old units.
No live deployment has been performed by the implementation branch. Follow the coordinated
[`Shared/competition_release.md`](../Shared/competition_release.md) runbook.
