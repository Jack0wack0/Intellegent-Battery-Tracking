#!/usr/bin/env python3
"""Wrapper to run main.py only when there are new files in Google Drive.

Checks the configured Drive folder for .dslog/.dsevents files and compares
the names against the local exclusion list used by DSConverter. If any
Drive file is not yet in the exclusion list, this script runs main.py.
"""
import os
import sys
import subprocess
from dotenv import load_dotenv

load_dotenv()

ROOT = os.path.dirname(os.path.realpath(__file__))
EXCLUSION_FP = os.path.join(ROOT, "exclusionListFP.txt")

try:
    from drive_sync import get_service, get_folder_id_by_name, list_new_files
except Exception as e:
    print(f"[!] Failed to import drive helpers: {e}")
    sys.exit(1)


def read_exclusions(path):
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r") as f:
            return set(line.strip() for line in f if line.strip())
    except Exception:
        return set()


def main():
    service = None
    try:
        service = get_service()
    except Exception as e:
        print(f"[!] Could not authenticate to Google Drive: {e}")
        sys.exit(1)

    DRIVE_FOLDER_NAME = os.getenv("DRIVE_FOLDER_NAME", "DRIVER_STATION_LOGS")
    folder_id = get_folder_id_by_name(service, DRIVE_FOLDER_NAME)
    if not folder_id:
        print("[i] Drive folder not found; nothing to do.")
        sys.exit(0)

    files = list_new_files(service, folder_id)
    if not files:
        print("[i] No .dslog/.dsevents files found in Drive folder.")
        sys.exit(0)

    exclusions = read_exclusions(EXCLUSION_FP)

    new_files = [f for f in files if f.get("name") and f.get("name") not in exclusions]

    if not new_files:
        print("[i] No new files to process (all files are in exclusion list).")
        sys.exit(0)

    print(f"[+] Detected {len(new_files)} new file(s). Running main.py...")
    python = sys.executable or "/usr/bin/python3"
    try:
        subprocess.run([python, os.path.join(ROOT, "main.py")], check=False)
    except Exception as e:
        print(f"[!] Failed to run main.py: {e}")


if __name__ == "__main__":
    main()
