"""Streaming DS conversion with stable fields; incomplete logs never publish."""
import argparse
import csv
import json
from pathlib import Path
from artifacts import atomic_output
from dslogtocsvlibrary.dslogstream import DsLogStream

FIELDS = ['date', 'voltage', 'trip_time', 'packet_loss', 'rio', 'can', 'wifi', 'bandwidth',
          'pdp_id', 'pdp_type', 'pdp_data_currents', 'pdp_voltage', 'pdp_temperature',
          'brownout', 'watchdog', 'ds_teleop', 'ds_disabled', 'robot_teleop', 'robot_autonomous', 'robot_disabled']


def convert_file(source, destination):
    count = 0
    with open(source, 'rb') as input_file, atomic_output(destination, newline='') as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        for entry in DsLogStream(input_file):
            row = {field: getattr(entry, field, '') for field in FIELDS}
            row['date'] = entry.date.isoformat()
            row['pdp_type'] = entry.pdp_meta_data.type.name
            row['pdp_data_currents'] = json.dumps(entry.pdp_data.currents) if entry.pdp_data.currents else ''
            row['pdp_voltage'] = entry.pdp_data.voltage
            row['pdp_temperature'] = entry.pdp_data.temperature
            for field in ('brownout', 'watchdog', 'ds_teleop', 'ds_disabled', 'robot_teleop', 'robot_autonomous', 'robot_disabled'):
                row[field] = getattr(entry.status, field)
            writer.writerow(row)
            count += 1
        if count == 0:
            raise ValueError('DS log contains no complete records')
    return count


class DSConvertor:
    def __init__(self, dsLogDir, destinationDr=None):
        self.dsLogDir = Path(dsLogDir)
        self.destinationDr = Path(destinationDr or self.dsLogDir / 'converted')

    def processDSLogs(self):
        for source in sorted(self.dsLogDir.glob('*.dslog')):
            convert_file(source, self.destinationDr / (source.stem + '.csv'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory')
    parser.add_argument('--output')
    args = parser.parse_args()
    DSConvertor(args.directory, args.output).processDSLogs()
