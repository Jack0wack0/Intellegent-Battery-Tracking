"""Binary DS events; retain provenance and never guess an ambiguous battery tag."""
import csv
import re
from artifacts import atomic_output
from dslogtocsvlibrary.dseventstream import DsEventStream

TAG_PATTERN = re.compile(r'\b(?:Battery(?:\s*(?:ID|Tag))?|BAT)\s*[:=]\s*(\d{10})\b', re.IGNORECASE)


def event_records(filepath):
    with open(filepath, 'rb') as source:
        for event in DsEventStream(source):
            message = event.raw_message
            tags = sorted(set(TAG_PATTERN.findall(message)))
            yield {'timestamp': event.date.isoformat(), 'message': message,
                   'battery_id': tags[0] if len(tags) == 1 else '',
                   'binding_status': 'identified' if len(tags) == 1 else 'ambiguous' if tags else 'unmatched'}


def parse_dsevents(filepath):
    tags = {row['battery_id'] for row in event_records(filepath) if row['battery_id']}
    return next(iter(tags)) if len(tags) == 1 else None


def convert_events(source, destination):
    with atomic_output(destination, newline='') as output:
        writer = csv.DictWriter(output, fieldnames=['timestamp', 'message', 'battery_id', 'binding_status'])
        writer.writeheader()
        writer.writerows(event_records(source))
