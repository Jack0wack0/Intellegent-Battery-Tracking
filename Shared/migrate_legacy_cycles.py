#!/usr/bin/env python3
"""Prepare an additive legacy-cycle migration. Applying requires an explicit --apply."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo


def timestamp(value, local_timezone):
    if not isinstance(value, str):
        raise ValueError('Missing timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        if not local_timezone:
            raise ValueError('Legacy local timestamp needs an explicitly selected timezone')
        zone = ZoneInfo(local_timezone)
        if parsed.replace(tzinfo=zone, fold=0).utcoffset() != parsed.replace(tzinfo=zone, fold=1).utcoffset():
            raise ValueError('Ambiguous/nonexistent DST timestamp: correct the export with an explicit UTC offset')
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(timezone.utc).isoformat(timespec='milliseconds')


def plan(export, local_timezone=None):
    patch, warnings = {}, []
    existing = export.get('Cycles') or {}
    signatures = set()
    for value in existing.values():
        try:
            signatures.add((value['batteryId'], timestamp(value['startTime'], local_timezone), timestamp(value['endTime'], local_timezone)))
        except (ValueError, KeyError, TypeError):
            continue
    for tag, battery in (export.get('BatteryList') or {}).items():
        if not tag.isdigit() or len(tag) != 10 or not isinstance(battery, dict):
            continue
        records = battery.get('ChargingRecords') or {}
        records = dict(enumerate(records)) if isinstance(records, list) else records
        if not isinstance(records, dict):
            warnings.append(f'{tag}: invalid legacy history shape')
            continue
        for key, raw in records.items():
            try:
                if not isinstance(raw, dict) or not raw.get('EndTime'):
                    continue  # Open/incomplete history is retained, never invented as completed.
                start, end = timestamp(raw.get('StartTime'), local_timezone), timestamp(raw['EndTime'], local_timezone)
                if end < start:
                    raise ValueError('End time precedes start time')
                signature = (tag, start, end)
                if signature in signatures:
                    continue
                identity = 'legacy_' + hashlib.sha256(json.dumps([tag, str(key), start, end]).encode()).hexdigest()[:32]
                values = {'batteryId': tag, 'season': end[:4], 'startTime': start, 'endTime': end,
                          'completed': True, 'legacyImported': True,
                          'legacySource': f'BatteryList/{tag}/ChargingRecords/{key}'}
                if raw.get('ChargingSlot') is not None:
                    values['slot'] = raw['ChargingSlot']
                for field, value in values.items():
                    patch[f'Cycles/{identity}/{field}'] = value
                patch[f'ScoringRevisions/{tag}'] = {'.sv': {'increment': 1}}
                signatures.add(signature)
            except (ValueError, TypeError, OverflowError) as error:
                warnings.append(f'{tag}/{key}: {error}')
    return patch, warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export_file', help='Private RTDB backup/export; never commit it')
    parser.add_argument('--timezone', help='Explicit timezone for legacy naive timestamps, e.g. America/Chicago')
    parser.add_argument('--out', required=True, help='Private reviewable migration plan JSON')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    exported = json.loads(Path(args.export_file).read_text())
    patch, warnings = plan(exported, args.timezone)
    Path(args.out).write_text(json.dumps({'updates': patch, 'warnings': warnings}, indent=2) + '\n')
    print(f'Prepared {len(patch)} additive field updates; {len(warnings)} observations require inspection.')
    if args.apply:
        if warnings:
            raise SystemExit('Resolve/inspect migration warnings before applying; no writes made')
        import firebase_admin
        from firebase_admin import credentials, db
        firebase_admin.initialize_app(credentials.Certificate(os.environ['FIREBASE_CREDS_FILE']),
                                      {'databaseURL': os.environ['FIREBASE_DB_BASE_URL'], 'httpTimeout': 10})
        root = db.reference('/')
        # Revalidate against current canonical cycles; keep source history immutable.
        current = {**exported, 'Cycles': root.child('Cycles').get() or {}}
        patch, warnings = plan(current, args.timezone)
        if patch:
            root.update(patch)
        print('Additive migration applied; original history remains unchanged.')


if __name__ == '__main__':
    main()
