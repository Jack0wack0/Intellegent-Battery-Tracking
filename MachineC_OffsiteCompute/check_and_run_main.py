#!/usr/bin/env python3
"""Wrapper to run main.py only when there are new files in Google Drive.

This version runs indefinitely. It never sys.exit()s inside the loop.
"""

import os
import sys
import time
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
    
#testing if commit service is working on other machine. 


def read_exclusions(path):
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r") as f:
            return set(line.strip() for line in f if line.strip())
    except Exception:
        return set()


def main_loop():
    while True:
        print("\n[+] Checking Drive for new files...")

        # Authenticate each cycle (safe for long-running daemons)
        try:
            service = get_service()
        except Exception as e:
            print(f"[!] Could not authenticate to Google Drive: {e}")
            time.sleep(10)
            continue

        DRIVE_FOLDER_NAME = os.getenv("DRIVE_FOLDER_NAME", "DRIVER_STATION_LOGS")
        folder_id = get_folder_id_by_name(service, DRIVE_FOLDER_NAME)

        if not folder_id:
            print("[i] Drive folder not found; will retry...")
            time.sleep(10)
            continue

        files = list_new_files(service, folder_id)
        if not files:
            print("[i] No .dslog/.dsevents files in Drive folder.")
            time.sleep(10)
            continue

        exclusions = read_exclusions(EXCLUSION_FP)

        new_files = [
            f for f in files
            if f.get("name") and f.get("name") not in exclusions
        ]

        if not new_files:
            print("[i] No new files to process.")
            time.sleep(10)
            continue

        print(f"[+] Detected {len(new_files)} new file(s). Running main.py...")

        python = sys.executable or "/usr/bin/python3"
        try:
            subprocess.run([python, os.path.join(ROOT, "main.py")], check=False)
        except Exception as e:
            print(f"[!] Failed to run main.py: {e}")

        print("[+] Pipeline complete. Will check again soon.")
        time.sleep(10)  # Adjust polling interval


if __name__ == "__main__":
    main_loop()
