"""Persistent sessions, conservative scan correlation and durable pull requests."""
from datetime import datetime, timezone
import math
import re
import threading
import time
import uuid


def utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="milliseconds")


class CartState:
    def __init__(self, journal, slot_count=7, grace=3.0, match_window=3.0,
                 wall=time.time, monotonic=time.monotonic):
        if not 1 <= slot_count <= 12:
            raise ValueError("slot_count must be between 1 and 12")
        self.journal, self.slot_count = journal, slot_count
        self.grace, self.match_window = grace, match_window
        self.wall, self.monotonic = wall, monotonic
        self.lock = threading.RLock()
        self.sessions = journal.get_state("sessions", {})
        self.occupancy = {i: None for i in range(slot_count)}
        self.changed, self.scans, self.pending = {}, [], {}
        self.quiet_until = 0.0
        self.verified = set()
        self.started_monotonic = {}

    def _save(self):
        self.journal.set_state("sessions", self.sessions)

    def scan(self, tag):
        if not re.fullmatch(r"\d{10}", tag):
            return False
        with self.lock:
            now = self.monotonic()
            self.scans = [(t, at) for t, at in self.scans if now - at <= self.match_window]
            active = [int(slot) for slot, session in self.sessions.items() if session["batteryId"] == tag]
            if active:
                if len(active) == 1 and self.occupancy[active[0]] is True and not self.changed:
                    self.verified.add(active[0])
                return False
            if not any(t == tag for t, _ in self.scans):
                self.scans.append((tag, now))
            self.scans = self.scans[-32:]
            return True

    def disconnect(self, board):
        with self.lock:
            for slot in range((board - 1) * 6, min(board * 6, self.slot_count)):
                self.occupancy[slot] = None
                self.pending.pop(slot, None)
                self.changed.pop(slot, None)
                self.verified.discard(slot)

    def presence(self, slot, present, *, snapshot=False):
        if type(slot) is not int or slot not in self.occupancy or type(present) is not bool:
            raise ValueError("Invalid slot observation")
        with self.lock:
            if self.occupancy[slot] == present and not snapshot:
                return
            now, wall = self.monotonic(), self.wall()
            self.occupancy[slot] = present
            session = self.sessions.get(str(slot))
            if present:
                if session:
                    # A different identified battery within grace is a swap, not sensor flicker.
                    distinct = [tag for tag, at in self.scans if tag != session["batteryId"] and now - at <= self.match_window]
                    if len(distinct) == 1 and session.get("pendingEnd"):
                        removal_mono = self.pending.get(slot, (0, 0, 0, now))[3]
                        self._finish(slot, session, session["pendingEnd"], removal_mono)
                        self.pending.pop(slot, None)
                        self.changed[slot] = now
                        self.quiet_until = now + 1
                        return
                    # Preserve the same session through sensor flicker.
                    self.pending.pop(slot, None)
                    self.changed.pop(slot, None)
                    if "pendingEnd" in session:
                        with self.journal.transaction():
                            session.pop("pendingEnd")
                            self._save()
                elif not snapshot:
                    self.changed[slot] = now
                    self.quiet_until = now + 1.0
                # Initially occupied unidentified slots require removal/rescan.
            else:
                self.changed.pop(slot, None)
                if session and slot not in self.pending:
                    end = session.get("pendingEnd") or wall
                    with self.journal.transaction():
                        session["pendingEnd"] = end
                        if snapshot:
                            session["reconciledFromSnapshot"] = True
                        self._save()
                    self.pending[slot] = (now + self.grace, end, session["id"], now)

    def tick(self):
        with self.lock:
            now = self.monotonic()
            self.scans = [(t, at) for t, at in self.scans if now - at <= self.match_window]
            if now >= self.quiet_until:
                candidates = [s for s, at in self.changed.items()
                              if self.occupancy[s] is True and now - at <= self.match_window]
                if len(candidates) == 1 and len(self.scans) == 1:
                    slot, (tag, _) = candidates[0], self.scans[0]
                    self._start(slot, tag)
                    self.scans.clear()
                    self.changed.pop(slot, None)
            self.changed = {s: at for s, at in self.changed.items() if now - at <= self.match_window}
            for slot, (deadline, end, identity, removal_mono) in list(self.pending.items()):
                if now >= deadline and self.occupancy[slot] is False:
                    session = self.sessions.get(str(slot))
                    if session and session["id"] == identity:
                        self._finish(slot, session, end, removal_mono)
                    self.pending.pop(slot, None)

    def _start(self, slot, tag):
        start, identity = self.wall(), uuid.uuid4().hex
        session = {"id": identity, "batteryId": tag, "slot": slot, "start": start}
        values = {"ID": tag, "IsCharging": True, "ChargingSlot": slot,
                  "ChargingStartTime": utc(start), "ChargingEndTime": None, "SessionId": identity}
        patch = {f"BatteryList/{tag}/{k}": v for k, v in values.items()}
        patch[f"ChargeSessions/{identity}"] = {**session, "startTime": utc(start)}
        patch[f"EnrollmentRequests/{tag}"] = {"batteryId": tag, "slot": slot, "timestamp": utc(start)}
        previous = dict(self.sessions)
        try:
            with self.journal.transaction():
                self.sessions[str(slot)] = session
                self._save()
                self.journal.put_record('enrollment_requests', tag, {'batteryId': tag})
                self.journal.enqueue("", patch, event_id=identity + "_start")
            self.verified.add(slot)
            self.started_monotonic[identity] = self.monotonic()
        except BaseException:
            self.sessions = previous
            raise

    def _finish(self, slot, session, end, monotonic_end=None):
        tag, identity = session["batteryId"], session["id"]
        duration = max(0, end - session["start"])
        cycle = {"batteryId": tag, "season": str(datetime.fromtimestamp(end, timezone.utc).year),
                 "startTime": utc(session["start"]), "endTime": utc(end), "slot": slot,
                 "durationSeconds": duration, "completed": True}
        if identity in self.started_monotonic:
            cycle["durationSeconds"] = max(0, (monotonic_end if monotonic_end is not None else self.monotonic()) - self.started_monotonic[identity])
        if end < session["start"]:
            cycle["clockAnomaly"] = True
        if session.get("reconciledFromSnapshot"):
            cycle["endTimeEstimated"] = True
        values = {"IsCharging": False, "ChargingSlot": None, "ChargingStartTime": None,
                  "ChargingEndTime": utc(end), "LastChargingSlot": slot,
                  "LastOverallChargeTime": duration, "LastCycleId": identity}
        patch = {f"BatteryList/{tag}/{k}": v for k, v in values.items()}
        patch.update({f"Cycles/{identity}/{k}": v for k, v in cycle.items()})
        patch[f"ScoringRevisions/{tag}"] = {".sv": {"increment": 1}}
        patch[f"ChargeSessions/{identity}/endTime"] = utc(end)
        # Upload-ack crash replay must not overwrite later kiosk acknowledgment fields.
        patch.update({f"PullRequests/{identity}/{k}": v for k, v in {**cycle, "cycleId": identity}.items()})
        patch[f"BatteryList/{tag}/ChargingRecords/{identity}"] = {
            "StartTime": cycle["startTime"], "EndTime": cycle["endTime"],
            "Duration": duration, "ChargingSlot": slot, "ID": identity}
        previous = dict(self.sessions)
        try:
            with self.journal.transaction():
                del self.sessions[str(slot)]
                self._save()
                self.journal.put_record('cycles', identity, cycle)
                self.journal.put_record('pull_requests', identity, {**cycle, 'cycleId': identity})
                self.journal.enqueue("", patch, event_id=identity + "_end")
            self.verified.discard(slot)
            self.started_monotonic.pop(identity, None)
        except BaseException:
            self.sessions = previous
            raise

    def snapshot(self):
        with self.lock:
            return {slot: {"present": self.occupancy[slot],
                           "session": {**self.sessions.get(str(slot), {}), "verified": slot in self.verified} if str(slot) in self.sessions else {}}
                    for slot in self.occupancy}


def pick_next(slots, metadata, settings, now):
    """Unknown input never weakens eligibility."""
    if not isinstance(settings, dict) or not isinstance(metadata, dict):
        return None
    minimum = settings.get("minTime")
    if type(minimum) not in (int, float) or not math.isfinite(minimum) or minimum < 0:
        return None
    candidates = []
    for slot, state in slots.items():
        session = state.get("session", {})
        if state.get("present") is not True or not session or session.get("verified") is not True or now - session["start"] < minimum:
            continue
        battery = metadata.get(session["batteryId"])
        if not isinstance(battery, dict) or battery.get("retirementDate") or battery.get("status", "competition-ready") != "competition-ready":
            continue
        if not all(isinstance(battery.get(key), str) and battery[key].strip() for key in ('id', 'name', 'brand', 'purchaseDate')):
            continue
        cache = battery.get("cache") or {}
        score, confidence = cache.get("latestMatchScore"), cache.get("latestMatchConfidence")
        try:
            at = datetime.fromisoformat(cache["latestVoltageAt"].replace("Z", "+00:00")).timestamp()
            fresh = 0 <= now - at <= float(settings.get("maxReadinessAgeHours", 2)) * 3600
            valid = all(type(v) in (float, int) and math.isfinite(v) for v in (score, confidence))
            if fresh and valid and 0 <= score <= 100 and float(settings.get("minimumMatchConfidence", .45)) <= confidence <= 1:
                candidates.append((score, now - session["start"], -slot, slot))
        except (KeyError, ValueError, TypeError):
            continue
    return max(candidates)[-1] if candidates else None
