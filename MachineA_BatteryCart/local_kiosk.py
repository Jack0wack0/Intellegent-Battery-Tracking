"""Loopback-only pit kiosk. Validated measurements persist before any network access."""
from datetime import datetime, timezone
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import re

from cart_state import utc


def numeric(value, field, lower, upper, optional=False):
    if value is None and optional:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError(f'{field} is outside its valid numeric range')
    return value


class KioskStore:
    def __init__(self, journal, state):
        self.journal, self.state = journal, state

    def metadata(self):
        local = self.journal.records('enrollments')
        for tag, remote in (self.journal.get_state('last_known_metadata', {}) or {}).items():
            if isinstance(remote, dict):
                local[tag] = {**remote, **local.get(tag, {})} if not all(remote.get(k) for k in ('id','name','brand','purchaseDate')) else remote
        return local

    def reconcile(self, root):
        for identity, request in self.journal.pending_pulls().items():
            pointer = root.child(f'Cycles/{identity}/pullMeasurementId').get()
            if pointer:
                record = root.child(f"PullMeasurements/{request['batteryId']}/{pointer}").get()
                if isinstance(record, dict) and record.get('cycleId') == identity:
                    with self.journal.transaction():
                        if identity not in self.journal.records('pull_measurements'):
                            self.journal.put_record('pull_measurements', identity, record)

    def snapshot(self):
        metadata = self.metadata()
        requests = self.journal.records('enrollment_requests')
        enrollment = [tag for tag in requests if not all((metadata.get(tag) or {}).get(field) for field in ('id','name','brand','purchaseDate'))]
        return {'slots': {str(k): v for k, v in self.state.snapshot().items()}, 'batteries': metadata,
                'enrollmentRequests': enrollment, 'pullRequests': self.journal.pending_pulls(),
                'conflicts': self.journal.records('conflicts'), 'pendingEvents': self.journal.size()}

    def enroll(self, data):
        identity = data.get('id', '')
        if not re.fullmatch(r'\d{10}', identity):
            raise ValueError('A ten-digit battery ID is required')
        name, brand, purchased = data.get('name'), data.get('brand'), data.get('purchaseDate')
        if not all(isinstance(value, str) and value.strip() for value in (name, brand, purchased)) or max(len(name), len(brand)) > 100:
            raise ValueError('Name, brand and purchase date are required')
        date = datetime.strptime(purchased, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        if date.date().isoformat() != purchased or date > datetime.now(timezone.utc):
            raise ValueError('Purchase date must be valid and not in the future')
        record = {'id': identity, 'name': name.strip(), 'brand': brand.strip(), 'purchaseDate': purchased,
                  'createdAt': utc(__import__('time').time())}
        with self.journal.transaction():
            existing = self.metadata().get(identity)
            if existing and all(existing.get(field) for field in ('id','name','brand','purchaseDate')):
                return existing
            self.journal.put_record('enrollments', identity, record)
            self.journal.enqueue('', record, operation='enrollment', event_id='enroll_' + identity)
        return record

    def observation(self, data):
        kind = data.get('kind')
        identity = data.get('id', '')
        if kind not in ('pull', 'cba') or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', identity):
            raise ValueError('A stable observation ID and kind are required')
        tag = data.get('batteryId', '')
        battery = self.metadata().get(tag) or {}
        if not re.fullmatch(r'\d{10}', tag) or not all(battery.get(field) for field in ('id','name','brand','purchaseDate')):
            raise ValueError('Complete battery enrollment before recording observations')
        record = {'timestamp': utc(__import__('time').time()), 'recordedBy': 'cart-local'}
        if kind == 'pull':
            request = self.journal.records('pull_requests').get(identity)
            if not request or request['batteryId'] != tag:
                raise ValueError('Measurement must belong to an existing completed pull')
            record.update(cycleId=identity, currentVoltage=numeric(data.get('currentVoltage'), 'Current voltage', .001, 16))
            for field, maximum in (('socPercent',100),('internalResistanceMilliOhm',200),('voltage1A',16),('voltage18A',16)):
                record[field] = numeric(data.get(field), field, 0, maximum, optional=True)
            bucket, root = 'pull_measurements', 'PullMeasurements'
        else:
            season, notes = data.get('season'), data.get('notes') or ''
            if not isinstance(season, str) or not re.fullmatch(r'\d{4}', season) or not isinstance(notes, str) or len(notes) > 1000:
                raise ValueError('CBA season and notes are invalid')
            record.update(capacityAh=numeric(data.get('capacityAh'), 'Capacity', .001, 100), season=season, notes=notes or None)
            bucket, root = 'cba_tests', 'CBATests'
        value = {'id': identity, 'batteryId': tag, 'kind': kind, 'path': f'{root}/{tag}/{identity}', 'record': record}
        with self.journal.transaction():
            existing = self.journal.records(bucket).get(identity)
            if existing:
                return existing
            self.journal.put_record(bucket, identity, record)
            self.journal.enqueue('', value, operation='observation', event_id=f'{kind}_{identity}')
        return record


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def __init__(self, *args, store, **kwargs):
        self.store = store
        super().__init__(*args, **kwargs)

    def send(self, status, data, content_type='application/json'):
        body = data if isinstance(data, bytes) else json.dumps(data, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def trusted(self):
        expected = f'127.0.0.1:{self.server.server_port}'
        return self.headers.get('Host') == expected and self.headers.get('Origin') in (None, 'http://' + expected)

    def do_GET(self):
        if not self.trusted():
            return self.send(403, {'error': 'Use the local cart origin'})
        if self.path == '/api/state':
            return self.send(200, self.store.snapshot())
        if self.path == '/':
            return self.send(200, Path(__file__).with_name('kiosk.html').read_bytes(), 'text/html; charset=utf-8')
        self.send(404, {'error': 'Unknown resource'})

    def do_POST(self):
        if not self.trusted() or self.headers.get('Content-Type') != 'application/json':
            return self.send(403, {'error': 'Same-origin JSON requests only'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 8192:
                raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Expected an object')
            if self.path == '/api/enroll':
                record = self.store.enroll(data)
            elif self.path == '/api/observation':
                record = self.store.observation(data)
            else:
                return self.send(404, {'error': 'Unknown resource'})
            self.send(200, {'savedLocally': True, 'record': record})
        except (ValueError, TypeError, KeyError) as error:
            self.send(400, {'error': str(error)})
        except Exception:
            self.send(503, {'error': 'Local persistence failed. Reading was not acknowledged; inspect the cart journal.'})

    def log_message(self, *_):
        pass  # Never log entered observations into HTTP access logs.


def server(journal, state, port=8765):
    result = ThreadingHTTPServer(('127.0.0.1', port), partial(Handler, store=KioskStore(journal, state)))
    result.daemon_threads = False
    return result
