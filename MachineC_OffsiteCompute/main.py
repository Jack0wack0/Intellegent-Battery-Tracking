"""Revision-keyed, durable Drive pipeline. A failed stage is retried on the next run."""
import csv
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import shutil
from artifacts import atomic_output, copy_verified, digest, safe_path
from drive_sync import get_service, get_folder_id_by_name, list_new_files, download_file
from DSConverter import convert_file
from filter_csv import process_csv
from parser import convert_events, event_records

log = logging.getLogger('ingestion')


def revision(file):
    key = json.dumps({k: file.get(k) for k in ('id', 'name', 'modifiedTime', 'md5Checksum', 'size')}, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()


class Pipeline:
    def __init__(self, staging, storage):
        self.staging, self.storage = Path(staging).resolve(), Path(storage).resolve()
        self.staging.mkdir(parents=True, exist_ok=True)
        # A missing configured backup mount must not be silently created on the system disk.
        if not self.storage.is_dir():
            raise OSError('Configured persistent storage is unavailable; create/mount it before ingestion')
        self.db = sqlite3.connect(self.staging / 'ingestion.sqlite3', timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS files(revision TEXT PRIMARY KEY, metadata TEXT NOT NULL, status TEXT NOT NULL, manifest TEXT)')

    def process(self, service, file):
        identity = revision(file)
        row = self.db.execute('SELECT status,manifest FROM files WHERE revision=?', (identity,)).fetchone()
        if row and row[0] == 'complete':
            manifest = json.loads(row[1])
            if all(safe_path(self.storage, name).is_file() and digest(safe_path(self.storage, name)) == checksum for name, checksum in manifest.items()):
                return identity
        self.db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?)', (identity, json.dumps(file), 'pending', None))
        self.db.commit()
        extension = '.dsevents' if file['name'].lower().endswith('.dsevents') else '.dslog'
        reserve = int(os.getenv('MIN_STORAGE_FREE_BYTES', '104857600'))
        required = max(reserve, int(file.get('size') or 0) * 8)
        if min(shutil.disk_usage(self.staging).free, shutil.disk_usage(self.storage).free) < required:
            raise OSError('Insufficient storage headroom; no raw history will be deleted automatically')
        raw = safe_path(self.staging, identity + extension)
        if not raw.exists() or (file.get('md5Checksum') and digest(raw, 'md5') != file['md5Checksum']):
            download_file(service, file['id'], raw, metadata=file)
        outputs = [raw]
        converted = safe_path(self.staging, identity + '.raw.csv')
        if extension == '.dslog':
            convert_file(raw, converted)
            derived = safe_path(self.staging, identity + '.derived.csv')
            process_csv(converted, derived)
            outputs += [converted, derived]
        else:
            convert_events(raw, converted)
            outputs += [converted]
        meta = safe_path(self.staging, identity + '.metadata.json')
        with atomic_output(meta) as f:
            json.dump({'source': file, 'revision': identity, 'formatVersion': 2}, f, sort_keys=True)
        outputs.append(meta)
        manifest = {}
        for source in outputs:
            target = safe_path(self.storage, source.name)
            copy_verified(source, target)
            manifest[source.name] = digest(target)
        # Commit completion only when every persistent artifact has been verified.
        self.db.execute('UPDATE files SET status=?,manifest=? WHERE revision=?', ('complete', json.dumps(manifest), identity))
        self.db.commit()
        # Persistent verified copies are authoritative; staging should not fill indefinitely.
        for source in outputs:
            source.unlink()
        return identity

    def bind(self, files):
        groups = {}
        for file in files:
            stem = file['name'].rsplit('.', 1)[0]
            groups.setdefault(stem, []).append(file)
        for stem, group in groups.items():
            logs = [f for f in group if f['name'].lower().endswith('.dslog')]
            events = [f for f in group if f['name'].lower().endswith('.dsevents')]
            binding = {'sourceStem': stem, 'status': 'unmatched', 'batteryId': None}
            if len(logs) == len(events) == 1:
                raw_event = safe_path(self.storage, revision(events[0]) + '.dsevents')
                if raw_event.exists():
                    records = list(event_records(raw_event))
                    tags = {r['battery_id'] for r in records if r['battery_id']}
                    ambiguous = any(r['binding_status'] == 'ambiguous' for r in records)
                    binding.update(status='identified' if len(tags) == 1 and not ambiguous else 'ambiguous' if tags or ambiguous else 'unmatched',
                                   batteryId=next(iter(tags)) if len(tags) == 1 and not ambiguous else None,
                                   dslogRevision=revision(logs[0]), dseventsRevision=revision(events[0]),
                                   events=records)
            elif len(logs) > 1 or len(events) > 1:
                binding['status'] = 'ambiguous'
            name = hashlib.sha256(stem.encode()).hexdigest() + '.binding.json'
            with atomic_output(safe_path(self.storage, name)) as f:
                json.dump(binding, f, sort_keys=True)

    def close(self):
        self.db.close()


def main():
    from dotenv import load_dotenv
    import fcntl
    load_dotenv()
    root = Path(__file__).resolve().parent
    staging = Path(os.getenv('INGESTION_STATE_PATH', str(root / 'state')))
    staging.mkdir(parents=True, exist_ok=True)
    # Avoid manual/timer concurrent writers, including conversion artifact replacement.
    with open(staging / 'pipeline.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another ingestion run is active')
        service = get_service()
        folder = os.getenv('DRIVE_FOLDER_ID') or get_folder_id_by_name(service, os.environ['DRIVE_FOLDER_NAME'])
        files = list_new_files(service, folder)
        pipeline = Pipeline(staging, os.environ['LOCAL_STORAGE_PATH'])
        failed = []
        try:
            for file in files:
                try:
                    pipeline.process(service, file)
                except Exception:
                    log.exception('Failed file revision %s; retained for retry', revision(file))
                    failed.append(file['id'])
            pipeline.bind(files)
        finally:
            pipeline.close()
        if failed:
            raise RuntimeError(f'{len(failed)} file revisions failed; retry next run')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
