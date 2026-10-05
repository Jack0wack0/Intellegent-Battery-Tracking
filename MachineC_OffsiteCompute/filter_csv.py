"""Preserve source columns, mark invalid values, and write a separate derived artifact."""
import ast
import csv
import math
from pathlib import Path
import sys
from artifacts import atomic_output


def finite(value, low, high):
    try:
        number = float(value)
        return number if math.isfinite(number) and low <= number <= high else None
    except (ValueError, TypeError):
        return None


def process_csv(input_path, output_path, *, voltage_min=0, voltage_max=16, channel_max=200):
    if Path(input_path).resolve() == Path(output_path).resolve():
        raise ValueError('Keep raw CSV immutable: choose a distinct derived output path')
    with open(input_path, newline='') as src, atomic_output(output_path, newline='') as dst:
        reader = csv.DictReader(src)
        fields = list(reader.fieldnames or [])
        for field in ('total_current', 'quality_flags', 'valid_voltage'):
            if field not in fields:
                fields.append(field)
        writer = csv.DictWriter(dst, fieldnames=fields)
        writer.writeheader()
        for row in reader:
            warnings = []
            voltage = finite(row.get('voltage'), voltage_min, voltage_max)
            row['valid_voltage'] = '' if voltage is None else voltage
            if voltage is None:
                warnings.append('invalid_voltage')
            raw = row.get('pdp_data_currents')
            if raw is None and row.get('total_current', '') != '':
                total = finite(row['total_current'], 0, 10000)
            else:
                try:
                    values = ast.literal_eval(raw or '')
                    if not isinstance(values, list) or not values or len(values) > 32:
                        raise ValueError('Missing currents')
                    currents = [finite(value, 0, channel_max) for value in values]
                    if any(value is None for value in currents):
                        raise ValueError('Invalid channel current')
                    total = sum(currents)
                except (ValueError, SyntaxError, TypeError):
                    total = None
            row['total_current'] = '' if total is None else total
            if total is None:
                warnings.append('unknown_current')
            row['quality_flags'] = ';'.join(warnings)
            writer.writerow(row)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: filter_csv.py raw.csv derived.csv (raw is never overwritten)')
    process_csv(sys.argv[1], sys.argv[2])
