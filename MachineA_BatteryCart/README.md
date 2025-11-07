# Battery Tracking System - Machine A (Battery Cart)

This component is part of an intelligent battery tracking system designed to monitor and manage battery charging stations. It runs on a Raspberry Pi and interfaces with Arduino-based RFID readers and LED indicators.

## Features

- Real-time battery tracking with RFID identification
- LED status indicators for each charging slot
- Firebase integration for data storage and synchronization
- Automatic charge time tracking
- Smart slot management with next-up recommendations
- System health monitoring and status updates

## Prerequisites

- Raspberry Pi (I have gotten this to run on a pi 3B, but I would recommend a pi4 or better.)
- 2x Arduino UNO boards
- Addressable LED strip for status indication
- Firebase project with Realtime Database
- Python 3.x

## Installation

1. Clone this repository to your Raspberry Pi using sparse checkout (this downloads only the necessary components):
   ```bash
   # Clone the repository without downloading files yet
   git clone --no-checkout https://github.com/Jack0wack0/Intellegent-Battery-Tracking.git
   
   # Move into the repository directory
   cd Intellegent-Battery-Tracking
   
   # Set up sparse checkout to only download required folders
   git sparse-checkout init --cone
   git sparse-checkout set MachineA_BatteryCart Shared
   
   # Download the specified folders
   git checkout main
   ```

2. Firebase credentials and `.env` file

   The included `install.sh` script will prompt you for the Firebase Realtime Database URL and the full path to your Firebase service account JSON file, and it will create a `.env` file for you in the project directory during installation.

   If you prefer to create the `.env` file manually, create a file named `.env` in the project directory with the following contents (replace the placeholders):

   ```bash
   FIREBASE_DB_BASE_URL=https://your-project.firebaseio.com
   FIREBASE_CREDS_FILE=/absolute/path/to/your/firebase-credentials.json
   ```

   Notes:
   - `FIREBASE_DB_BASE_URL` should be your Firebase Realtime Database URL (for example: `https://your-project.firebaseio.com`).
   - `FIREBASE_CREDS_FILE` must be an absolute path to the downloaded Firebase service account JSON file on the Raspberry Pi.

3. Set up Arduino connections:
   - Two Arduino boards with RFID readers will be detected during installation
   - The script will help you identify and configure the correct COM ports

4. Make the install script executable and run it:
   ```bash
   chmod +x install.sh
   ./install.sh
   ```

   The installation script will:
   - Update the system
   - Install required dependencies
   - Set up the project directory
   - Configure Firebase credentials if not already present
   - Detect and configure Arduino hardware IDs
   - Create and enable system services for auto-start
   - Configure a browser to open on boot (optional)

## Configuration Files

- `.env`: Contains Firebase credentials
- `hardwareIDS.json`: Contains Arduino COM port assignments
- `requirements.txt`: Python package dependencies

## System Services

The installation creates two systemd services:
1. `tagtracker.service`: Manages the main battery tracking system
2. `browser.service`: (Optional) Opens a specified webpage on boot

## Operation

Once installed and running, the system will:
1. Monitor RFID scans from both Arduino readers
2. Track battery placement and removal from charging slots
3. Update Firebase with real-time status changes
4. Manage LED indicators showing slot status:
   - Orange (pulsing): Slot available
   - Red (solid): Currently charging
   - Blue (solid): Charge complete
   - Green (deep pulse): Next battery to pick

## Troubleshooting

- Check system status: `systemctl status tagtracker.service`
- View logs: `journalctl -u tagtracker.service`
- Hardware issues: Check `hardwareIDS.json` for correct COM port assignments
- Firebase connection: Verify credentials in `.env` file
- LED sync issues: Check Arduino connections and restart service

## Support

For issues and support, please create an issue in the repository or contact me.
