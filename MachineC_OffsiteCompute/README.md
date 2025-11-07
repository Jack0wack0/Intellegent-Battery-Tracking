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

There is an installer script that handles the common setup tasks: creating a virtualenv, installing Python dependencies (from `requirements.txt`), creating a minimal `.env` template, optionally installing Tailscale, and creating systemd units to run the services automatically.

Run the installer:

```bash
cd MachineC_OffsiteCompute
chmod +x install.sh
./install.sh
```

What the installer does
- Creates a virtualenv at `MachineC_OffsiteCompute/venv` and installs packages from `requirements.txt` (or falls back to a reasonable default set).
- Creates a minimal `.env` template in the MachineC folder if you don't already have one; edit it with the paths and values for `GOOGLE_CREDS_PATH`, `GOOGLE_TOKEN_PATH`, `DRIVE_FOLDER_NAME`, and `LOCAL_STORAGE_PATH`.
- Optionally installs Tailscale and can bring it up with an auth key if you provide one during the installer prompt.
- Creates and enables these systemd units:
	- `offsite-firebase-scraper.service` — long-running service that runs `FirebaseScraper.py` continuously.
	- `offsite-check.service` — a oneshot service that runs `check_and_run_main.py` (the wrapper that only runs `main.py` when new Drive files are detected).
	- `offsite-check.timer` — a systemd timer that triggers `offsite-check.service` every 10 minutes and once shortly after boot.

Manual alternative
If you prefer not to run the installer, you can still set things up manually:

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
# create creds/ and place your credentials.json per .env variables
```

Then run the components manually as needed (see sections below).

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

If you used `install.sh`, the installer created a venv at `venv/`. To test the Drive-check wrapper without waiting for the timer, run:

```bash
source venv/bin/activate
python3 check_and_run_main.py
```

That will authenticate if necessary and only run `main.py` when there are Drive files that are not yet in `exclusionListFP.txt`.

## Running automatically (suggested)

We provide an installer which creates systemd units for two purposes:

- `offsite-firebase-scraper.service` — runs `FirebaseScraper.py` continuously as a service.
- `offsite-check.service` + `offsite-check.timer` — the timer triggers every 10 minutes (and once shortly after boot) to run `check_and_run_main.py`. The wrapper checks Drive for new `.dslog`/`.dsevents` files and runs `main.py` only when new files are found (i.e. files not already listed in `exclusionListFP.txt`).

If you prefer a single long-running service for `main.py` instead of a timer, you can create your own systemd unit similar to the example below and enable it instead of the timer:

```
[Unit]
Description=Offsite DSLog processor (manual long-running)
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

Adjust `User`, `WorkingDirectory`, and `ExecStart` to match your installation paths.

## Output directories

- `temp/` — downloaded Drive files (`.dslog` and `.dsevents`) are placed here.
- `csvDSLogs/` — generated CSVs from `DSConverter.py` and `.dsevents`-derived CSV entries are saved here.
- `LOCAL_STORAGE_PATH` — persistent storage location you set (the README's `.env` example uses `/mnt/storage/csvlogs`).

## Troubleshooting

- Authentication errors: ensure `GOOGLE_CREDS_PATH` points to a valid OAuth client JSON and the Drive API is enabled in Google Cloud Console.
- Headless auth: perform the auth flow on a desktop and copy `token.pickle` to the Pi's `GOOGLE_TOKEN_PATH`.
- Permission errors when copying: ensure `LOCAL_STORAGE_PATH` is writable by the user running the script.
- DSLog parsing errors: `DSConverter.py` uses the local `dslogtocsvlibrary` to parse binary logs. If parsing fails, check the stack trace printed by `DSConverter.py` and the `exclusionListFP.txt` to see which files were skipped.

Service & timer troubleshooting
- Check the FirebaseScraper logs:
	- `sudo journalctl -u offsite-firebase-scraper.service -f`
- Check the check service logs (oneshot runs):
	- `sudo journalctl -u offsite-check.service --since "1 hour ago"`
- Timer status:
	- `systemctl list-timers --all | grep offsite-check`

If you need to run the Drive-check manually (for testing):

```bash
source venv/bin/activate
python3 check_and_run_main.py
```

---
