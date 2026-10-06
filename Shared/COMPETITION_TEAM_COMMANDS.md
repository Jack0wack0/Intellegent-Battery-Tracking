# Competition team commands — existing Arduino firmware, no reflash

**Audience:** robotics team operating the Raspberry Pi battery cart, and Jackson operating
the offsite Linux computer. Keep this file available offline before leaving for competition.

**Arduino answer:** yes, the earlier hardening release changed both `.ino` files to protocol v2.
Those sketches require reflashing. **For this competition, do not upload them.** This guide uses
the new Python collector's explicit `ARDUINO_PROTOCOL=legacy` compatibility mode with the
older firmware already on the boards. The Pi compatibility fix must be installed first.

Code is on `fix/legacy-cart-competition-guide` until reviewed/merged. Use that branch for these
instructions, or the main revision containing it after merge. Merely pulling the earlier
`fix/competition-readiness` release does not add legacy compatibility.

## What works and what remains manual

- Existing board 1: slots 0–5; existing board 2: slot 6. Operator labels are slots 1–7.
  Existing serial messages are `SLOT_0:PRESENT`, `SLOT_0:REMOVED`, etc., at 9600 baud.
- Keyboard RFID capture, local durable sessions, enrollment, pull voltage entry, CBA entry and
  queued cloud uploads work without changing either Arduino sketch.
- The old firmware sends changes, not a full boot snapshot. A slot stays **unknown** until
  a real insertion/removal is observed. Unknown does not mean empty.
- Old board 2 has no heartbeat. `legacy-port-open` only means Linux opened its USB port; an
  actual slot-7 transition must be tested to establish it is responding.
- **Automatic next-battery selection is disabled in legacy mode. Choose batteries manually.**
  LED commands are best-effort and cannot be confirmed; old firmware cannot guarantee stale
  LED fallback during every Pi fault. Do not treat any green light as competition readiness.
- Insert/scan one battery at a time. Keyboard scanners do not encode slot identity. Physical
  reader cross-talk still requires a test with the actual cart.

## Responsibilities and things to bring

| Person | Responsibility |
| --- | --- |
| Robotics team | Pi, power, both existing Arduino USB connections, scanner paths, local pit screen, voltage entry and manual battery choice |
| Jackson | Offsite scorer/Drive ingestion, Firebase rules and account approvals, Cloudflare Pages build, persistent storage and server health |

Bring the Pi's normal keyboard/display, labeled batteries, voltage meter, reliable USB/power
cables, known service-user login, this guide and a spare tested backup. The service-account JSON
must already be installed privately on the correct machine; do not put it in team chat or Git.

## A. Robotics team — prepare the Pi before travel

Do this while internet and time for testing are available. Competition arrival should require
startup checks, not dependency downloads or board uploads.

### A1. Stop the collector and find the existing checkout

Use the **normal Pi service user**, not a root login. If the current service exists:

```sh
sudo systemctl stop tagtracker.service
systemctl show tagtracker.service -p WorkingDirectory --value
```

The printed directory is normally the checkout's `MachineA_BatteryCart` folder. Change into
that directory, then `cd ..` to reach the repository root. If no checkout exists yet:

```sh
cd "$HOME"
git clone --branch fix/legacy-cart-competition-guide \
  https://github.com/Jack0wack0/Intellegent-Battery-Tracking.git
cd Intellegent-Battery-Tracking
```

For an **existing** checkout, run:

```sh
git status --short
git branch --show-current
git rev-parse HEAD
```

Record the old revision. If `git status` shows local work, preserve it and ask Jackson before
changing branches. Do not run `reset --hard`, erase local commits or clone over this checkout.
From a clean checkout:

```sh
git fetch origin
git switch fix/legacy-cart-competition-guide
git merge --ff-only origin/fix/legacy-cart-competition-guide
```

If the local branch does not yet exist, `git switch` normally creates it from the uniquely named
remote branch. If this fix has already been merged, use a clean, updated main checkout containing
the fix instead. Retain the old collector/configuration/state for rollback.

### A2. Connect and identify devices

From repository root:

```sh
ls -l /dev/serial/by-id/
ls -l /dev/input/by-id/*event-kbd
cd MachineA_BatteryCart
```

Identify the two boards by disconnecting/reconnecting **one at a time** while the collector is
stopped. `COM_PORT1` is the LED board/slots 1–6; `COM_PORT2` is the slot-7 board. Identify scanner
keyboard devices the same way. Do not configure the normal keyboard as an RFID reader.

Verify the real paths in `hardwareIDS.json`:

```json
{"COM_PORT1":"/dev/serial/by-id/ACTUAL_LED_BOARD","COM_PORT2":"/dev/serial/by-id/ACTUAL_SECOND_BOARD"}
```

Edit with `nano hardwareIDS.json` if needed. Those names are examples, not literal device paths.
The installer prompts for this file if it does not exist. Close Arduino serial monitors and
other programs owning the ports. Do not open/upload sketches.

### A3. Choose legacy mode explicitly

If `.env` already exists, this command privately backs it up and changes only the two relevant
settings, retaining credentials, URLs and reader paths:

```sh
python3 - <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import shutil
p = Path('.env')
if not p.is_file():
    raise SystemExit('No .env yet: run installer and choose legacy at its prompt instead.')
backup = p.with_name('.env.before-legacy-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
shutil.copy2(p, backup)
backup.chmod(0o600)
lines = [line for line in p.read_text().splitlines()
         if not line.strip().startswith(('ARDUINO_PROTOCOL=', 'SLOT_COUNT='))]
p.write_text('\n'.join(lines + ['ARDUINO_PROTOCOL=legacy', 'SLOT_COUNT=7']) + '\n')
p.chmod(0o600)
print('Legacy mode selected; original .env retained privately.')
PY
```

If creating configuration for the first time, run the installer and select **legacy** when
prompted (legacy is the new installer's default). The configuration must contain actual values:

```dotenv
FIREBASE_DB_BASE_URL=https://YOUR_DATABASE.firebasedatabase.app
FIREBASE_CREDS_FILE=/absolute/path/to/service-account.json
RFID_DEVICES=/dev/input/by-id/ACTUAL_SCANNER-event-kbd
ARDUINO_PROTOCOL=legacy
SLOT_COUNT=7
```

Multiple scanner paths are comma-separated. Each emits ten digits followed by Enter.
Existing `.env` files without `ARDUINO_PROTOCOL` still select v2 in the runtime for compatibility
with already-flashed installations; **do not omit the explicit legacy setting on this cart**.

### A4. Install and verify

```sh
bash install.sh
systemctl status tagtracker.service --no-pager
journalctl -u tagtracker.service -n 100 --no-pager
```

Run `bash install.sh` as the intended normal service user. It uses sudo for system changes,
installs the Python environment, checks device/credential paths, configures input/dialout access
and starts the collector. It does **not** reflash either board.

Look for the `LEGACY firmware mode` warning. It is expected. Repeated `Board ... unavailable;
reopening` messages are not expected. A permissions/device/credential failure must be resolved
before accepting pulls. Log out/in after group changes if your interactive device test needs
new group access; the service uses explicit supplementary groups.

### A5. Local screen and commissioning

Open a browser **on the Pi** at:

```text
http://127.0.0.1:8765/
```

From the Pi's desktop terminal you can also use `xdg-open http://127.0.0.1:8765/` if available.
An SSH terminal on another computer cannot display this loopback screen using the Pi's LAN IP.
Browser autostart is not installed by the service installer. Set desktop autostart before travel,
or assign someone to open the browser after each reboot.

Test a known battery through **all seven physical slots, one at a time**, including slot 7.
Confirm the correct slot changes, the scan identifies the battery, and a physical pull produces
a voltage-entry task. Test pulls are real history; record their readings rather than deleting
history. Test adjacent batteries/readers for cross-talk. If identification is ambiguous, remove
and deliberately rescan/reinsert one battery at a time.

The old boards cannot reveal which initially empty/occupied slots are present. Keep **unknown**
slots out of use until an actual transition has been observed and the team has confirmed their
state. After a Pi restart with batteries present, remove/rescan/reinsert them deliberately;
a scan alone cannot prove occupancy on the old silent firmware. Complete any resulting pull
readings. Do not pretend the old session was continuously verified while the machine was off.

## B. Robotics team — arrival and start of each competition day

Do not pull updates, reinstall packages or reflash boards as an automatic morning step.

1. Connect the labeled USB cables, scanner(s), keyboard/display, charger/strip power and network.
2. Boot the Pi and log in as its normal user.
3. Run these commands:

```sh
systemctl is-active tagtracker.service
systemctl status tagtracker.service --no-pager
journalctl -u tagtracker.service -n 60 --no-pager
```

Expected first command: `active`. Expected logs: legacy-mode warning and no repeated failures.
If the service is not active, run `sudo systemctl start tagtracker.service` once and inspect logs.
Do not start a second `input_listener.py` manually beside systemd.

4. Open `http://127.0.0.1:8765/` on the Pi. Confirm the local collector heartbeat is current,
   RFID is connected, legacy/manual selection is displayed and slots reflect observed changes.
5. Establish known state through real slot transitions. Check slot 7 explicitly after any
   USB/power change; an open serial port is not proof the second board is sensing correctly.
6. Confirm account access on `https://batteries.jacksonyoes.com/` when online. If access is
   pending or Firebase reports permission denied, tell Jackson; keep local entry available.
7. Run one known scan/place/pull/voltage save. Wait for the on-cart save acknowledgment. Confirm
   its cloud backlog drains after connectivity returns. Never erase a backlog to make the count zero.

For a terminal-only local check, obtain the service directory and summarize the local API:

```sh
COMP_CART_DIR="$(systemctl show tagtracker.service -p WorkingDirectory --value)"
cd "$COMP_CART_DIR"
curl --fail --silent --show-error http://127.0.0.1:8765/api/state | venv/bin/python -c '
import json, sys
s = json.load(sys.stdin)
h = s.get("collectorStatus", {})
print("Firmware:", h.get("FirmwareMode"), "Heartbeat:", h.get("LastUpdated"))
print("RFID:", h.get("RFID"), "Boards:", h.get("COM_PORT1"), h.get("COM_PORT2"))
print("Cloud backlog:", s["pendingEvents"], "Unentered pulls:", len(s["pullRequests"]))
for slot, value in s["slots"].items():
    session = value.get("session") or {}
    print("Slot", int(slot)+1, "present=", value["present"], "identified=", bool(session.get("verified")))
'
```

Expected firmware: `legacy`; LEDs remain unconfirmed and selection manual. `None`/`null` presence
means unknown. Read the timestamp: a stale heartbeat is not a successful operational check.

## C. During competition and shift changes

### Every placement/pull

- Keep the local Pi screen open. Assign one person to battery handling/entry at a time.
- Place and scan one battery, then confirm the correct slot/identity before placing another.
- Unknown tags need name, brand and actual purchase date; ask the battery lead if unknown.
- For a pull, enter **current voltage in volts**. SOC (%), internal resistance (mΩ), and 1 A/18 A
  voltages are optional; leave unavailable fields blank. Zero is a real reading, not a blank.
- Wait for “Saved durably on this cart.” Do not equate typing a number with saving it.
- Review/clear every unentered pull through proper entry before handoff. Pull requests remain
  available even after the battery returns to charging.
- Select the next match battery manually using verified recent meter readings, charger time,
  approved team procedure and battery condition. Do not rely on automatic green LEDs in legacy mode.
- CBA capacity tests are separate from ordinary pulls; enter Ah and season in the separate action.

### Internet loss

Continue using the local Pi screen if its collector is healthy. New enrollment and readings
persist in SQLite and upload later. The remote website cannot see fresh cart events until the
cart reconnects. Existing remote browser tasks persist in IndexedDB; do not clear browser data,
switch profiles/origins or upload another user's pending readings under a different account.

At handoff, report pending-event count, unentered pulls, unknown slots and any conflicts.
A conflict preserves both readings; ask the battery lead/Jackson to reconcile it rather than
blindly entering a third reading or overwriting history.

### Reader/USB failure, reboot or wrong identity

Pause automatic use of the affected slot, preserve saved data and inspect:

```sh
journalctl -u tagtracker.service -n 100 --no-pager
ls -l /dev/serial/by-id/
ls -l /dev/input/by-id/*event-kbd
```

Reconnect the correct device. The collector retries. If it remains broken, coordinate a restart:

```sh
sudo systemctl restart tagtracker.service
systemctl status tagtracker.service --no-pager
```

A restart requires deliberate occupancy/identity recovery with legacy firmware. Recheck every
slot's physical state and remove/rescan/reinsert affected batteries; complete real pull tasks.
Do not delete `.sqlite3`, the old JSON queue or Firebase charging records to “reset” the cart.
If a reading did not receive a save acknowledgment, retain the actual meter reading and resolve
storage/service failure before claiming it was recorded.

## D. Jackson — offsite computer setup and event-day commands

The offsite computer does **not** need Arduino access or reflashing. It runs scoring and Drive
ingestion. Complete first-time installation before travel using the
[detailed installation guide](INSTALL_COMPETITION_RELEASE.md#6-configureinstall-the-offsite-host):
Python 3.10+, private credentials, writable mounted backup storage, Drive OAuth JSON authorization,
`.env`, then `bash MachineC_OffsiteCompute/install.sh` as the intended service user.

Its required settings are `FIREBASE_DB_BASE_URL`, `FIREBASE_CREDS_FILE`, `GOOGLE_CREDS_PATH`,
`GOOGLE_TOKEN_PATH`, `DRIVE_FOLDER_ID` and `LOCAL_STORAGE_PATH`. The web build and cart must use
the same database. Browser deployments on Cloudflare Pages do not publish Firebase rules.
Verify the reviewed rules separately, including enrollment/pull/session/revision paths.
Do not make rules publicly writable to bypass an access error.

### On arrival

```sh
systemctl status offsite-scoring-engine.service offsite-firebase-scraper.service \
  offsite-check.timer --no-pager
systemctl list-timers --all
journalctl -u offsite-scoring-engine.service -n 100 --no-pager
journalctl -u offsite-check.service -n 100 --no-pager
```

If installed services need starting:

```sh
sudo systemctl start offsite-scoring-engine.service offsite-firebase-scraper.service \
  offsite-check.timer
```

Check the configured storage without printing credential contents:

```sh
COMP_OFFSITE_DIR="$(systemctl show offsite-scoring-engine.service -p WorkingDirectory --value)"
cd "$COMP_OFFSITE_DIR"
venv/bin/python - <<'PY'
from dotenv import dotenv_values
from pathlib import Path
import shutil
c = dotenv_values('.env')
p = Path(c['LOCAL_STORAGE_PATH'])
if not p.is_dir():
    raise SystemExit('Configured persistent storage is missing. Restore the mount before ingestion.')
print('Configured storage:', p)
print('Free GiB:', round(shutil.disk_usage(p).free / 1024**3, 2))
PY
```

Verify the path really belongs to the intended mounted filesystem (use `findmnt -T ACTUAL_PATH`).
Do not create a replacement directory on the root disk if the backup disk is absent.

### Run one ingestion pass now

Use the systemd entrypoint so it uses the configured environment and service user:

```sh
sudo systemctl start offsite-check.service
systemctl show offsite-check.service -p Result -p ExecMainStatus
journalctl -u offsite-check.service -n 100 --no-pager
```

The first command can wait while ingestion runs. `Result=success` and `ExecMainStatus=0` mean
that pass completed; a oneshot returning to inactive is normal. Verify new raw/CSV/metadata
artifacts actually reached persistent storage. The timer schedules subsequent passes ten minutes
after completion. Do not run competing `main.py` processes or reset the ingestion ledger.
A lack of new files is not itself an error. Truncated/unsupported files may fail visibly and
need investigation; they must not be marked successful by removing the source or editing state.

### Monitor scoring/network errors

```sh
journalctl -u offsite-scoring-engine.service -f
# Ctrl-C exits the log viewer; it does not stop the service.
```

Confirm fresh version-2 `status/Scoring` and score/cache timestamps in the approved web/database
view. Scores are computed from valid inputs; sparse/stale data should show reduced confidence.
For transient network failure, restore connectivity and observe recovery. If a service stays down:

```sh
sudo systemctl restart offsite-scoring-engine.service offsite-firebase-scraper.service
systemctl status offsite-scoring-engine.service offsite-firebase-scraper.service --no-pager
```

Expired Drive authorization: stop/pause ingestion, reauthorize using `venv/bin/python drive_sync.py
--authorize` from this directory (or securely transfer a freshly authorized JSON token from a
browser-equipped computer), then retry `offsite-check.service`. Do not use old pickle tokens.

Do not run `deploy.sh` or pull a new release during an active match without a maintenance decision.
It requires clean main and is for later reviewed releases, not first-time legacy-cart setup.
Actual robot tag events and real paired DS fixtures are still required for automatic log binding.

## E. End of day, shutdown and incident report

1. Complete outstanding voltage entries; report unresolved conflicts/unknown identities.
2. Restore internet if possible and record any remaining cloud backlog. A backlog is retained
   for the next run; never erase it before shutdown.
3. Stop the relevant services before unplugging power:

```sh
# Pi
sudo systemctl stop tagtracker.service
sudo shutdown -h now

# Offsite host, if shutting it down
sudo systemctl stop offsite-check.timer offsite-check.service \
  offsite-scoring-engine.service offsite-firebase-scraper.service
sudo shutdown -h now
```

Wait for shutdown before disconnecting power/storage. Preserve the entire state directory, including
SQLite WAL sidecars. For live backups use SQLite's backup API. Keep credential backups private.

When asking Jackson for help, send device/slot, local time, exact visible error, whether a local
save acknowledgment occurred, pending counts and the recent service log excerpt. Do not send
passwords, `.env` contents, service-account JSON or the OAuth token. Say whether firmware mode
was legacy, whether a reboot/USB reset happened and whether slot 7 was physically tested.

## Final sign-off

The compatibility branch passed 65 backend tests, including legacy parsing, durable pulls,
unconfirmed LED writes and a silent-board-2 regression. This is software evidence. Before relying
on it at competition, test the actual existing board firmware, all seven slots, keyboard readers,
local saves, reconnect and recovery. If the flashed firmware differs from the older sketches
reviewed here, stop and report its serial messages rather than assuming compatibility.
