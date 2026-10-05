# Competition release and acceptance

For exact setup commands and the full change summary, use [INSTALL_COMPETITION_RELEASE.md](INSTALL_COMPETITION_RELEASE.md).

This is a coordinated cart + two Arduino boards + offsite scorer/ingestion + kiosk release.
The implementation branch fixes the audited software paths. Competition approval still requires
the actual Linux installation, deployed Firebase/website configuration and physical acceptance below.
Do not interpret local tests or an active systemd unit as that sign-off.

## Verified implementation evidence

- 62 backend regressions: durable outbox ordering/concurrency; abrupt process exit; disk-full
  rollback/corruption visibility; fast offline pulls; grace/restart/swap sessions; ambiguous scans;
  real serial reopen-loop execution; command acknowledgment races; stale/retired picks; input/config
  validation; independent trend windows; revision-aware input caching; atomic score publication;
  raw/derived artifact preservation; pagination; truncation; binary tag parsing; additive migration.
- 16 matching website tests cover required enrollment, voltage-only optional blanks/meaningful zero,
  durable IndexedDB submissions, another-tab conflicts, account isolation, CBA persistence, and
  rendered dialog/recommendation behavior. Chromium acceptance covers desktop/narrow enrollment
  and offline pull entry through page reload/reconnect using synthetic Firebase fixtures.
- 23 RTDB emulator assertions cover authentication/approval, required valid voltage, immutable historical
  readings, canonical cycle links, auditable correction, CBA history and scorer-only cache ownership.
- Two website Chromium acceptance cases and the native offline Pi kiosk workflow passed. Both UNO sketches compiled using AVR core 1.8.8, native AVR GCC 15.2 and FastLED 3.6.0.
  A no-op prototype-generation adapter was used on this ARM Mac because Arduino's bundled Intel
  ctags cannot run here; all actual C++ helpers are already declared in the shared header. This
  was an actual AVR compile, not a mock firmware build. Upload/electrical behavior remains untested.
- The website production build passes with Node 24.15/Vite. Its production dependency audit
  reported zero advisories after updating Firebase and replacing the obsolete build stack.

Use the final PR checks/evidence for counts and post-edit firmware memory numbers. Existing
`audit/check-results.txt` is a historical failure report for the pre-fix commit, not current results.

## Backup and coordinate

1. Export RTDB privately and verify it can be restored to an isolated emulator/test database.
   Retain current deployed revisions, credentials/settings, units and both Arduino sketches.
   Back up SQLite using `sqlite3.Connection.backup`; do not copy only its main file while WAL is active.
2. Confirm both machines and the website point at the same database. No local website `.env`
   was present during this implementation; verify the deployed build's configuration explicitly.
   Keep service-account files private and owned by the service user. Do not commit exports/secrets.
3. Stop cart/offsite writers for the maintenance window. Disable the old offsite auto-pull timer.
4. Deploy the reviewed website rules/indexes and matching kiosk build. Test with an approved crew
   account and a nonapproved account before granting readiness. The branch prepares rules/build;
   it does not authorize or perform a production deployment.
5. Upload both v2 sketches to their correct boards. The seven-slot default drives pixels 0–59,
   with active segments ending at pixel 53; power-cycle the strip to clear any unused tail state.
6. Configure dedicated RFID keyboard devices and stable board USB IDs, then run the reviewed Pi
   installer. Reinstall offsite units deliberately; authorize Drive to JSON and verify the backup mount.
7. Review legacy-history migration before applying it. Preserve all original records; no historical
   popup requests are fabricated. For example, with a private backup/export:

   ```sh
   python3 Shared/migrate_legacy_cycles.py /private/path/export.json \
     --timezone America/Chicago --out /private/path/cycle-plan.json
   ```

   Select the **actual old Pi timezone**, not this example by assumption. Inspect warnings and
   the plan, then apply only in the maintenance window with explicitly configured service credentials
   and `--apply`. Ambiguous/nonexistent DST timestamps require explicit offsets, not guessing.
8. Start services, verify revision/config/status, and perform all acceptance cases below. Keep the
   previous release and backups available until the actual soak passes. Use `deploy.sh` only after
   the coordinated initial unit/protocol migration; it refuses dirty/diverged/non-main checkouts.

## Physical and deployed acceptance

Record date, device revisions, operator and observed outcome for every case in release tracker #27.

| Case | Required observation |
| --- | --- |
| Pi reboot without terminal, Chromium focused | Dedicated keyboard-wedge scan captured once; no stdin EOF/restart loop; normal keyboard remains usable |
| Empty/occupied boot, one board delayed/missing | Every configured slot appears empty, occupied or unknown correctly; silence never means empty; occupied identities require verification |
| RFID/each Arduino unplug/replug/reset | Correct disconnected status, automatic reconnect/snapshot, command resync, no stale green pick |
| Reader-field cross-talk/adjacent tags/shielding | Correct tag across every physical slot; ambiguous simultaneous inserts are not guessed; grounded unused inputs do not trigger |
| Place and pull before first upload | Exactly one canonical cycle and durable pull request; no remote-record prerequisite |
| Flicker; rapid A→B swap; moving slots | Session start preserved for flicker, separate identified swap cycles, no double assignment or old timer closing a newer session |
| Kiosk closed; multiple pulls; multiple tabs | Every pending request reappears; one initial measurement per cycle; a conflict retains the losing local copy for explicit review |
| Offline entry/reload/reconnect | Submitted pull/CBA readings survive locally until cloud acknowledgment; queued reads are not uploaded under another account |
| Unknown tag | Name, brand and valid purchase date required; no skip or fully enrolled partial record |
| Voltage only; optional blanks/zero | Voltage required; blank optional values remain null; zero SOC/IR is preserved as entered rather than missing |
| CBA/correction/season switch | Separate CBA action, all previous tests retained, reliable baseline explicit, original readings retained with correction links, lifetime/season counts correct |
| Poor/sparse/stale history | Confidence/data age visible; no fake stability from overlapping windows; no stale/retired/practice/unknown next pick |
| Cloud outage, Pi power loss, restart during grace | Durable events retained; physical state reconciled; estimated timestamps flagged; no history wipe or invented removal |
| Local disk full/corrupt storage | Visible failure and firmware fallback; no silent successful enqueue/reset; recovery from verified backup demonstrated |
| Real CTRE/REV DS files and event pairs | Currents/voltage agree with known data; exact battery tags/provenance; incomplete/ambiguous logs remain unassigned or failed |
| Interrupted Drive transfer/copy/filter; duplicate/revised names; many pages | Failed stage retries; immutable raw data unchanged; no path escape/permanent exclusion; stable verified output |
| Update failure and rollback | Previous code/dependencies/services recover; local work preserved; running revision and health verified |
| Extended soak | Run through a pit-like offline/online cycle, monitor outbox/storage/health, then verify event counts/history and backup restore |

## Operating limits to keep explicit

- No charger-voltage/current sensor proves charge completion. Elapsed time plus recent manual
  measurements provides an operational recommendation, not an electrical guarantee.
- Keyboard scans lack slot identity. Insert/rescan one battery at a time; simultaneous ambiguity
  needs operator recovery, and software cannot replace the physical reader/shielding test.
- Open the local Pi pit screen at `http://127.0.0.1:8765/` for immediate offline enrollment,
  pull readings and CBA entry. It is served by the collector and needs no CDN or cloud login.
  Firebase website requests appear when connectivity returns; existing web readings remain
  in IndexedDB. Competing submissions preserve both raw copies and expose a conflict.
- DS pairing does not invent robot tag telemetry or assign unmatched logs. Actual robot emission
  and real paired fixtures remain required before claiming automatic robot/cycle association.
- Algorithm thresholds are unvalidated operational defaults. Recalibrate with team data using a
  new configuration version; preserve raw history and score provenance.

## Local verification commands

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r MachineA_BatteryCart/requirements.txt -r MachineC_OffsiteCompute/requirements.txt
.venv/bin/python -m unittest discover -s tests -v
bash -n MachineA_BatteryCart/install.sh MachineC_OffsiteCompute/install.sh MachineC_OffsiteCompute/deploy.sh
```

The matching website has its own `npm test`, `npm run test:rules`, `npm run test:browser`,
`npm run build` and `npm audit --omit=dev` checks. Use Node 24.15+ and Java 21 for emulator tests.
All automated checks use synthetic data; a passing local run is not a deployed acceptance result.

Native kiosk browser reproduction (synthetic data only): start `python tests/kiosk_fixture.py`,
then run `PLAYWRIGHT_MODULE=/path/to/BatteryTrackingWebsite/node_modules/playwright node tests/kiosk_browser.mjs`.
The fixture defaults to port 8765; never run it beside the live collector.

CBA CSV interchange import: `python Shared/import_cba_csv.py reviewed.csv --out private-plan.json`.
Required columns are `battery_id,timestamp,capacity_ah,season`, optional `notes`; timestamps
need explicit UTC offsets. Map vendor exports deliberately and review the plan before `--apply`
with service credentials. Content IDs deduplicate observations; original source hashes are retained.
