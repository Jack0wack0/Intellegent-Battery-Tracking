# Intelligent Battery Tracking

**Install this release:** [Changes and detailed installation guide](Shared/INSTALL_COMPETITION_RELEASE.md)
(Pi, both Arduino boards, offsite services, website/rules, backups and verification).

Competition hardening is on `fix/competition-readiness`, with the matching BatteryTrackingWebsite
release. Read [Shared/competition_release.md](Shared/competition_release.md) for the coordinated
migration, validated checks and required physical/deployed sign-off. The historical audit remains
under `audit/`; its failures describe the pre-fix source revision.

Intellegent-Battery-Tracking — high-level overview

This repository collects the pieces for an intelligent battery tracking system. The project is split into three machine-focused components to make deployment and maintenance easier:

- MachineA_BatteryCart — Raspberry Pi service that listens to Arduino serial messages and RFID scans, updates Firebase, and controls LEDs. See `MachineA_BatteryCart/README.md` for full setup.
- MachineB_ArduinoCode — Two Arduino sketches (LED + slot sensing and a second slot-sensor board). See `MachineB_ArduinoCode/README.md` for upload and wiring notes.
- MachineC_OffsiteCompute — Offsite/VM pipeline that syncs `.dslog` and `.dsevents` from Google Drive, converts DS logs to CSV, filters them, and stores results. See `MachineC_OffsiteCompute/README.md` for install and run instructions.

This top-level README is a short orientation; each machine folder contains a more detailed README with step-by-step install and configuration.

Quick checkout (sparse) — clone only the parts you need

```bash
# Clone the repo without checking out files
git clone --no-checkout https://github.com/Jack0wack0/Intellegent-Battery-Tracking.git
cd Intellegent-Battery-Tracking

# Initialize sparse checkout and choose folders you want. Example: pull MachineA and Shared
git sparse-checkout init --cone
git sparse-checkout set MachineA_BatteryCart Shared

# Download the specified folders from the main branch
git checkout main
```

Quick pointers
- Each machine folder contains a README, and most have an `install.sh` or instructions for environment variables.
- `MachineA_BatteryCart/install.sh` helps configure the Pi (including creating a `.env` during install and detecting Arduino serial IDs).
- `MachineC_OffsiteCompute` includes `requirements.txt` and a `README.md` describing Google Drive auth and an example `systemd` unit.

Contributing / support
- For code changes, open a PR against `main` and add a short description of the change.
- For deployment questions or troubleshooting, check the machine-level README first. If you still need help, open an issue describing which machine and what logs/config you have.

License
- See the project `LICENSE` files in the folders for licensing details.

Enjoy — use the per-machine READMEs for detailed setup steps and troubleshooting.
