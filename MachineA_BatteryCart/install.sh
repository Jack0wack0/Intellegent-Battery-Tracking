#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT=$(cd "$(dirname "$0")" && pwd)
TASK_USER=$(id -un)
[[ "$TASK_USER" != root ]] || { echo 'Run as the service user; sudo is used for system changes.'; exit 1; }
cd "$TASK_ROOT"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-dev gcc libevdev-dev
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ is required"'
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
venv/bin/python -m pip check
if [[ ! -f .env ]]; then
  read -r -p 'Firebase database URL: ' TASK_URL
  read -r -p 'Absolute service account JSON path: ' TASK_CREDS
  read -r -p 'Dedicated RFID /dev/input/by-id/*event-kbd paths (comma separated; scanners only): ' TASK_RFID
  read -r -p 'Arduino firmware protocol: legacy (no reflash) or v2 [legacy]: ' TASK_PROTOCOL
  TASK_PROTOCOL=${TASK_PROTOCOL:-legacy}
  [[ -n "$TASK_URL" && "$TASK_CREDS" == /* && -f "$TASK_CREDS" && -n "$TASK_RFID" ]] || exit 1
  umask 077
  printf 'FIREBASE_DB_BASE_URL=%s\nFIREBASE_CREDS_FILE=%s\nRFID_DEVICES=%s\nARDUINO_PROTOCOL=%s\nSLOT_COUNT=7\n' "$TASK_URL" "$TASK_CREDS" "$TASK_RFID" "$TASK_PROTOCOL" > .env
fi
if [[ ! -f hardwareIDS.json ]]; then
  read -r -p 'Board 1 stable /dev/serial/by-id path: ' TASK_PORT1
  read -r -p 'Board 2 stable /dev/serial/by-id path: ' TASK_PORT2
  venv/bin/python - "$TASK_PORT1" "$TASK_PORT2" <<'PY'
from pathlib import Path
import json, sys
ports={'COM_PORT1':sys.argv[1], 'COM_PORT2':sys.argv[2]}
if ports['COM_PORT1']==ports['COM_PORT2'] or not all(p.startswith('/dev/serial/by-id/') and Path(p).exists() for p in ports.values()):
    raise SystemExit('Two distinct connected stable serial paths are required')
Path('hardwareIDS.json').write_text(json.dumps(ports,indent=2)+'\n')
PY
fi
venv/bin/python - <<'PY'
from dotenv import dotenv_values
from pathlib import Path
import glob, json
c=dotenv_values('.env')
protocol=c.get('ARDUINO_PROTOCOL','v2')
if protocol not in ('legacy','v2'): raise SystemExit('ARDUINO_PROTOCOL must be legacy or v2')
if protocol=='legacy' and not 1 <= int(c.get('SLOT_COUNT','7')) <= 7:
    raise SystemExit('Legacy firmware requires SLOT_COUNT between 1 and 7')
for key in ('FIREBASE_DB_BASE_URL','FIREBASE_CREDS_FILE','RFID_DEVICES'):
    if not c.get(key): raise SystemExit(f'Missing {key} in .env')
if not Path(c['FIREBASE_CREDS_FILE']).is_file(): raise SystemExit('Credential file missing')
for pattern in c['RFID_DEVICES'].split(','):
    if not pattern.strip().startswith('/dev/input/by-id/') or not glob.glob(pattern.strip()):
        raise SystemExit('Each RFID path must match a connected dedicated input device')
ports=json.loads(Path('hardwareIDS.json').read_text())
if ports['COM_PORT1']==ports['COM_PORT2'] or not all(Path(p).exists() for p in ports.values()):
    raise SystemExit('Two distinct connected serial ports are required')
PY
# evdev access is required to the explicitly configured scanner paths; do not configure a general keyboard.
sudo usermod -a -G dialout,input "$TASK_USER"
mkdir -p state
if [[ -f firebase_queue.json && ! -f state/firebase_queue.json ]]; then cp firebase_queue.json state/firebase_queue.json; fi
chmod 600 .env
TASK_UNIT=$(mktemp)
trap 'rm -f "$TASK_UNIT"' EXIT
cat > "$TASK_UNIT" <<EOF
[Unit]
Description=Durable battery cart collection
After=local-fs.target

[Service]
Type=simple
User=$TASK_USER
SupplementaryGroups=dialout input
WorkingDirectory="$TASK_ROOT"
ExecStart="$TASK_ROOT/venv/bin/python3" "$TASK_ROOT/input_listener.py"
EnvironmentFile="$TASK_ROOT/.env"
Environment="STATE_DIRECTORY=$TASK_ROOT/state"
Restart=on-failure
RestartSec=5
TimeoutStopSec=20
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
sudo install -m 0644 "$TASK_UNIT" /etc/systemd/system/tagtracker.service
sudo systemctl daemon-reload
sudo systemctl enable --now tagtracker.service
sudo systemctl restart tagtracker.service
sleep 2
sudo systemctl is-active --quiet tagtracker.service
printf 'Cart service started. Verify RFID capture and both board snapshots in journalctl -u tagtracker.\n'
printf 'Verify the configured Arduino firmware protocol; legacy mode requires no reflash and uses manual battery selection.\n'
