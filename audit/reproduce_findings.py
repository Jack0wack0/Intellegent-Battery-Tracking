"""Offline audit checks. Failures demonstrate readiness blockers, not fixes.

Run: python3 audit/reproduce_findings.py
Only temporary files and fake transports are used. No credentials/network required.
"""
import ast
import csv
import logging
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'MachineC_OffsiteCompute'))
sys.path.insert(0, str(ROOT / 'MachineA_BatteryCart'))
from wal import LocalQueue
from filter_csv import process_csv
from battery_scoring.config import load_config
from battery_scoring.models import PullMeasurement
from battery_scoring.match_score import compute_match_score
from battery_scoring.health_score import _trend_change_pct
from battery_scoring.score_utils import normalize_linear
from dslogtocsvlibrary.entry.pdp_ctre_data import PdpCtreData


def function_from_source(relative, name, namespace):
    """Extract real functions without executing hardware/cloud initialization."""
    tree = ast.parse((ROOT / relative).read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), relative, 'exec'), namespace)
    return namespace[name]


class FakeRef:
    def __init__(self, on_write=lambda path, value: None, path=''):
        self.on_write, self.path = on_write, path

    def child(self, path):
        return FakeRef(self.on_write, path)

    def update(self, value):
        self.on_write(self.path, value)

    set = update


class AuditChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.log = logging.getLogger('audit')
        self.config = load_config()
        self.now = datetime(2026, 10, 5, tzinfo=timezone.utc)

    def queue(self):
        return LocalQueue(str(self.directory / 'queue.json'), self.log)

    def test_wal_retains_enqueue_during_flush(self):
        q = self.queue()
        q.enqueue('first', {'v': 1})
        q.process(FakeRef(lambda p, d: q.enqueue('second', {'v': 2})))
        self.assertEqual(q.size(), 1, 'concurrent enqueue was silently discarded')

    def test_wal_failed_write_preserves_order(self):
        q = self.queue()
        q.enqueue('battery', {'IsCharging': True})
        q.enqueue('battery', {'IsCharging': False})
        remote = {}
        first = True

        def write(path, data):
            nonlocal first
            if first:
                first = False
                raise OSError('temporary outage')
            remote.update(data)

        q.process(FakeRef(write))
        q.process(FakeRef(write))
        self.assertFalse(remote['IsCharging'], 'older retry overwrote newer removal')

    def test_wal_reports_disk_failure(self):
        q = self.queue()
        q.queue_file = str(self.directory / 'missing' / 'queue.json')
        with self.assertRaises(OSError):
            q.enqueue('battery', {'v': 1})

    def test_wal_corrupt_file_requires_recovery(self):
        path = self.directory / 'queue.json'
        path.write_text('[{"path":')
        with self.assertRaises((ValueError, OSError)):
            self.queue()

    def test_filter_honors_output_path(self):
        src, dst = self.directory / 'raw.csv', self.directory / 'clean.csv'
        src.write_text('date,voltage,pdp_data_currents\nnow,12.5,"[1, 2]"\n')
        original = src.read_bytes()
        process_csv(str(src), str(dst))
        self.assertEqual(src.read_bytes(), original, 'raw source was overwritten')
        self.assertTrue(dst.exists())

    def test_filter_repeat_preserves_current(self):
        src = self.directory / 'raw.csv'
        src.write_text('date,voltage,pdp_data_currents\nnow,12.5,"[1, 2]"\n')
        process_csv(str(src), str(src))
        process_csv(str(src), str(src))
        with src.open() as f:
            row = next(csv.DictReader(f))
        self.assertEqual(float(row['total_current']), 3, 'second pass replaced current with zero')

    def test_filter_flags_impossible_voltage(self):
        src = self.directory / 'raw.csv'
        src.write_text('date,voltage,pdp_data_currents\nnow,255.6,"[1, 2]"\n')
        process_csv(str(src), str(src))
        with src.open() as f:
            rows = list(csv.DictReader(f))
        self.assertFalse(rows, 'impossible voltage remains unflagged in output')

    def test_ctre_currents_do_not_bleed_between_channels(self):
        # All 16 packed ten-bit channel values encode 1 A (8 raw units).
        packed = sum(8 << (54 - 10 * i) for i in range(6))
        third = sum(8 << (54 - 10 * i) for i in range(4))
        tail = list((third >> 24).to_bytes(5, 'big')) + [0, 170, 25]
        data = struct.pack(PdpCtreData.byte_code, 0, packed, packed, *tail)
        self.assertEqual(PdpCtreData.from_bytes(data).currents, [1.0] * 16)

    def test_health_trend_detects_change_at_five_samples(self):
        c = self.config['health_score']
        change = _trend_change_pct([8, 10, 14, 20, 25], c['baseline_sample_size'],
                                   c['recent_sample_size'], c['min_points_for_trend'])
        self.assertGreater(change, 0, 'identical windows hide a large resistance increase')

    def test_invalid_voltage_is_rejected(self):
        with self.assertRaises((TypeError, ValueError)):
            PullMeasurement.from_dict('m', 'b', {'currentVoltage': -100, 'timestamp': self.now.isoformat()})

    def test_nonfinite_voltage_is_rejected(self):
        with self.assertRaises((TypeError, ValueError)):
            PullMeasurement.from_dict('m', 'b', {'currentVoltage': 'NaN', 'timestamp': self.now.isoformat()})

    def test_missing_timestamp_not_treated_as_fresh(self):
        m = PullMeasurement.from_dict('m', 'b', {'currentVoltage': 12.9})
        result = compute_match_score(m, self.config, now=self.now)
        self.assertEqual(result.confidence, 0, 'undated voltage received fresh confidence')

    def test_missing_optional_fields_are_not_zero_penalties(self):
        m = PullMeasurement('m', 'b', self.now, 12.9)
        result = compute_match_score(m, self.config, now=self.now)
        self.assertEqual(result.score, 100)
        self.assertAlmostEqual(result.confidence, .45)

    def test_stale_measurement_has_no_confidence_on_recompute(self):
        m = PullMeasurement('m', 'b', self.now - timedelta(days=4), 12.9)
        self.assertEqual(compute_match_score(m, self.config, now=self.now).confidence, 0)

    def test_normalization_bounds(self):
        self.assertEqual(normalize_linear(-100, 0, 100), 0)
        self.assertEqual(normalize_linear(200, 0, 100), 100)

    def test_serial_reader_reopens_after_unplug(self):
        opened = []

        class Port:
            def readline(self):
                raise OSError('unplug')

        def connect(*args):
            opened.append(args)
            return Port()

        ns = {'serial': types.SimpleNamespace(Serial=connect), 'BAUD_RATE': 9600,
              'time': types.SimpleNamespace(sleep=lambda _: None),
              'serial_log': self.log, 'general_log': self.log,
              'serial_ports_lock': __import__('threading').Lock(), 'serial_ports': {},
              'report_critical_error': lambda *a: None}
        fn = function_from_source('MachineA_BatteryCart/input_listener.py', 'handle_serial', ns)
        fn('fake')
        self.assertGreater(len(opened), 1, 'handler returned without reconnecting')

    def test_fast_ack_is_not_cleared(self):
        # Extract the real nested helper without starting hardware/cloud workers.
        event = __import__('threading').Event()
        tree = ast.parse((ROOT / 'MachineA_BatteryCart/input_listener.py').read_text())
        manager = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'led_manager_loop')
        helper = next(n for n in manager.body if isinstance(n, ast.FunctionDef) and n.name == 'wait_for_ack')
        ns = {'ack_received': event, 'ACK_TIMEOUT': 0, 'led_log': self.log}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), 'input_listener.py', 'exec'), ns)
        event.set()  # serial reader receives ACK immediately after write
        self.assertTrue(ns['wait_for_ack'](timeout=0), 'ACK already received was discarded')

    def test_root_stream_event_identifies_affected_batteries(self):
        fn = function_from_source('MachineC_OffsiteCompute/battery_scoring/engine.py',
                                  '_battery_id_from_event_path', {})
        self.assertIsNotNone(fn('/'), 'root patch/initial events are ignored by callbacks')

    def test_drive_listing_uses_pagination(self):
        requests = []

        class Service:
            def files(self):
                return self

            def list(self, **kwargs):
                requests.append(kwargs)
                return self

            def execute(self):
                if len(requests) == 1:
                    return {'files': [{'id': 'a', 'name': 'a.dslog'}], 'nextPageToken': 'more'}
                return {'files': [{'id': 'b', 'name': 'b.dslog'}]}

        fn = function_from_source('MachineC_OffsiteCompute/drive_sync.py', 'list_new_files', {})
        self.assertEqual(len(fn(Service(), 'folder')), 2, 'second Drive page is never fetched')

    def test_drive_filename_cannot_escape_temp_dir(self):
        # Exact path construction used by main.py for untrusted Drive names.
        target = (self.directory / 'temp' / '../outside.dslog').resolve()
        self.assertTrue(target.is_relative_to(self.directory / 'temp'))

    def test_rfid_input_with_service_stdin_closed(self):
        ns = {'input': lambda: (_ for _ in ()).throw(EOFError('systemd stdin=/dev/null'))}
        fn = function_from_source('MachineA_BatteryCart/input_listener.py', 'listen_rfid', ns)
        try:
            fn()
        except EOFError:
            self.fail('RFID loop crashes with installed service stdin')


if __name__ == '__main__':
    unittest.main(verbosity=2)
