# Machine A: competition cart

See the [coordinated change summary and detailed installation guide](../Shared/INSTALL_COMPETITION_RELEASE.md) before installing this release.

Runs seven slots by default: Arduino 1 supplies slots 0–5, Arduino 2 supplies slot 6.
The dedicated RFID scanners act as USB keyboards. Scans are read using Linux evdev and
are grabbed exclusively, so they do not depend on terminal stdin or Chromium focus.

Use Raspberry Pi OS/Debian with Python 3.10+. Upload **both protocol-v2 sketches** before
running the new collector. The older sketches do not implement initial snapshots or
correlated command acknowledgments.

## Configure and install

```sh
cd MachineA_BatteryCart
./install.sh
```

The installer uses a virtualenv, checks required configuration, grants the service user
`dialout`/`input` access, replaces the systemd unit deliberately and verifies it starts.
Choose only dedicated scanner devices: `/dev/input/by-id/*event-kbd`. Do not select a
normal keyboard. Stable board paths belong in the ignored `hardwareIDS.json`:

```json
{"COM_PORT1":"/dev/serial/by-id/BOARD_ONE","COM_PORT2":"/dev/serial/by-id/BOARD_TWO"}
```

Local `.env`:

```dotenv
FIREBASE_DB_BASE_URL=https://YOUR_DATABASE.firebasedatabase.app
FIREBASE_CREDS_FILE=/absolute/path/to/service-account.json
RFID_DEVICES=/dev/input/by-id/SCANNER_ONE-event-kbd,/dev/input/by-id/SCANNER_TWO-event-kbd
SLOT_COUNT=7
```

Scanners must emit exactly ten decimal digits followed by Enter. Multiple readers are
supported, but keyboard scans do not carry slot identity. Insert one battery at a time.
Ambiguous simultaneous inserts/scans remain unidentified rather than guessing a tag.

## Durable behavior

`state/cart.sqlite3` contains active sessions and an ordered transactional outbox. A
session transition and its upload are committed together. No placement/pull calculation
needs a Firebase read. A pull produces one stable `Cycles` event and `PullRequests` entry;
open `http://127.0.0.1:8765/` in the Pi browser for immediate enrollment, required pull voltage,
optional Beak readings and separate CBA tests, including when internet is unavailable.
The local screen commits receipts and their upload in one SQLite transaction before acknowledging
a save. `KIOSK_PORT` optionally changes the loopback-only port. Keep the screen open in the pit.
The authenticated Firebase website also discovers outstanding requests on reconnect, even if
the battery returned to charging. Competing inputs retain their originals for explicit review.

The old `firebase_queue.json` is imported once without deleting the original. Invalid
JSON or SQLite corruption is a visible failure; never delete the database to "repair"
a pending queue. Disk exhaustion fails collection visibly and lets the firmware time
out instead of claiming unpersisted events succeeded. Back up the database using SQLite's
backup API; copying only the `.sqlite3` while its WAL is active is insufficient.

On boot/reconnect, initially occupied slots are not assumed empty. Existing sessions
are retained, but battery identity must be reverified by a matching scan or a deliberate
remove/rescan. Initially occupied unidentified slots need a remove/rescan. Snapshot-based
removals retain `endTimeEstimated`; clock reversals retain `clockAnomaly` for inspection.
Sensor flicker during grace preserves the session; an identified different battery is
a new session. Stable IDs prevent replay from erasing kiosk acknowledgments.

## LEDs and recommendations

- Pulsing orange: observed empty.
- Flashing red: occupied, but identity needs verification.
- Flashing purple: slot/board state unknown.
- Solid red: occupied and identified; no verified next-match recommendation.
- Deep-pulsing green: current recommended pick, based on recent valid Match Score,
  confidence, enrollment, status and the configured minimum charger time.
- Purple fallback: the Arduino has not received Pi commands/heartbeats for five seconds.

Elapsed charger time is an operational heuristic, not a direct charge-complete sensor.
No recommendation is made when settings/metadata/cloud reads, reader health, board health,
occupancy, identity, score freshness or eligibility cannot be verified. Retired/practice
batteries can charge, but do not enter the competition recommendation queue.

## Verify

```sh
systemctl status tagtracker.service
journalctl -u tagtracker.service -f
```

A green systemd state alone is insufficient: verify `status/RFID`, both synchronized boards,
`status/Slots`, `PendingEvents`, and actual scanner/LED behavior. Follow
[`Shared/competition_release.md`](../Shared/competition_release.md) for acceptance.
