> Historical audit of commit `356971d`. The implementation branch has a new regression suite
> under `tests/`; see `Shared/competition_release.md` for current behavior and acceptance.
> The old reproduction harness depends on functions removed by the repair and should be run
> against the audited revision, not used as the current release test command.

# Reliability and release-readiness audit

Date: October 5, 2026. Audited source: `356971d28bd8bbdd45c00bcc6923067df1456e43`.
The local checkout was clean and GitHub `main` matched this revision at audit time.

**Readiness recommendation: do not release as a dependable competition system yet.**
The fundamental design is useful: raw measurements and score computation are separated,
the two scores are configurable/versioned, and absent optional readings reduce confidence.
The current implementation can nevertheless lose events, stop collecting after hardware
errors, misidentify batteries, publish outdated recommendations and corrupt derived telemetry.

This branch contains audit artifacts only. It does not repair production code or deploy anything.

## Scope and evidence

Reviewed all tracked runtime source, both Arduino sketches, installers/deployment scripts,
dependency manifests, repository/ per-machine documentation, schema, security policy,
Git state and existing GitHub issues. Extracted the included FRC specification and used its
non-negotiable requirements as the product contract. The separate kiosk website, deployed
Firebase rules, Linux service state, Drive contents and physical cart were outside this checkout
and were not validated. Untracked local credentials/configuration were not read or published.
An exact-path tracked-history check found no commits for the known credential filename patterns;
this is not a comprehensive secret/history scan or assurance about deployed credentials.

Verification completed:

- All 32 tracked Python runtime files parsed successfully on the available Python 3.14 interpreter.
- `bash -n` passed for both installers and `deploy.sh`.
- Both requirements manifests installed together in a fresh temporary virtual environment;
  `pip check` reported no broken requirements. Offsite parser/converter/Drive/scoring entrypoint
  imports succeeded without running their services or authenticating.
- 21 offline audit checks ran: **18 failures and 3 passes**. These demonstrate present defects;
  this is not a passing release test suite or 18 independent defect categories.
- No Arduino toolchain was installed, so firmware compilation, electrical behavior and
  analog/RFID timing remain unverified. No Linux installation, live Firebase/Drive mutation,
  or kiosk/browser acceptance test was performed.

Run the offline checks from the repository root:

```sh
python3 audit/reproduce_findings.py
```

The harness needs Python 3.10+ and uses temporary files/fake transports. It extracts actual
functions to avoid executing module-level hardware/cloud initialization. The ACK test extracts
the actual nested helper. Path containment and root-event checks are protocol/contract probes;
they are not an end-to-end execution of the ingestion or scoring service. Corruption/disk-error
checks require visible failure instead of silent success; a future explicit recovery design may
need different assertions. Root events ultimately need their payloads handled, not merely a
single battery ID returned. Adapt those probes into integration tests as implementation changes.

See [check-results.txt](check-results.txt) for the final run. Passing cases establish only that
voltage-only scoring avoids an optional-zero penalty, normalization clamps the tested finite
values, and stale measurements receive zero confidence when explicitly recomputed.

## Prioritized findings and suggested changes

P0 means a basic operation can fail or durable battery history can be lost. P1 means an additional
readiness blocker for unattended/competition use. Each linked issue includes evidence, a concrete
change proposal and acceptance conditions; [issues.json](issues.json) preserves the exact issue bodies.

| Priority | Finding | Suggested direction | Issue |
| --- | --- | --- | --- |
| P0 | WAL loses concurrent enqueue, replays old state over new state, truncates its only file and suppresses disk/corruption errors | Transactional outbox, stable IDs, ordered delivery, durable acknowledgment and recovery | [#12](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/12) |
| P0 | Installed systemd service reads RFID through unusable stdin and exits on EOF | Dedicated HID/evdev or serial reader with stable identity and hotplug recovery | [#13](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/13) |
| P0 | Placements/removals depend on remote state before the 30-second queue flush; direct removal writes bypass the queue; flicker falls into new-session creation | Persist local sessions and timer generations; atomically replay session/cycle/pull-request transitions | [#14](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/14) |
| P1 | Unplugged serial worker exits but remains reported connected; ACK race, no command identity or enforced firmware timeout | Supervised reopen, response-based health, reset resync and correlated command acknowledgments | [#15](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/15) |
| P1 | Startup relies on occupied-slot messages neither sketch sends | Explicit complete board snapshot handshake; unknown state until synchronized | [#16](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/16) |
| P1 | First-in-window scan correlation can bind wrong batteries; scans accumulate indefinitely | Bounded/deduplicated state machine, uniqueness invariant and explicit ambiguity handling | [#17](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/17) |
| P1 | Invalid/nonfinite inputs accepted; missing timestamps treated as fresh; malformed records can stop scoring | Validated units/types/ranges/config, record-level quarantine and trusted write-boundary validation | [#18](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/18) |
| P1 | Five-point baseline and recent windows are identical and hide degradation | Independent windows, enough samples and auditable reliable baselines/CBA confidence | [#19](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/19) |
| P1 | Root stream events ignored, callbacks not protected, no periodic decay/reconciliation, metadata/cycles unwatched, non-atomic publishing | Serialized dirty work, supervised streams/retries, full reconciliation and revision-aware atomic publishing | [#20](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/20) |
| P1 | Retirement/settings read failures can make picks permissive; ranking ignores age/confidence; slot layout differs between consumers | Validated local configuration, explicit unknown state, freshness/eligibility gates and shared physical mapping | [#21](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/21) |
| P1 | Drive pagination omitted, filename identity collides, partial downloads persist, exclusions precede durable output, filenames escape staging | File ID/revision journal, atomic validated stages, safe naming, complete listing and bounded retention | [#22](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/22) |
| P1 | Filter ignores output path, destroys raw columns and zeroes current on a second pass; backup is copied before filtering | Immutable raw artifacts and atomic versioned derived output; missing current stays unknown | [#23](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/23) |
| P1 | CTRE packed-current extraction leaks neighboring bits; short records silently appear complete | Ten-bit masking, authoritative CTRE/REV fixtures, strict truncation handling and stable streamed schema | [#24](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/24) |
| P1 | Timer invokes infinite loop; updates don't restart/install dependencies; separate deploy script resets hard; required startup failures are swallowed | Choose one lifecycle, report failures, tested locked releases, non-destructive update and rollback | [#25](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/25) |
| P1 | Core workflows are distributed across an unverified separate website; event delivery/season counts/rules remain unproven | Durable requests, shared writer contract, linked release, emulator checks and full product acceptance | [#26](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/26) |

The synthetic CTRE fixture encodes 1 A on every channel. Current decoding yields 1 A on the first
channel, 1025 A on the second and values over 10^15 A on later channels. This is a deterministic
bit-extraction failure, independent of any calibration choice. The real hardware/format fixtures
are still needed before trusting corrected decoding.

The resistance sequence `[8, 10, 14, 20, 25]` produces 0% trend change with the default five/five
windows. That can make an actual rise look stable. Sparse evidence should produce reduced
confidence or an unknown trend, never a fabricated stable trend.

## Behavior against the FRC specification

| Required behavior | What this repository establishes | Readiness gap |
| --- | --- | --- |
| Exactly Match Score and Health Score | Separate calculators and versioned JSON exist | Data validation, trend correctness and freshness/convergence must be repaired |
| Unknown scan requires name, brand and purchase date | Cart creates legacy NameRequests when BatteryNames is absent | Complete enrollment belongs to separate website; validate all three fields and identity consistency |
| Every pull creates a completed cycle and requires current voltage | Legacy cart finalization and scorer parsing exist | Durable canonical cycle/pull request delivery is not implemented by this cart; website flow unverified |
| Optional Beak inputs may remain blank | Match Score uses only supplied optional fields and lowers confidence | Optional latest timestamps/history, validation, 1 A/sag/trend display and correction behavior need verification |
| Separate roughly seasonal CBA workflow | Schema and CBA reader/Health input exist | Writer/action belongs to separate website; enrollment/no-pull CBA behavior and baseline policy need completion/verification |
| Preserve all historical data and derive lifetime/season counts | New canonical nodes are documented | Cart still overwrites legacy history arrays; scorer counts all Cycles nodes and omits seasonal cache counts |
| Explainable auditable historical scores | Components, explanations, version and two latest references are saved | Full Health input/baseline/cycle/config provenance and atomic publication are incomplete |
| Fleet ranking plus retirement/status/confidence | Cart has Match Score sorting and retirementDate check | Read failures remove exclusions; score freshness/confidence ignored; practice/status filtering and website view unverified |
| Lifetime trends, correction audit and season survival | Historical schema can support them | Detail/fleet UI and correction workflow absent from this checkout; preserve raw telemetry first |

`Shared/battery_schema.md` explicitly identifies the separate website as a writer. This audit
does not infer that those UI features are missing there. It identifies the evidence and durable
integration contract needed to call the combined product ready. Match recommendations based on
elapsed charger time remain an operational heuristic: there is no charger-voltage/current sensor
in these sketches proving charge completion.

FirebaseScraper currently clears recommendations and IsCharging after unchanged-heartbeat checks.
That mixes observed hardware state with connectivity state and cannot close a canonical session
or recover a missed pull. Change that recovery behavior alongside #14/#26: mark status unknown/offline,
preserve evidence and reconcile with the returning cart rather than declaring a physical removal.
Use explicit UTC timestamps across cart/VM/browser, monotonic durations for local grace/matching,
and tests around DST/clock corrections. Existing formatted second-level local timestamps make
cross-machine interpretation and unique cycle IDs fragile.

## Existing issue follow-up

- [#5](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/5): impossible voltage remains
  unflagged; added exact reproduction and raw-preserving quality-filter acceptance notes.
- [#6](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/6): dsevents parser is a text
  placeholder for a binary format and does not bind canonical telemetry to battery/cycle; added next steps.
- [#7](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/7): linked the detailed audit backlog.
- [#10](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/10): physical reader-field cross-talk
  still needs actual shielding/adjacent-slot tests; linked the separate software ambiguity issue.
- Previously closed resilience/startup work (#2/#3/#8) cannot establish current readiness; the new
  issues capture the present counterexamples without reopening or declaring old work complete.

## Release gate and next work

The central tracker is [#27](https://github.com/Jack0wack0/Intellegent-Battery-Tracking/issues/27).
Fix #12–#14 first, then serial/startup/matching and recommendation eligibility, scoring, ingestion
and deployment. Convert the offline counterexamples into durable regression coverage around
the repaired designs. Add CI checks for scoring invariants, ingestion fixtures, service configuration
and the durable-event integration tests; this audit adds no workflows.

Before release, complete all tracker checks, including actual clean Pi installation/reboot,
reader/Arduino hotplug, occupied startup, simultaneous inserts and physical cross-talk,
fast pulls/flicker/moves, offline power-loss recovery, disk exhaustion/corruption, and prolonged
offline/online soak. Test the matching kiosk release with multiple tabs, a closed kiosk,
pending requests after restart, required enrollment/voltage, optional blanks, separate CBA,
corrections and multiple seasons. Verify scoring after reconnect/time decay and current confidence
in rankings. Validate real CTRE/REV DS fixtures and interrupted ingestion/update/rollback.

Check Firebase access rules/indexes in an emulator, verify authorized live health and backup/restore,
and record actual deployed revisions and manual acceptance evidence. Syntax and dependency success
do not establish hardware behavior, supported Linux/Python versions or correct deployed permissions.
