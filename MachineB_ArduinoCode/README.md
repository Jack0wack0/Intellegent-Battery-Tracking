# Arduino Code

This folder contains the Arduino sketches used on the two Arduino UNOs that monitor charging slots and drive an addressable LED strip.

Files
- `RFID_ARDUINO_1.ino` — Main Arduino controlling the LED strip (uses FastLED) and reporting slot state for slots 0–5.
- `RFID_ARDUINO_2.ino` — Second Arduino that reports slot state for slots 6–11 (it adds +6 to its slot indices).

Quick overview
- Each Arduino reads analog sensors (A0..A5) to determine whether a battery is present in a slot.
- When a slot state changes the Arduino prints a line to Serial (USB) in the form:
	- `SLOT_<N>:PRESENT` or `SLOT_<N>:REMOVED`
	- Example: `SLOT_3:PRESENT`
- The Raspberry Pi `input_listener.py` listens to those serial messages and matches them with RFID scans.

Dependencies
- `RFID_ARDUINO_1.ino` requires the FastLED library. Install it in the Arduino IDE via Library Manager or with PlatformIO.

Wiring notes
- Connect the LED strip data line to the Arduino pin defined by `LED_PIN` (default `3` in `RFID_ARDUINO_1.ino`).
- Power the LED strip with an appropriate external 5V supply and common ground between the Arduino and the strip.
- Connect the analog presence sensors to A0..A5 on each Arduino.
- USB connection to the Raspberry Pi is used for serial communication and power.
- VERY IMPORTANT WIRING NOTE: Any unused slots MUST be grounded. Everything needs to share the same ground plane or false positives will occur.

Key configuration values (in the sketches)
- `threshold` (default `450`) — analog threshold to decide PRESENT vs REMOVED. Tune this for your sensors.
- `slotCount` (default `6`) — number of slots each Arduino monitors. Do not change this
- `NUM_SEGMENTS`, `SEGMENT_WIDTH` and `NUM_LEDS` in `RFID_ARDUINO_1.ino` define how the LED strip is partitioned into segments; the Python `input_listener.py` uses segment indices and positions to address LEDs.

Serial protocol / LED control
- The main Arduino (1) accepts simple text commands over Serial to control LEDs. The format is:
	- `SEG <id 0-6> POS <index> COLOR <hue 0-255> MODE SOLID|FLASH|PULSE|DEEPPULSE`\
		Example: `SEG 3 POS 120 COLOR 90 MODE PULSE`
- After processing a valid `SEG` command the Arduino responds with `ACK` and a human-readable summary.
- A simple keep-alive command is supported: send `PING`, Arduino replies `PONG` and marks the serial connection active.

Important implementation details
- `RFID_ARDUINO_1.ino` contains a `delay(500)` after detecting a state change — this debounce/delay is required because the Pi reads the arduino output faster than the Pi can recieve the RFID ID; do not remove it.
- `RFID_ARDUINO_2.ino` reports slots with `i + 6` so the second board occupies slots 6..11.

# Upload instructions

Arduino IDE
1. Open the `.ino` file in the Arduino IDE.
2. Install the FastLED library (Sketch → Include Library → Manage Libraries → search `FastLED`).
3. Select the correct board (`Arduino UNO`) and serial port.
4. Upload.

PlatformIO (VS Code) Dont do this just use the Arduino IDE stop making life hard for yourself.
1. Create or open a PlatformIO project for `uno` and add `FastLED` as a lib dependency.
2. Copy the sketch code into `src/main.cpp` (you may need to adapt Arduino-style `.ino` top-level declarations to C++ style — usually just pasting works).
3. Build and upload using PlatformIO.

Tuning and testing
- Adjust `threshold` values if you see false triggers.
- Use the Arduino Serial Monitor (9600 baud) to watch `SLOT_` messages while plugging/unplugging batteries to confirm correct behavior.
- For LEDs, verify the `SEG` command from the Raspberry Pi by running the Python LED manager; you should see `ACK` responses from `RFID_ARDUINO_1`.

Troubleshooting
- No serial output: confirm the Arduino is powered and the USB cable is data-capable.
- LEDs not responding: check external power to the strip, common ground, and that `LED_PIN` and `NUM_LEDS` match your hardware.
- Wrong slot indices: remember the second Arduino offsets its slot index by +6.

Notes and suggestions
- If you change the number of slots or LED layout, update both the Arduino sketch and `MachineA_BatteryCart/input_listener.py` so the segment positions and slot mapping remain in sync.


