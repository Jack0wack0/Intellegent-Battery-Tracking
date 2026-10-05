#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT=$(cd "$(dirname "$0")" && pwd)
TASK_USER=$(id -un)
[[ "$TASK_USER" != root ]] || { echo 'Run as the service user; sudo is used for system changes.'; exit 1; }
cd "$TASK_ROOT"
sudo apt-get update
sudo apt-get install -y python3 python3-venv git
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
venv/bin/python -m pip check
if [[ ! -f .env ]]; then
  umask 077
  cat > .env <<'EOF'
FIREBASE_DB_BASE_URL=
FIREBASE_CREDS_FILE=
GOOGLE_CREDS_PATH=creds/credentials.json
GOOGLE_TOKEN_PATH=creds/token.json
DRIVE_FOLDER_ID=
LOCAL_STORAGE_PATH=
EOF
  echo 'Fill .env before rerunning; authorize Drive with venv/bin/python drive_sync.py --authorize.'
  exit 1
fi
venv/bin/python - <<'PY'
from dotenv import dotenv_values
from pathlib import Path
c=dotenv_values('.env')
for k in ('FIREBASE_DB_BASE_URL','FIREBASE_CREDS_FILE','GOOGLE_CREDS_PATH','GOOGLE_TOKEN_PATH','LOCAL_STORAGE_PATH'):
    if not c.get(k): raise SystemExit(f'Missing {k}')
if not c.get('DRIVE_FOLDER_ID') and not c.get('DRIVE_FOLDER_NAME'): raise SystemExit('Configure DRIVE_FOLDER_ID')
for k in ('FIREBASE_CREDS_FILE','GOOGLE_CREDS_PATH','GOOGLE_TOKEN_PATH'):
    if not Path(c[k]).is_file(): raise SystemExit(f'{k} missing; authorize Drive first')
if c['GOOGLE_TOKEN_PATH'].endswith('.pickle'): raise SystemExit('Reauthorize to token.json; pickle is unsupported')
if not Path(c['LOCAL_STORAGE_PATH']).is_dir(): raise SystemExit('Persistent storage must be mounted/created before install')
PY
chmod 600 .env
mkdir -p state
TASK_UNITS=$(mktemp -d)
trap 'rm -rf "$TASK_UNITS"' EXIT
write_service() {
  local service_name=$1 module=$2
  cat > "$TASK_UNITS/$service_name.service" <<EOF
[Unit]
Description=$service_name
After=network-online.target
Wants=network-online.target

[Service]
User=$TASK_USER
WorkingDirectory="$TASK_ROOT"
ExecStart="$TASK_ROOT/venv/bin/python3" $module
EnvironmentFile="$TASK_ROOT/.env"
Restart=on-failure
RestartSec=10
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
}
write_service offsite-scoring-engine '-m battery_scoring.engine'
write_service offsite-firebase-scraper "\"$TASK_ROOT/FirebaseScraper.py\""
cat > "$TASK_UNITS/offsite-check.service" <<EOF
[Unit]
Description=One durable Drive ingestion pass
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$TASK_USER
WorkingDirectory="$TASK_ROOT"
ExecStart="$TASK_ROOT/venv/bin/python3" "$TASK_ROOT/check_and_run_main.py"
EnvironmentFile="$TASK_ROOT/.env"
TimeoutStartSec=30min
UMask=0077
NoNewPrivileges=true
EOF
cat > "$TASK_UNITS/offsite-check.timer" <<'EOF'
[Unit]
Description=Run Drive ingestion ten minutes after completion
[Timer]
OnBootSec=1min
OnUnitInactiveSec=10min
Persistent=true
[Install]
WantedBy=timers.target
EOF
# Retire the unsafe live-source auto-pull timer; updates are explicit validated releases.
sudo systemctl disable --now offsite-github-update.timer 2>/dev/null || true
for unit in "$TASK_UNITS"/*; do sudo install -m 0644 "$unit" /etc/systemd/system/; done
sudo systemctl daemon-reload
sudo systemctl enable --now offsite-scoring-engine.service offsite-firebase-scraper.service offsite-check.timer
sudo systemctl restart offsite-scoring-engine.service offsite-firebase-scraper.service
sleep 2
for service in offsite-scoring-engine.service offsite-firebase-scraper.service offsite-check.timer; do
  sudo systemctl is-active --quiet "$service"
done
printf 'Required services started. Verify health and first ingestion before release acceptance.\n'
