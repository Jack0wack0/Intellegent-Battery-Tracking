# Competition release: changes and installation

Use this guide for the coordinated `fix/competition-readiness` release. It covers the Pi,
two Arduino UNO boards, offsite Linux computer and BatteryTrackingWebsite. Allow a maintenance
window: the old collector cannot operate the new firmware correctly, and the website/rules must
match the new event contract. This document describes installation; it does not mean those
installations have already been performed.

Code review: [backend PR #28](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/pull/28)
and [website PR #1](https://github.com/Jack0wack0/BatteryTrackingWebsite/pull/1).

## What changed

| Component | Changes and resulting behavior |
| --- | --- |
| Pi input | Dedicated USB keyboard RFID scanners use Linux evdev instead of terminal stdin; Arduino serial devices reconnect automatically. Default configuration is seven slots. |
| Sessions/storage | SQLite commits local sessions and queued uploads together. Fast offline pulls, flicker, restart and identified swaps retain stable cycle IDs. Replay preserves saved measurements. |
| Offline pit screen | The collector serves `http://127.0.0.1:8765/` on the Pi. Enrollment, pull voltage and separate CBA tests save durably without internet; uploads retry on reconnect. |
| Firmware | Protocol-v2 startup snapshots, board/layout validation, occupancy heartbeats and correlated LED acknowledgments replace timing assumptions. Stale commands expire to purple fallback. |
| Matching/recommendations | Ambiguous scans remain unidentified. Picks require verified identity, complete enrollment, competition status, current/confident scores and confirmed hardware communication. |
| Scoring | Version-2 configuration, strict input validation, independent trend windows, CBA baseline/freshness, periodic reconciliation, writer lease and atomic score/cache publication. |
| Drive/logs | Paginated, revision-keyed retryable ingestion; atomic verified downloads/backups; immutable raw data and separate quality-flagged derived CSV. CTRE ten-bit current parsing and truncated-record handling corrected. |
| Website | Required enrollment; persistent pull tasks; voltage required with optional blanks preserved; IndexedDB upload queue/account isolation/conflict review; CBA entry, corrections, baselines, lifetime charts and cycle counts. |
| Rules/build | Approved-account access, immutable observation history and protected scorer caches. Vite replaces CRA; Node 24.15+ required. Production output remains `build/`. |
| Maintenance | Explicit installers and rollback-aware updates replace unattended source pulling. Legacy cycle migration and CBA CSV import are additive and dry-run by default. |

Software evidence: 62 backend regressions, 16 website tests, 23 database emulator assertions,
two website browser cases, the native offline kiosk browser workflow, both UNO compilations,
website production build and zero production dependency advisories. Hardware/deployed acceptance
is tracked separately in [release tracker #27](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/27).

## 1. Prepare and back up

Requirements:

- Pi and offsite host: Debian/Raspberry Pi OS or compatible Linux with systemd, Python 3.10+,
  internet for dependency installation, and a normal service user with sudo access.
- Two Arduino UNO boards; FastLED 3.6.0; Arduino IDE or CLI; actual slot wiring/strip power.
- Private Firebase service-account JSON on each machine; the same RTDB URL in both machines
  and the web build; approved crew/admin accounts configured in that database.
- Offsite host: Google Drive desktop OAuth client JSON, exact source folder ID and mounted,
  writable persistent backup storage.
- Web build computer: Node 24.15+; Java 21 for emulator checks; access to the current hosting provider.

For an existing installation, record `git rev-parse HEAD`, deployed website revision and current
firmware on each device. Save a private Firebase export, existing database rules, systemd units,
local configuration, credentials and all local queue/state files. Verify the database export can
restore into an isolated test database.

Stop the old writers **on their respective machines**, before changing source/firmware:

```sh
# Pi (existing installation)
sudo systemctl stop tagtracker.service

# Offsite Linux host (existing installation)
sudo systemctl disable --now offsite-github-update.timer
sudo systemctl stop offsite-check.timer offsite-check.service \
  offsite-scoring-engine.service offsite-firebase-scraper.service
```

Skip units that do not exist on a fresh installation. With services stopped, archive the entire
old component directories, including `state`, SQLite `-wal`/`-shm` files and any legacy
`firebase_queue.json`; keep external credential files and mounted archives separately. For a
running SQLite database use Python's `sqlite3.Connection.backup()` rather than copying only its
main file. Do not delete a queue, reset charging history or discard pending browser readings.

## 2. Get the coordinated branches

On each relevant machine, a fresh checkout is:

```sh
git clone --branch fix/competition-readiness \
  https://github.com/Jack0wack0/Intellegent-Battery-Tracking.git
cd Intellegent-Battery-Tracking
git rev-parse HEAD
```

For an existing checkout, first run `git status --short` and preserve local changes/commits.
Fetch the branch and switch only after the checkout is clean; do not use `reset --hard` or
clone over an existing directory. After the release is merged, use the reviewed main revision
instead. Record the exact installed commit for acceptance and rollback.

## 3. Build website and deploy its rules

On the web build computer:

```sh
git clone --branch fix/competition-readiness \
  https://github.com/Jack0wack0/BatteryTrackingWebsite.git
cd BatteryTrackingWebsite
node --version                    # 24.15.0 or newer
npm ci
```

Create `.env.local` using **Firebase's public web configuration**, not a service-account key:

```dotenv
REACT_APP_FIREBASE_CONFIG={"apiKey":"YOUR_WEB_KEY","authDomain":"YOUR_PROJECT.firebaseapp.com","projectId":"YOUR_PROJECT","databaseURL":"https://YOUR_DATABASE.firebasedatabase.app"}
```

Replace every placeholder. Compare `databaseURL` with both machines' `FIREBASE_DB_BASE_URL`.
Then run:

```sh
npm test
npm run test:rules                 # Java 21; isolated demo database
npx playwright install chromium
npm run test:browser
npm run build
npm audit --omit=dev
```

During the reviewed maintenance deployment, authenticate to the intended Firebase project and
publish **only** the database rules using the website's local CLI:

```sh
./node_modules/.bin/firebase login
./node_modules/.bin/firebase deploy --only database --project YOUR_PROJECT_ID
```

Upload the generated `build/` directory through the site's existing hosting/deployment process.
This repository does not configure a Firebase Hosting target; do not assume the database command
publishes the website. Verify the public site loads the new build and correct database, an approved
crew member can enroll/save measurements, and an unapproved account cannot access crew data.
Keep the previous build/rules available. Build-time environment changes require another build.

## 4. Upload both Arduino boards

On the computer connected to the Arduino boards, from the backend repository root:

```sh
python3 MachineB_ArduinoCode/prepare_sketches.py /tmp/battery-cart-sketches
```

In Arduino IDE install FastLED **3.6.0**, select **Arduino UNO**, and separately open/upload:

1. `/tmp/battery-cart-sketches/BatteryCartBoard1/BatteryCartBoard1.ino` to the LED/sensor board.
2. `/tmp/battery-cart-sketches/BatteryCartBoard2/BatteryCartBoard2.ino` to the second sensor board.

Each prepared folder contains its own `CartProtocol.h`. Do not compile both original `.ino`
files together in one folder. Disconnect/reconnect boards individually to confirm port identity.
Board 1 A0–A5 supplies slots 0–5; board 2 A0 supplies slot 6 (operator labels 1–7). Ground unused
sensor inputs, verify shared ground and appropriate external LED-strip power. The default buffer
controls pixels 0–59; power-cycle the strip to clear unused tail state.

At 9600 baud, a startup snapshot contains `BEGIN 1 V2`, `LAYOUT 7 60`, six `SLOT_…` observations
and `END 1`; board 2 uses BEGIN/END 2 and slots 6–11, without LAYOUT. Close the serial monitor
before starting the Pi collector so it does not own the port. Keep slot count seven unless the
firmware, Pi configuration and actual physical layout are deliberately changed together.

## 5. Configure/install the Pi

Connect both boards and dedicated RFID scanners. Identify persistent device paths:

```sh
ls -l /dev/serial/by-id/
ls -l /dev/input/by-id/*event-kbd
cd MachineA_BatteryCart
bash install.sh
```

Run as the intended service user, **not** `sudo bash install.sh`; it invokes sudo where needed.
For fresh configuration the installer prompts for Firebase URL/key-file path, comma-separated
scanner input paths and two distinct connected serial paths. Existing `.env`/`hardwareIDS.json`
are retained and validated: edit them explicitly if they still describe the old hardware.

`.env` must contain:

```dotenv
FIREBASE_DB_BASE_URL=https://YOUR_DATABASE.firebasedatabase.app
FIREBASE_CREDS_FILE=/absolute/path/to/service-account.json
RFID_DEVICES=/dev/input/by-id/SCANNER_ONE-event-kbd,/dev/input/by-id/SCANNER_TWO-event-kbd
SLOT_COUNT=7
```

`hardwareIDS.json` must contain the actual stable board paths:

```json
{"COM_PORT1":"/dev/serial/by-id/BOARD_ONE","COM_PORT2":"/dev/serial/by-id/BOARD_TWO"}
```

Choose scanner devices only; the collector grabs them exclusively. Leave a general-purpose
keyboard unconfigured. Each scanner must emit exactly ten decimal digits followed by Enter.
The installer creates its venv, grants input/dialout group access, installs `tagtracker.service`,
starts it and verifies it is active. Inspect:

```sh
systemctl status tagtracker.service --no-pager
journalctl -u tagtracker.service -n 100 --no-pager
```

Open **on the Pi**: `http://127.0.0.1:8765/`. This loopback screen is served by the collector;
no separate web installation or cloud sign-in is required. It cannot be opened from another
computer using the Pi's IP. Keep it open in the Pi browser; browser autostart is not installed
by `install.sh`, so configure desktop startup separately if the cart must reopen it on login.

Test one scan/insertion at a time. Unknown tags require name, brand and purchase date. On a pull,
enter voltage; leave optional meter readings blank when unavailable. Wait for the local save
acknowledgment. CBA capacity is a separate action. After reboot, verify occupied identities by
rescan or deliberate remove/rescan; an unknown slot never qualifies as a recommended pick.

## 6. Configure/install the offsite host

Mount/create the intended persistent storage **before** installing. Confirm it is the correct
filesystem and writable by the service user; avoid an unmounted directory pretending to be a
backup volume. From backend repository root:

```sh
cd MachineC_OffsiteCompute
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
mkdir -p creds
```

Place the private desktop OAuth client JSON and Firebase service-account JSON at their intended
paths. Create `.env` with actual values:

```dotenv
FIREBASE_DB_BASE_URL=https://YOUR_DATABASE.firebasedatabase.app
FIREBASE_CREDS_FILE=/absolute/path/to/service-account.json
GOOGLE_CREDS_PATH=/absolute/path/to/credentials.json
GOOGLE_TOKEN_PATH=/absolute/path/to/token.json
DRIVE_FOLDER_ID=EXACT_SOURCE_FOLDER_ID
LOCAL_STORAGE_PATH=/absolute/path/to/mounted/persistent/csvlogs
```

The folder ID is the ID in the Drive folder URL, not its display name. The Google account must
have read access to that folder. Protect private files with service-user ownership and mode 600.
Authorize interactively, then install:

```sh
venv/bin/python drive_sync.py --authorize
bash install.sh
systemctl status offsite-scoring-engine.service offsite-firebase-scraper.service \
  offsite-check.timer --no-pager
journalctl -u offsite-scoring-engine.service -n 100 --no-pager
journalctl -u offsite-check.service -n 100 --no-pager
systemctl list-timers --all
```

The authorization command loads this directory's `.env`. On a headless host, authorize on a
computer with a browser and securely transfer the resulting JSON token to `GOOGLE_TOKEN_PATH`.
Old `token.pickle` is unsupported; reauthorize. The installer disables the old auto-pull timer.
The ingestion timer runs after boot and ten minutes after the preceding pass finishes. A oneshot
service being inactive after successful completion is normal; inspect its exit status/logs.
Verify the first pass actually stores raw/derived artifacts on the persistent volume and
`status/Scoring` shows a healthy version-2 scorer.

## 7. Optional additive history/import operations

Use a private Firebase export and the **actual old Pi timezone** for a migration dry-run:

```sh
MachineC_OffsiteCompute/venv/bin/python Shared/migrate_legacy_cycles.py \
  /private/path/export.json --timezone America/Chicago --out /private/path/cycle-plan.json
```

Run from backend repository root. The timezone is an example, not a default to assume. Review
warnings and proposed cycles; ambiguous DST timestamps require explicit offsets. The plan retains
original history and creates no historical pull popups. Apply only after review with `--apply` and
both Firebase environment variables explicitly set in the process environment; these Shared
scripts do not automatically load a machine's `.env`.

CBA import uses a reviewed interchange CSV, not guessed vendor columns:

```csv
battery_id,timestamp,capacity_ah,season,notes
1234567890,2026-10-05T12:00:00Z,17,2026,Reviewed analyzer test
```

```sh
MachineC_OffsiteCompute/venv/bin/python Shared/import_cba_csv.py \
  /private/path/reviewed.csv --out /private/path/cba-plan.json
```

Map the analyzer's export into those columns with correct Ah units and timezone first. Review
the plan before adding `--apply`; complete enrollment is required, content IDs deduplicate
observations, and source hashes are retained. Selecting a reliable CBA baseline is a separate
admin action in the website.

## 8. Verify before competition; recover/update

Complete the [physical/deployed acceptance table](competition_release.md#physical-and-deployed-acceptance)
and record results in #27. Minimum checks: all seven slots; headless reboot; each reader/board
unplug/reset; adjacent-tag cross-talk; offline place/pull/save/reload/reconnect; multiple queued
pulls/conflicts; stale/practice/retired suppression; actual LED correspondence; real CTRE/REV
fixtures and robot tag events; backup restore; update rollback and an extended pit-like soak.
A green systemd status or successful compilation alone does not complete these checks.

If setup fails, stop the affected writer, retain its journal and inspect service logs/configuration.
Do not delete `cart.sqlite3`, clear IndexedDB, erase Firebase history or repeatedly reupload old
firmware beside a new collector. Restore the coordinated previous code/firmware/website/rules and
service configuration from the private backups when necessary; preserve any new events before
restoring an older database snapshot.

For later offsite updates **after this coordinated migration is installed and merged**, run
`bash MachineC_OffsiteCompute/deploy.sh` from a clean main checkout. It requires fast-forward
history, stages checks and retains previous dependencies for rollback; it refuses installer
migrations. It is not the initial branch/firmware/website installer. Pi/firmware/site updates
remain explicit coordinated installations using this guide.
