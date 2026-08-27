# Battery Health & Match Scoring — Data Model

Source of truth for the Firebase Realtime Database nodes used by the FRC Battery
Health & Match Scoring system (see `FRC_Battery_Health_and_Match_Scoring_Specification.docx`
at the repo root). This is additive to the existing charging-cart schema
(`BatteryList`, `BatteryNames`, `status`, ...) used by `MachineA_BatteryCart` and
the website's live charging dashboard — nothing below replaces those nodes.

Consumers of this schema:
- `MachineC_OffsiteCompute/battery_scoring/` — computes and writes `ScoreSnapshots`
  and cached fields on `Batteries`. Runs off-cart to keep CPU/network load off the
  Raspberry Pi.
- The battery-tracking website (`~/BatteryTrackingWebsite`, kiosk browser on the
  cart) — writes `Batteries` (enrollment/edit), `Cycles` + `PullMeasurements`
  (pull popup, triggered by watching `BatteryList` for a finalized removal), and
  will write `CBATests` (separate CBA workflow). Reads `ScoreSnapshots`/cached
  fields for the battery detail view.

## Nodes

### `Batteries/{batteryId}`
```
Batteries/{batteryId}
  id: string                # same as batteryId (RFID tag), immutable
  name: string               # required at enrollment
  brand: string              # required at enrollment
  purchaseDate: string (ISO date)  # required at enrollment
  createdAt: string (ISO datetime)
  model: string | null       # optional metadata
  ratedCapacityAh: number | null
  serialNumber: string | null
  notes: string | null
  retirementDate: string | null
  cache:
    totalCycleCount: number
    seasonCycleCount: { [season]: number }
    latestVoltage: number | null
    latestVoltageAt: string | null
    latestSOC: number | null
    latestInternalResistanceMilliOhm: number | null
    latest1AVoltage: number | null
    latest18AVoltage: number | null
    latestCBACapacityAh: number | null
    latestCBATestAt: string | null
    latestMatchScore: number | null
    latestMatchConfidence: number | null
    latestHealthScore: number | null
    latestHealthConfidence: number | null
    scoreAlgorithmVersion: number | null
```
Cached fields are for fast dashboard reads only. Historical nodes below are the
source of truth and are never overwritten.

### `Cycles/{cycleId}`
```
Cycles/{cycleId}
  batteryId: string
  season: string
  startTime: string (ISO datetime)
  endTime: string | null      # set on pull
  slot: number | null
  pullMeasurementId: string | null
```
`cycleId` is deterministically derived by the kiosk website as
`sanitize(batteryId + "_" + BatteryList/{id}/ChargingEndTime)` so that repeated
detection of the same finalized pull (e.g. from multiple open kiosk tabs)
converges on the same node instead of creating duplicates.

### `PullMeasurements/{batteryId}/{measurementId}`
```
timestamp: string (ISO datetime)
cycleId: string | null
currentVoltage: number        # REQUIRED, volts
socPercent: number | null            # nullable, never coerced to 0
internalResistanceMilliOhm: number | null
voltage1A: number | null
voltage18A: number | null
```
Every submitted measurement is a new node (push ID) — never overwrite a prior
measurement. `currentVoltage` must be present to write this node at all.

### `CBATests/{batteryId}/{testId}`
```
timestamp: string (ISO datetime)
season: string
capacityAh: number
notes: string | null
```
Roughly one per battery per season. Never overwritten; every test is kept
permanently.

### `ScoreSnapshots/{batteryId}/{scoreId}`
```
timestamp: string (ISO datetime)
algorithmVersion: number
matchScore: number (0-100)
matchConfidence: number (0-1)
matchComponents: [ { metric, rawValue, normalizedValue, weight, freshness, contribution } ]
matchExplanation: [ string ]
healthScore: number (0-100)
healthConfidence: number (0-1)
healthComponents: [ { metric, rawValue, normalizedValue, weight, contribution } ]
healthExplanation: [ string ]
inputRefs: { measurementId, cbaTestId, cycleId }  # what was used to compute this snapshot
```
Written by the scoring engine after every new `PullMeasurements` or `CBATests`
write. Historical snapshots are never deleted so scores stay auditable across
algorithm versions.

### `ScoringConfig/{version}`
Versioned weights/thresholds consumed by the scoring engine — see
`MachineC_OffsiteCompute/battery_scoring/scoring_config_v1.json` for the
canonical defaults. Nothing scientific is hard-coded; recalibrate by editing
config and bumping the version.

## Non-negotiables carried over from the spec
- `currentVoltage` is the only required pull field; everything else optional and
  nullable — never coerced to `0`.
- Missing optional data reduces **confidence**, not the score itself.
- Raw observations never depend on a scoring algorithm version; scores are
  recomputed into new `ScoreSnapshots` entries when the algorithm changes.
- Lifetime and per-season cycle counts, CBA history, and score history are all
  retained indefinitely across season boundaries.
