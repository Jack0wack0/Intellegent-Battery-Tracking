import csv
import ast
import sys

# Usage: python filter_csv.py input.csv output.csv

def process_csv(input_path, output_path):
    # Read and filter data into memory
    filtered_rows = []
    with open(input_path, 'r', newline='') as infile:
        reader = csv.DictReader(infile)
        for row in reader:
            date = row.get('date', '')
            voltage = row.get('voltage', '')
            currents_str = row.get('pdp_data_currents', '[]')
            try:
                currents = ast.literal_eval(currents_str)
                if isinstance(currents, list):
                    total_current = sum(currents)
                else:
                    total_current = 0.0
            except Exception:
                total_current = 0.0
            filtered_rows.append({
                'date': date,
                'voltage': voltage,
                'total_current': total_current
            })
    # Overwrite the input file with filtered data
    fieldnames = ['date', 'voltage', 'total_current']
    with open(input_path, 'w', newline='') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(filtered_rows)

if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print("Usage: python filter_csv.py input.csv [output.csv]\nIf output.csv is omitted, input.csv will be overwritten.")
    else:
        input_path = sys.argv[1]
        if len(sys.argv) == 3:
            output_path = sys.argv[2]
            process_csv(input_path, output_path)
        else:
            process_csv(input_path, input_path)
