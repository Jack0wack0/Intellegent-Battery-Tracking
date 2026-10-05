#!/usr/bin/env python3
"""Unattended cart runtime. Local collection is independent of cloud/network status."""
from datetime import datetime, timezone
import glob
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import select
import signal
import threading
import time
import uuid

from cart_state import CartState, pick_next, utc
from wal import LocalQueue

log = logging.getLogger("cart")


class SerialWorker(threading.Thread):
    def __init__(self, path, board, state, stop, serial_factory=None):
        super().__init__(name=f"board-{board}", daemon=True)
        self.path, self.board, self.state, self.stop = path, board, state, stop
        self.serial_factory = serial_factory
        self.port = None
        self.write_lock = threading.Lock()
        self.pending_lock = threading.Lock()
        self.pending = {}
        self.last_response = 0.0
        self.synchronized = False
        self.generation = 0
        self.snapshot = None

    @property
    def healthy(self):
        return self.port is not None and self.synchronized and time.monotonic() - self.last_response < 8

    def send(self, line):
        with self.write_lock:
            if self.port is None:
                return False
            try:
                self.port.write((line + "\n").encode("ascii"))
                return True
            except Exception as error:
                log.warning("Board %s write failed: %s", self.board, error)
                return False

    def command(self, body, timeout=1.5):
        identity = uuid.uuid4().hex[:12]
        event = threading.Event()
        with self.pending_lock:
            self.pending[identity] = event  # Register before writing: immediate ACK is safe.
        try:
            return self.send(f"CMD {identity} {body}") and event.wait(timeout)
        finally:
            with self.pending_lock:
                self.pending.pop(identity, None)

    def consume(self, line):
        if line == f"BEGIN {self.board} V2":
            self.synchronized = False
            self.snapshot = {}
            return
        if line == f"END {self.board}" and self.snapshot is not None:
            expected = set(range((self.board - 1) * 6, self.board * 6))
            if set(self.snapshot) != expected:
                raise ValueError("Incomplete board snapshot")
            for slot, present in self.snapshot.items():
                if slot < self.state.slot_count:
                    self.state.presence(slot, present, snapshot=True)
            self.snapshot = None
            self.synchronized = True
            self.last_response = time.monotonic()
            self.generation += 1
            return
        if line == "PONG":
            self.last_response = time.monotonic()
            return
        ack = re.fullmatch(r"ACK ([a-f0-9]{12})", line)
        if ack:
            with self.pending_lock:
                event = self.pending.get(ack[1])
                if event:
                    event.set()
            self.last_response = time.monotonic()
            return
        observation = re.fullmatch(r"SLOT_(\d+):(PRESENT|REMOVED)", line)
        if observation:
            slot = int(observation[1])
            if not (self.board - 1) * 6 <= slot < self.board * 6:
                raise ValueError("Slot belongs to another board")
            present = observation[2] == "PRESENT"
            if self.snapshot is not None:
                self.snapshot[slot] = present
            elif self.synchronized and slot < self.state.slot_count:
                self.state.presence(slot, present)
            self.last_response = time.monotonic()

    def run(self):
        if self.serial_factory is None:
            from serial import Serial
            self.serial_factory = Serial
        while not self.stop.is_set():
            try:
                port = self.serial_factory(self.path, 9600, timeout=.2, write_timeout=1)
                with self.write_lock:
                    self.port = port
                self.synchronized = False
                self.snapshot = None
                # Opening an UNO resets it; request again after boot if necessary.
                ping_at, snapshot_at, opened = 0.0, 0.0, time.monotonic()
                while not self.stop.is_set():
                    now = time.monotonic()
                    if now - ping_at >= 2:
                        if not self.send("PING"):
                            raise OSError("PING write failed")
                        ping_at = now
                    if not self.synchronized and now - snapshot_at >= 2:
                        self.send("SNAPSHOT")
                        snapshot_at = now
                    raw = port.read_until(b"\n", size=128)
                    if raw:
                        if not raw.endswith(b"\n"):
                            raise ValueError("Overlong/unterminated serial message")
                        try:
                            self.consume(raw.decode("ascii").strip())
                        except (ValueError, UnicodeError):
                            log.warning("Rejected malformed board %s message", self.board)
                    if now - max(self.last_response, opened) > 10:
                        raise OSError("Board response timeout")
            except Exception:
                log.warning("Board %s unavailable; reopening", self.board, exc_info=True)
            finally:
                self.state.disconnect(self.board)
                self.synchronized = False
                with self.write_lock:
                    if self.port:
                        self.port.close()
                    self.port = None
            self.stop.wait(2)


class RFIDReader(threading.Thread):
    """Read only explicitly configured keyboard-wedge devices, never GUI stdin."""
    def __init__(self, paths, state, stop):
        super().__init__(name="rfid", daemon=True)
        if not paths:
            raise ValueError("RFID_DEVICES must list dedicated /dev/input/by-id/*event-kbd paths")
        self.paths, self.state, self.stop = paths, state, stop
        self.last_scan = None
        self.connected = 0

    def run(self):
        from evdev import InputDevice, ecodes
        digits = {getattr(ecodes, f"KEY_{i}"): str(i) for i in range(10)}
        digits.update({getattr(ecodes, f"KEY_KP{i}"): str(i) for i in range(10)})
        devices, buffers, activity = {}, {}, {}
        try:
            while not self.stop.is_set():
                configured = {p for pattern in self.paths for p in glob.glob(pattern)}
                for path in configured - devices.keys():
                    try:
                        device = InputDevice(path)
                        device.grab()  # Prevent scans being typed into the kiosk's forms.
                        devices[path], buffers[path], activity[path] = device, "", time.monotonic()
                    except OSError:
                        log.warning("RFID device unavailable: %s", path)
                for path in list(devices):
                    if path not in configured:
                        devices.pop(path).close()
                        buffers.pop(path, None)
                self.connected = len(devices)
                readable, _, _ = select.select(list(devices.values()), [], [], .5)
                for device in readable:
                    path = next(p for p, d in devices.items() if d is device)
                    try:
                        for event in device.read():
                            if event.type != ecodes.EV_KEY or event.value != 1:
                                continue
                            now = time.monotonic()
                            if now - activity[path] > 2:
                                buffers[path] = ""
                            activity[path] = now
                            if event.code in (ecodes.KEY_ENTER, ecodes.KEY_KPENTER):
                                if self.state.scan(buffers[path]):
                                    self.last_scan = utc(time.time())
                                buffers[path] = ""
                            elif event.code in digits:
                                buffers[path] += digits[event.code]
                                if len(buffers[path]) > 10:
                                    buffers[path] = "invalid"
                            elif event.code not in (ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT):
                                buffers[path] = "invalid"
                    except OSError:
                        devices.pop(path).close()
                        buffers.pop(path, None)
        finally:
            for device in devices.values():
                device.close()
            self.connected = 0


def cloud_loop(journal, stop, shared):
    """Firebase init/retry stays outside hardware workers, including offline startup."""
    import firebase_admin
    from firebase_admin import credentials, db
    root = None
    while not stop.is_set():
        try:
            if root is None:
                try:
                    firebase_admin.get_app()
                except ValueError:
                    firebase_admin.initialize_app(credentials.Certificate(os.environ["FIREBASE_CREDS_FILE"]),
                                                  {"databaseURL": os.environ["FIREBASE_DB_BASE_URL"], "httpTimeout": 5})
                root = db.reference("/")
            journal.process(root)
            # Fresh reads needed for recommendation eligibility. Outage clears eligibility.
            settings, metadata = root.child("Settings").get(), root.child("Batteries").get()
            with shared["lock"]:
                shared.update(settings=settings, metadata=metadata, fetched=time.monotonic())
            if isinstance(settings, dict) and isinstance(metadata, dict):
                journal.set_state("last_known_settings", settings)
                journal.set_state("last_known_metadata", metadata)
        except Exception:
            log.warning("Cloud unavailable; collecting locally", exc_info=True)
            with shared["lock"]:
                shared["fetched"] = 0
        stop.wait(3)


def led_loop(state, ports, reader, stop, shared):
    last_sent, generation = {}, -1
    positions = [3, 11, 18, 26, 34, 42, 49, 57, 65, 73, 81, 89]
    while not stop.wait(.2):
        slots = state.snapshot()
        with shared['lock']:
            eligible = time.monotonic() - shared['fetched'] < 10
            next_slot = pick_next(slots, shared['metadata'], shared['settings'], time.time()) if eligible else None
        if not all(p.healthy for p in ports) or not reader.connected:
            next_slot = None
        if ports[0].generation != generation:
            last_sent.clear()
            generation = ports[0].generation
        if ports[0].healthy:
            for slot, entry in slots.items():
                if entry["present"] is None:
                    mode, hue = "FLASH", 200
                elif not entry["present"]:
                    mode, hue = "PULSE", 25
                elif not entry["session"] or not entry["session"].get("verified"):
                    mode, hue = "FLASH", 0
                elif slot == next_slot:
                    mode, hue = "DEEPPULSE", 85
                else:
                    mode, hue = "SOLID", 0
                command = f"SEG {slot} POS {positions[slot]} COLOR {hue} MODE {mode}"
                if last_sent.get(slot) != command and ports[0].command(command):
                    last_sent[slot] = command


def main():
    from dotenv import load_dotenv
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env")
    directory = Path(os.environ.get("STATE_DIRECTORY", root / "state"))
    directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.addHandler(RotatingFileHandler(directory / "cart.log", maxBytes=2_000_000, backupCount=3))
    config = json.loads((root / "hardwareIDS.json").read_text())
    journal = LocalQueue(directory / "cart.sqlite3")
    state = CartState(journal, slot_count=int(os.environ.get("SLOT_COUNT", "7")))
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    ports = [SerialWorker(config[f"COM_PORT{i}"], i, state, stop) for i in (1, 2)]
    reader = RFIDReader([p.strip() for p in os.environ.get("RFID_DEVICES", "").split(",") if p.strip()], state, stop)
    shared = {"lock": threading.Lock(), "settings": None, "metadata": None, "fetched": 0}
    workers = ports + [reader, threading.Thread(target=cloud_loop, args=(journal, stop, shared), name="cloud", daemon=True)]
    workers.append(threading.Thread(target=led_loop, args=(state, ports, reader, stop, shared), name='leds', daemon=True))
    for worker in workers:
        worker.start()
    heartbeat = 0
    try:
        while not stop.wait(.1):
            if not all(worker.is_alive() for worker in workers):
                raise RuntimeError('Required cart worker stopped')
            state.tick()
            slots = state.snapshot()
            with shared['lock']:
                eligible = time.monotonic() - shared['fetched'] < 10
                next_slot = pick_next(slots, shared['metadata'], shared['settings'], time.time()) if eligible else None
            if not all(p.healthy for p in ports) or not reader.connected:
                next_slot = None
            if time.monotonic() - heartbeat >= 5:
                values = {"COM_PORT1": "connected" if ports[0].healthy else "disconnected",
                          "COM_PORT2": "connected" if ports[1].healthy else "disconnected",
                          "RFID": "connected" if reader.connected else "disconnected",
                          "LastUpdated": utc(time.time()), "ProtocolVersion": 2,
                          "PendingEvents": journal.size(), "Slots": {str(s): e for s, e in slots.items()}}
                journal.enqueue("status", values, coalesce_key="heartbeat")
                journal.enqueue("BatteryNextUp", {"BatteryNext": slots[next_slot]["session"]["batteryId"] if next_slot is not None else None,
                                                   "Slot": next_slot, "verifiedAt": utc(time.time())},
                                operation="set", coalesce_key="recommendation")
                heartbeat = time.monotonic()
    finally:
        stop.set()
        for worker in workers:
            worker.join(timeout=7)
        journal.close()


if __name__ == "__main__":
    main()
