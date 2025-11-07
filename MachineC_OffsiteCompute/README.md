# Offsite Compute — Drive sync & DSLog processing

This component downloads Drive logs (.dslog and .dsevents) from a Google Drive folder, converts them to CSV using the included DSConverter, filters CSVs, and copies results to a local storage path. It's intended to run on a Raspberry Pi or a small Linux VM.

## What it does

- Authenticates with Google Drive (OAuth) and lists files in a configured Drive folder.
- Downloads new `.dslog` and `.dsevents` files to `temp/`.
- Parses `.dsevents` files into a simple CSV entry so they are recorded.
- Runs `DSConverter.py` to convert `.dslog` files into structured CSVs saved in `csvDSLogs/`.
- Copies CSVs to a persistent storage location (configurable) and verifies the copy.
- Runs `filter_csv.py` on non-`dsevents` CSVs to clean/filter data in-place.

## Layout (important files)

- `main.py` — pipeline entrypoint. Orchestrates download -> convert -> copy -> filter.
- `drive_sync.py` — Google Drive helpers (auth, listing, download).
- `DSConverter.py` — converts `.dslog` files to CSV using `dslogtocsvlibrary`.
- `parser.py` — small helpers used for `.dsevents` parsing and DSLog parsing utilities.
- `filter_csv.py` — CSV post-processing script.
- `dslogtocsvlibrary/` — local library used by `DSConverter.py` to parse binary `.dslog` files.

## Prerequisites

- Linux (Raspberry Pi OS / Debian / Ubuntu) or any Linux VM.
- Python 3.8+ (3.10+ recommended on newer Pis/VMs).
- pip and virtualenv (recommended).
- Google OAuth client credentials JSON (created in Google Cloud Console) with Drive API enabled.

Python packages used (examples):
- google-api-python-client
- google-auth
- google-auth-oauthlib
- python-dotenv

This repository includes the `dslogtocsvlibrary` locally, so you don't need an external `dslogparser` package.

A `requirements.txt` is included in this folder. To install all required packages in one step run:

```bash
pip install -r requirements.txt
```

## Environment variables / .env

Create a `.env` file in this folder (or set environment variables system-wide) containing the following values:

```
GOOGLE_TOKEN_PATH=/creds/token.pickle
GOOGLE_CREDS_PATH=/creds/credentials.json
DRIVE_FOLDER_NAME="Folder name in google drive"
LOCAL_STORAGE_PATH=Backup location
TEST_DRIVE_FOLDER_ID=FOLDER_ID
```

Notes:
- `GOOGLE_CREDS_PATH` should point to the OAuth client credentials file you download (JSON) from the Google Cloud Console. Place it under a `creds/` subfolder or update the path.
- On first run the script will open a browser to perform the OAuth flow and create `GOOGLE_TOKEN_PATH` (token.pickle). On a headless Pi, use an SSH port-forward or run the flow on a local machine and copy the token file.

## Installation (recommended)

1. Create a Python virtual environment and activate it:

```bash
python3 -m venv venv
source venv/bin/activate
```

2. Install required packages (recommended):

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

If you prefer pinned versions, edit `requirements.txt` to include specific versions (e.g. `pkg==1.2.3`).

3. Place your Google OAuth `credentials.json` at the path you specified in `GOOGLE_CREDS_PATH` (e.g. `creds/credentials.json`).

4. Create the `.env` file in this folder (see the section above). Ensure `LOCAL_STORAGE_PATH` exists or change it to a valid path.

## First run and authentication

On first run the Drive helper (`drive_sync.get_service()`) will attempt to load `GOOGLE_TOKEN_PATH`. If not present it will start an OAuth flow and open a browser to let you grant access. The credentials will then be saved to the `GOOGLE_TOKEN_PATH` file.

On a headless machine (no GUI) you can either:
- Run the script on a machine with a browser to perform the flow and copy the resulting token file to the Pi/VM; or
- Temporarily enable X forwarding / run with `run_local_server` (it launches a local server and opens a browser on the host) and complete the auth via an externally accessible browser.

To run the pipeline manually:

```bash
source venv/bin/activate   # if using virtualenv
python3 main.py
```

## Running automatically (suggested)

You can run `main.py` as a cron job or systemd service. Example systemd unit (place in `/etc/systemd/system/offsite-compute.service`):

```
[Unit]
Description=Offsite DSLog processor
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/Intellegent-Battery-Tracking/MachineC_OffsiteCompute
ExecStart=/home/pi/Intellegent-Battery-Tracking/MachineC_OffsiteCompute/venv/bin/python3 main.py
Restart=on-failure
EnvironmentFile=/home/pi/Intellegent-Battery-Tracking/MachineC_OffsiteCompute/.env

[Install]
WantedBy=multi-user.target
```

Adjust the `User`, `WorkingDirectory`, `ExecStart`, and `EnvironmentFile` paths to match your setup.

## Output directories

- `temp/` — downloaded Drive files (`.dslog` and `.dsevents`) are placed here.
- `csvDSLogs/` — generated CSVs from `DSConverter.py` and `.dsevents`-derived CSV entries are saved here.
- `LOCAL_STORAGE_PATH` — persistent storage location you set (the README's `.env` example uses `/mnt/storage/csvlogs`).

## Troubleshooting

- Authentication errors: ensure `GOOGLE_CREDS_PATH` points to a valid OAuth client JSON and the Drive API is enabled in Google Cloud Console.
- Headless auth: perform the auth flow on a desktop and copy `token.pickle` to the Pi's `GOOGLE_TOKEN_PATH`.
- Permission errors when copying: ensure `LOCAL_STORAGE_PATH` is writable by the user running the script.
- DSLog parsing errors: `DSConverter.py` uses the local `dslogtocsvlibrary` to parse binary logs. If parsing fails, check the stack trace printed by `DSConverter.py` and the `exclusionListFP.txt` to see which files were skipped.

---
