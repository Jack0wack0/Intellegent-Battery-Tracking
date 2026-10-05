#!/usr/bin/env bash
# Explicit release update. No destructive reset or automatic update under running services.
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
TASK_STAGE=$(mktemp -d)
trap 'rm -rf "$TASK_STAGE"' EXIT
git archive "$TASK_AFTER" | tar -x -C "$TASK_STAGE"
python3 -m venv "$TASK_STAGE/venv"
"$TASK_STAGE/venv/bin/python" -m pip install -r "$TASK_STAGE/MachineC_OffsiteCompute/requirements.txt"
"$TASK_STAGE/venv/bin/python" -m pip check
"$TASK_STAGE/venv/bin/python" -m unittest discover -s "$TASK_STAGE/tests" -v
# Runtime unit migrations require install.sh explicitly; do not silently skip changed units.
if ! git diff --quiet "$TASK_BEFORE" "$TASK_AFTER" -- MachineC_OffsiteCompute/install.sh; then
  echo 'Unit/install migration changed: run a reviewed maintenance installation rather than automatic deploy.'
  exit 1
fi
sudo systemctl stop offsite-check.timer offsite-check.service offsite-scoring-engine.service offsite-firebase-scraper.service
rollback() {
  echo "Update failed; restoring $TASK_BEFORE and dependencies."
  git -c advice.detachedHead=false checkout --detach "$TASK_BEFORE"
  MachineC_OffsiteCompute/venv/bin/python -m pip install -r MachineC_OffsiteCompute/requirements.txt
  sudo systemctl start offsite-scoring-engine.service offsite-firebase-scraper.service offsite-check.timer
}
if ! git merge --ff-only "$TASK_AFTER" || ! MachineC_OffsiteCompute/venv/bin/python -m pip install -r MachineC_OffsiteCompute/requirements.txt; then
  rollback
  exit 1
fi
sudo systemctl start offsite-scoring-engine.service offsite-firebase-scraper.service offsite-check.timer
sleep 3
if ! sudo systemctl is-active --quiet offsite-scoring-engine.service || ! sudo systemctl is-active --quiet offsite-firebase-scraper.service; then
  rollback
  exit 1
fi
printf 'Running revision: %s. Verify deployed heartbeat/scoring/ingestion and retain previous revision %s.\n' "$TASK_AFTER" "$TASK_BEFORE"
