
import os
import time
import shutil
import subprocess
from drive_sync import get_service, list_new_files, download_file, get_folder_id_by_name
from dotenv import load_dotenv
from parser import parse_dsevents

load_dotenv()

# CONFIG
# You can set DRIVE_FOLDER_NAME in your .env (defaults to DRIVER_STATION_LOGS)
DRIVE_FOLDER_NAME = os.getenv('DRIVE_FOLDER_NAME', 'DRIVER_STATION_LOGS')
TEMP_DIR = "temp"
DSLOG_DIR = "csvDSLogs"  # Output dir for DSConverter
LOCAL_STORAGE = os.getenv('LOCAL_STORAGE_PATH', '/mnt/storage/csvlogs')  # Change to your local storage server path

def run_dsconverter(dslog_dir):
    # Run DSConverter.py to process all .dslog files in dslog_dir
    # Pass the directory where .dslog files were downloaded so DSConverter processes them
    subprocess.run(["python3", "DSConverter.py", dslog_dir], check=True)

def copy_and_verify(src, dst):
    shutil.copy2(src, dst)
    # Verify by comparing file sizes
    return os.path.getsize(src) == os.path.getsize(dst)

def filter_csv_inplace(csv_path):
    subprocess.run(["python3", "filter_csv.py", csv_path], check=True)

def main():
    service = get_service()
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(DSLOG_DIR, exist_ok=True)
    os.makedirs(LOCAL_STORAGE, exist_ok=True)

    # Resolve the folder ID from the folder name (user's Drive root)
    print(f"[+] Resolving Drive folder name: {DRIVE_FOLDER_NAME}")
    folder_id = get_folder_id_by_name(service, DRIVE_FOLDER_NAME)
    if not folder_id:
        print("[!] Could not find the Drive folder. Aborting.")
        return

    # Step 1: Download all .dslog and .dsevents files from Drive
    files = list_new_files(service, folder_id)
    for file in files:
        name = file['name']
        fid = file['id']
        local_path = os.path.join(TEMP_DIR, name)
        if not os.path.exists(local_path):
            print(f"[+] Downloading {name}...")
            download_file(service, fid, local_path)

    # Step 1b: Process any downloaded .dsevents files into CSVs so they get copied & filtered
    for fname in os.listdir(TEMP_DIR):
        if fname.endswith('.dsevents'):
            src = os.path.join(TEMP_DIR, fname)
            try:
                batt_id = parse_dsevents(src)
                out_name = fname.replace('.dsevents', '.dsevents.csv')
                out_path = os.path.join(DSLOG_DIR, out_name)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, 'w', newline='') as f:
                    f.write('source_file,battery_id\n')
                    # Quote fields if necessary
                    f.write(f'"{fname}","{batt_id}"\n')
                print(f"  └─ parsed dsevents -> {out_path}")
                # Add the original .dsevents filename to the exclusion list so it won't be reprocessed
                exclusion_fp = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'exclusionListFP.txt')
                try:
                    with open(exclusion_fp, 'a') as exf:
                        exf.write(fname + "\n")
                    print(f"  └─ added {fname} to exclusion list")
                except Exception as e:
                    print(f"[!] Failed to write to exclusion list: {e}")
            except Exception as e:
                print(f"[!] Failed to parse {fname}: {e}")

    # Step 2: Run DSConverter.py to convert all .dslog files to CSV
    run_dsconverter(TEMP_DIR)

    # Step 3: Copy and verify all CSVs to local storage
    for fname in os.listdir(DSLOG_DIR):
        if fname.endswith(".csv"):
            src = os.path.join(DSLOG_DIR, fname)
            dst = os.path.join(LOCAL_STORAGE, fname)
            print(f"[+] Copying {fname} to storage...")
            if copy_and_verify(src, dst):
                print(f"  └─ Verified {fname}")
            else:
                print(f"  └─ Verification failed for {fname}")

    # Step 4: Filter all CSVs in-place, but skip dsevents-derived CSVs
    for fname in os.listdir(DSLOG_DIR):
        if not fname.endswith(".csv"):
            continue
        # Skip files produced from .dsevents (we leave those unfiltered)
        if fname.endswith('.dsevents.csv'):
            print(f"[i] Skipping filtering for dsevents CSV: {fname}")
            continue
        csv_path = os.path.join(DSLOG_DIR, fname)
        print(f"[+] Filtering {fname}...")
        filter_csv_inplace(csv_path)
        print(f"  └─ Filtered {fname}")

    print("[✓] Pipeline complete.")

if __name__ == "__main__":
    main()
