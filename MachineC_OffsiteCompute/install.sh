#!/usr/bin/env bash
set -euo pipefail

CURRENT_USER=$(whoami)
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_NAME="Intellegent-Battery-Tracking"
MACHINE_DIR="$ROOT_DIR"
VENV_DIR="$MACHINE_DIR/venv"

echo "[i] MachineC installer — setting up OffsiteCompute in: $MACHINE_DIR"

echo "[i] Updating system packages..."
sudo apt-get update -y
sudo apt-get upgrade -y

echo "[i] Installing prerequisites..."
sudo apt-get install -y python3 python3-venv python3-pip curl git || true

echo "[i] Creating Python virtualenv at $VENV_DIR (if missing)"
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

echo "[i] Activating venv and installing Python requirements..."
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"
if [ -f "$MACHINE_DIR/requirements.txt" ]; then
  pip install --upgrade pip
  pip install -r "$MACHINE_DIR/requirements.txt"
else
  pip install --upgrade pip
  pip install google-api-python-client google-auth google-auth-oauthlib python-dotenv
fi

deactivate || true

echo "[i] Ensuring credentials folder exists"
mkdir -p "$MACHINE_DIR/creds"

if [ ! -f "$MACHINE_DIR/.env" ]; then
  echo "[i] No .env found in $MACHINE_DIR — creating a minimal template"
  cat > "$MACHINE_DIR/.env" <<EOF
# Example .env values (fill these in)
GOOGLE_CREDS_PATH=creds/credentials.json
GOOGLE_TOKEN_PATH=creds/token.pickle
DRIVE_FOLDER_NAME=DRIVER_STATION_LOGS
LOCAL_STORAGE_PATH=/mnt/storage/csvlogs
FIREBASE_DB_BASE_URL=
FIREBASE_CREDS_FILE=
EOF
  echo "[i] Created $MACHINE_DIR/.env"
else
  echo "[i] .env already present — leaving it in place"
fi

set_env_value() {
  local key="$1"
  local value="$2"
  local temp_env

  temp_env=$(mktemp "$MACHINE_DIR/.env.XXXXXX")
  grep -v "^${key}=" "$MACHINE_DIR/.env" > "$temp_env" || true
  printf '%s=%s\n' "$key" "$value" >> "$temp_env"
  mv "$temp_env" "$MACHINE_DIR/.env"
}

if ! grep -q '^FIREBASE_DB_BASE_URL=.' "$MACHINE_DIR/.env"; then
  read -r -p "Enter your Firebase Realtime Database URL: " FIREBASE_DB_BASE_URL
  if [ -z "$FIREBASE_DB_BASE_URL" ]; then
    echo "[!] A Firebase Realtime Database URL is required."
    exit 1
  fi
  set_env_value "FIREBASE_DB_BASE_URL" "$FIREBASE_DB_BASE_URL"
fi

if ! grep -q '^FIREBASE_CREDS_FILE=.' "$MACHINE_DIR/.env"; then
  read -r -p "Enter the absolute path to your Firebase service account JSON file: " FIREBASE_CREDS_FILE
  if [ -z "$FIREBASE_CREDS_FILE" ] || [ ! -f "$FIREBASE_CREDS_FILE" ] || [[ "$FIREBASE_CREDS_FILE" != /* ]]; then
    echo "[!] An existing absolute Firebase credential-file path is required."
    exit 1
  fi
  set_env_value "FIREBASE_CREDS_FILE" "$FIREBASE_CREDS_FILE"
fi

echo "\n[i] Tailscale installation (optional network access)"
read -p "Install Tailscale now? [y/N]: " install_tailscale
if [[ "$install_tailscale" =~ ^([yY][eE][sS]|[yY])$ ]]; then
  echo "[i] Installing Tailscale..."
  # official quick-install script
  curl -fsSL https://tailscale.com/install.sh | sudo sh

  read -p "If you have a Tailscale auth key and want to automatically connect (optional), paste it now (or press Enter to skip): " TS_AUTHKEY
  if [ -n "$TS_AUTHKEY" ]; then
    echo "[i] Bringing up Tailscale with provided auth key..."
    sudo tailscale up --authkey "$TS_AUTHKEY" || true
  else
    echo "[i] Tailscale installed. Run 'sudo tailscale up' as needed to authenticate this node."
  fi
else
  echo "[i] Skipping Tailscale installation. You can install it later with: curl -fsSL https://tailscale.com/install.sh | sudo sh"
fi

echo "\n[i] Creating systemd service for FirebaseScraper (long-running)"
SERVICE_FILE=/etc/systemd/system/offsite-firebase-scraper.service
if [ ! -f "$SERVICE_FILE" ]; then
  sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=Offsite Firebase Scraper
After=network.target

[Service]
User=$CURRENT_USER
WorkingDirectory=$MACHINE_DIR
ExecStart=$VENV_DIR/bin/python3 $MACHINE_DIR/FirebaseScraper.py
Restart=on-failure
EnvironmentFile=$MACHINE_DIR/.env

[Install]
WantedBy=multi-user.target
EOF
  echo "[i] Created $SERVICE_FILE"
else
  echo "[i] $SERVICE_FILE already exists — skipping creation"
fi

echo "[i] Creating systemd service and timer to check Drive and run main.py only when new files exist"
CHECK_SERVICE=/etc/systemd/system/offsite-check.service
CHECK_TIMER=/etc/systemd/system/offsite-check.timer

if [ ! -f "$CHECK_SERVICE" ]; then
  sudo bash -c "cat > $CHECK_SERVICE" <<EOF
[Unit]
Description=Offsite Compute - check Drive and run main.py if new files exist
After=network-online.target

[Service]
Type=oneshot
User=$CURRENT_USER
WorkingDirectory=$MACHINE_DIR
ExecStart=$VENV_DIR/bin/python3 $MACHINE_DIR/check_and_run_main.py
EnvironmentFile=$MACHINE_DIR/.env

[Install]
WantedBy=multi-user.target
EOF
  echo "[i] Created $CHECK_SERVICE"
else
  echo "[i] $CHECK_SERVICE already exists — skipping"
fi

if [ ! -f "$CHECK_TIMER" ]; then
  sudo bash -c "cat > $CHECK_TIMER" <<EOF
[Unit]
Description=Run offsite-check.service every 10 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=10min
Persistent=true

[Install]
WantedBy=timers.target
EOF
  echo "[i] Created $CHECK_TIMER"
else
  echo "[i] $CHECK_TIMER already exists — skipping"
fi

echo "[i] Creating systemd service and timer to update from GitHub"
GITHUB_UPDATE_SERVICE=/etc/systemd/system/offsite-github-update.service
GITHUB_UPDATE_TIMER=/etc/systemd/system/offsite-github-update.timer

if [ ! -f "$GITHUB_UPDATE_SERVICE" ]; then
  sudo bash -c "cat > $GITHUB_UPDATE_SERVICE" <<EOF
[Unit]
Description=Update Offsite Compute checkout from GitHub
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$CURRENT_USER
WorkingDirectory=$MACHINE_DIR
ExecStart=/usr/bin/git -C $MACHINE_DIR pull --ff-only
EOF
  echo "[i] Created $GITHUB_UPDATE_SERVICE"
else
  echo "[i] $GITHUB_UPDATE_SERVICE already exists — skipping"
fi

if [ ! -f "$GITHUB_UPDATE_TIMER" ]; then
  sudo bash -c "cat > $GITHUB_UPDATE_TIMER" <<EOF
[Unit]
Description=Check GitHub for Offsite Compute updates every 30 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
EOF
  echo "[i] Created $GITHUB_UPDATE_TIMER"
else
  echo "[i] $GITHUB_UPDATE_TIMER already exists — skipping"
fi

echo "[i] Creating systemd service for the battery scoring engine (long-running)"
SCORING_SERVICE_FILE=/etc/systemd/system/offsite-scoring-engine.service
if [ ! -f "$SCORING_SERVICE_FILE" ]; then
  sudo bash -c "cat > $SCORING_SERVICE_FILE" <<EOF
[Unit]
Description=Offsite Battery Health & Match Scoring Engine
After=network.target

[Service]
User=$CURRENT_USER
WorkingDirectory=$MACHINE_DIR
ExecStart=$VENV_DIR/bin/python3 -m battery_scoring.engine
Restart=on-failure
EnvironmentFile=$MACHINE_DIR/.env

[Install]
WantedBy=multi-user.target
EOF
  echo "[i] Created $SCORING_SERVICE_FILE"
else
  echo "[i] $SCORING_SERVICE_FILE already exists — skipping creation"
fi

echo "[i] Reloading systemd daemon and enabling services/timers"
sudo systemctl daemon-reload
sudo systemctl enable --now offsite-firebase-scraper.service || true
sudo systemctl enable --now offsite-scoring-engine.service || true
sudo systemctl enable --now offsite-check.timer || true
sudo systemctl enable --now offsite-github-update.timer || true

echo "[✓] Installation complete."
echo "[i] Check service logs with: sudo journalctl -u offsite-firebase-scraper.service -f"
echo "[i] Check timer status with: systemctl list-timers --all | grep offsite-check"
echo "[i] Check GitHub update logs with: sudo journalctl -u offsite-github-update.service -f"

echo "[i] If you did not provide a Tailscale auth key and want remote access, run: sudo tailscale up and follow the interactive flow."
