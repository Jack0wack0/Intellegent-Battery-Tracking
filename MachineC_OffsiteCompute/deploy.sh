#!/bin/bash
set -e
cd /home/offsitecompute/Intellegent-Battery-Tracking

# Capture current commit
BEFORE=$(git rev-parse HEAD)

git fetch origin main
git reset --hard origin/main

AFTER=$(git rev-parse HEAD)

if [ "$BEFORE" != "$AFTER" ]; then
    echo "New commit detected: $BEFORE -> $AFTER, restarting services..."
    source MachineC_OffsiteCompute/venv/bin/activate
    pip install -r MachineC_OffsiteCompute/requirements.txt
    sudo systemctl restart offsite-firebase-scraper.service
    sudo systemctl restart offsite-check.service
    sudo systemctl restart offsite-scoring-engine.service
else
    echo "No changes."
fi