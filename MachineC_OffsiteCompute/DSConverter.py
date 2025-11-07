from dslogtocsvlibrary.dslogstream import DsLogStream
from pathlib import Path
import os
import csv
import sys


class DSConvertor:
    def __init__(self, dsLogDir=""):
        self.dsLogDir = dsLogDir
        self.destinationDr = os.path.join(
            os.path.dirname(os.path.realpath(__file__)), "csvDSLogs"
        )
        self.exclusionListFP = os.path.join(
            os.path.dirname(os.path.realpath(__file__)), "exclusionListFP.txt"
        )

        # Ensure output directory exists
        os.makedirs(self.destinationDr, exist_ok=True)

        # Ensure exclusion file exists
        if not os.path.exists(self.exclusionListFP):
            Path(self.exclusionListFP).touch()

    def processDSLogs(self):
        for file in os.listdir(self.dsLogDir):
            file_path = os.path.join(self.dsLogDir, file)

            # Only process .dslog files not already excluded
            with open(self.exclusionListFP, "r") as exF:
                exclusions = exF.read().splitlines()

            if file.endswith(".dslog") and file not in exclusions:
                print(f"[*] Processing {file}...")

                try:
                    records = []
                    # Open DS log in binary mode
                    with open(file_path, "rb") as f:
                        log_stream = DsLogStream(f)
                        for entry in log_stream:
                            rec = entry.__dict__.copy()  # shallow copy

                            # Flatten pdp_meta_data
                            if hasattr(entry, "pdp_meta_data") and entry.pdp_meta_data is not None:
                                for k, v in entry.pdp_meta_data.__dict__.items():
                                    rec[f"pdp_meta_{k}"] = v
                                rec.pop("pdp_meta_data")

                            # Flatten pdp_data
                            if hasattr(entry, "pdp_data") and entry.pdp_data is not None:
                                for k, v in entry.pdp_data.__dict__.items():
                                    rec[f"pdp_data_{k}"] = v
                                rec.pop("pdp_data")

                            records.append(rec)

                    if not records:
                        print(f"[!] No records found in {file}")
                        continue

                    # Prepare CSV file
                    csv_filename = file[:-6] + ".csv"
                    csv_path = os.path.join(self.destinationDr, csv_filename)

                    # Use fieldnames from the first record
                    fieldnames = list(records[0].keys())

                    with open(csv_path, "w", newline="") as csvfile:
                        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(records)

                    print(f"[+] Wrote {csv_filename} with {len(records)} records.")
                    self.addToExclusionList(file)

                except Exception as e:
                    import traceback
                    print(f"[!] Failed to process {file}: {e}")
                    print("[!] Full traceback:")
                    traceback.print_exc()

    def addToExclusionList(self, fileName=""):
        with open(self.exclusionListFP, "a") as f:
            f.write(fileName + "\n")


def _main():
    # Allow passing the directory to process as the first CLI argument.
    # If omitted, fall back to the hard-coded path for backward compatibility.
    default_dir = r"/Users/jacksonyoes/Downloads/dslogs"
    dslogdir = sys.argv[1] if len(sys.argv) > 1 else default_dir
    dsconv = DSConvertor(dslogdir)
    dsconv.processDSLogs()


if __name__ == "__main__":
    _main()
