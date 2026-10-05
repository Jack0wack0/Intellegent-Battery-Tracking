#!/usr/bin/env bash
# Explicit release update; preserve exact previous source/dependencies for rollback.
set -euo pipefail
TASK_REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$TASK_REPO"
[[ -z $(git status --porcelain) ]] || { echo 'Checkout has local work; refusing deployment.'; exit 1; }
[[ $(git branch --show-current) == main ]] || { echo 'Deploy only from main.'; exit 1; }
mkdir -p MachineC_OffsiteCompute/state
exec 9>MachineC_OffsiteCompute/state/deploy.lock
flock -n 9 || { echo 'Another deployment is running.'; exit 1; }
git fetch origin main
TASK_BEFORE=$(git rev-parse HEAD)
TASK_AFTER=$(git rev-parse origin/main)
git merge-base --is-ancestor "$TASK_BEFORE" "$TASK_AFTER" || { echo 'Local commits diverge; refusing update.'; exit 1; }
[[ "$TASK_BEFORE" != "$TASK_AFTER" ]] || { echo 'Already current.'; exit 0; }
TASK_VENV_BACKUP="MachineC_OffsiteCompute/state/venv-before-$TASK_BEFORE"
[[ ! -e "$TASK_VENV_BACKUP" && -d MachineC_OffsiteCompute/venv ]] || { echo 'Inspect existing dependency backup/venv before deployment.'; exit 1; }
TASK_STAGE=$(mktemp -d)
TASK_STOPPED=0
TASK_MOVED=0
TASK_COMPLETE=0
rollback() {
  echo "Update failed; restoring $TASK_BEFORE and exact previous dependencies."
  git -c advice.detachedHead=false checkout --detach "$TASK_BEFORE"
  if [[ "$TASK_MOVED" == 1 ]]; then
    if [[ -d MachineC_OffsiteCompute/venv ]]; then
      mv MachineC_OffsiteCompute/venv "MachineC_OffsiteCompute/state/failed-venv-$TASK_AFTER-$(date +%s)"
    fi
    mv "$TASK_VENV_BACKUP" MachineC_OffsiteCompute/venv
  fi
  sudo systemctl start offsite-scoring-engine.service offsite-firebase-scraper.service offsite-check.timer
}
cleanup() {
  local task_exit=$?
  if [[ "$TASK_STOPPED" == 1 && "$TASK_COMPLETE" == 0 ]]; then rollback || true; fi
  rm -rf "$TASK_STAGE"
  return "$task_exit"
}
trap cleanup EXIT
git archive "$TASK_AFTER" | tar -x -C "$TASK_STAGE"
python3 -m venv "$TASK_STAGE/venv"
"$TASK_STAGE/venv/bin/python" -m pip install -r "$TASK_STAGE/MachineC_OffsiteCompute/requirements.txt"
"$TASK_STAGE/venv/bin/python" -m pip check
"$TASK_STAGE/venv/bin/python" -m unittest discover -s "$TASK_STAGE/tests" -v
if ! git diff --quiet "$TASK_BEFORE" "$TASK_AFTER" -- MachineC_OffsiteCompute/install.sh; then
  echo 'Unit/install migration changed: use a reviewed maintenance installation.'
  exit 1
fi
TASK_STOPPED=1
sudo systemctl stop offsite-check.timer offsite-check.service offsite-scoring-engine.service offsite-firebase-scraper.service
mv MachineC_OffsiteCompute/venv "$TASK_VENV_BACKUP"
TASK_MOVED=1
git merge --ff-only "$TASK_AFTER"
python3 -m venv MachineC_OffsiteCompute/venv
MachineC_OffsiteCompute/venv/bin/python -m pip install -r MachineC_OffsiteCompute/requirements.txt
MachineC_OffsiteCompute/venv/bin/python -m pip check
sudo systemctl start offsite-scoring-engine.service offsite-firebase-scraper.service offsite-check.timer
sleep 3
sudo systemctl is-active --quiet offsite-scoring-engine.service
sudo systemctl is-active --quiet offsite-firebase-scraper.service
TASK_COMPLETE=1
printf 'Running %s; verify deployed health. Exact rollback dependencies retained at %s.\n' "$TASK_AFTER" "$TASK_VENV_BACKUP"
