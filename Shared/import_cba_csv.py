"""Reviewed CBA CSV interchange import; dry-run by default, immutable content IDs.
Vendor exports must be explicitly mapped to this schema, never inferred from position.
"""
import argparse
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re


def plan(path):
    path = Path(path)
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    updates = {}
    with path.open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        if not {'battery_id','timestamp','capacity_ah','season'} <= set(reader.fieldnames or []):
            raise ValueError('Required columns: battery_id,timestamp,capacity_ah,season; optional notes')
        for number, row in enumerate(reader, 2):
            try:
                tag, season = row['battery_id'], row['season']
                timestamp = datetime.fromisoformat(row['timestamp'].replace('Z','+00:00'))
                capacity = float(row['capacity_ah'])
                if not re.fullmatch(r'\d{10}',tag) or not re.fullmatch(r'\d{4}',season):
                    raise ValueError('Invalid battery ID or season')
                if timestamp.tzinfo is None or not math.isfinite(capacity) or not 0 < capacity <= 100:
                    raise ValueError('Explicit timestamp offset and capacity in (0,100] Ah required')
                notes = row.get('notes') or None
                if notes and len(notes) > 1000: raise ValueError('Notes exceed 1000 characters')
                record={'timestamp':timestamp.isoformat(),'capacityAh':capacity,'season':season,'notes':notes}
                identity='csv_'+hashlib.sha256(json.dumps([tag,record],sort_keys=True).encode()).hexdigest()[:32]
                updates[f'CBATests/{tag}/{identity}']={**record,'source':{'sha256':source_hash,'filename':path.name,'row':number},'recordedBy':'reviewed-csv-import'}
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError(f'Row {number}: {error}') from error
    if not updates: raise ValueError('CSV contains no observations')
    return updates


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv'); parser.add_argument('--out',required=True); parser.add_argument('--apply',action='store_true')
    args=parser.parse_args(); updates=plan(args.csv)
    Path(args.out).write_text(json.dumps(updates,indent=2,allow_nan=False)+'\n')
    if args.apply:
        import os
        import firebase_admin
        from firebase_admin import credentials, db
        firebase_admin.initialize_app(credentials.Certificate(os.environ['FIREBASE_CREDS_FILE']),{'databaseURL':os.environ['FIREBASE_DB_BASE_URL']})
        root=db.reference('/')
        tags={path.split('/')[1] for path in updates}
        for tag in tags:
            battery=root.child('Batteries/'+tag).get()
            if not isinstance(battery,dict) or not all(battery.get(k) for k in ('id','name','brand','purchaseDate')):
                raise ValueError('Complete enrollment before import: '+tag)
        for path, record in updates.items():
            root.child(path).transaction(lambda existing: existing if existing is not None else record)
        for tag in tags: root.child('ScoringRevisions/'+tag).transaction(lambda value:(value or 0)+1)
    print(f'{len(updates)} distinct CBA observations planned; '+('applied additively.' if args.apply else 'no cloud writes.'))


if __name__=='__main__': main()
