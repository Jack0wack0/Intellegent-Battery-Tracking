# Arduino firmware: protocol v2

See the [coordinated change summary and detailed installation guide](../Shared/INSTALL_COMPETITION_RELEASE.md) before installing this release.

The cart has seven installed slots: A0–A5 on board 1 are slots 0–5; A0 on board 2 is slot 6.
The remaining inputs on board 2 are ignored by the default Pi configuration. Ground unused
inputs, use a shared ground and the LED strip's appropriate external power supply.
Presence threshold hysteresis is 430/470 with a non-blocking 500 ms settle period.

The shared header owns both sketches. **Do not compile both `.ino` files in one Arduino IDE
folder**, because they define two board configurations. Prepare separate sketch directories:

```sh
python3 prepare_sketches.py /tmp/battery-cart-sketches
```

Open `BatteryCartBoard1/BatteryCartBoard1.ino` or `BatteryCartBoard2/BatteryCartBoard2.ino`.
Install FastLED **3.6.0** and select Arduino UNO. Verify the physical board assignment before
uploading. The default seven-segment buffer controls pixels 0–59; active segments use
positions 3, 11, 18, 26, 34, 42, 49 with width 5. Unused pixels beyond 59 are not driven by
this firmware; power-cycle the strip during the coordinated firmware installation.

The tested seven-slot UNO build uses 8,638 bytes flash and 847 bytes SRAM on board 1,
and 3,012 bytes flash/452 bytes SRAM on board 2 (native AVR GCC 15.2, AVR core 1.8.8,
FastLED 3.6.0; see release evidence for final post-edit numbers).

## Protocol

At startup and after `SNAPSHOT`, a board emits:

```text
BEGIN 1 V2
LAYOUT 7 60
SLOT_0:PRESENT
... all six board slots ...
END 1
```

Only board 1 emits LAYOUT. Board 2 uses BEGIN/END 2 and slots 6–11. The Pi waits for a
complete snapshot and validates board ownership instead of treating silence as empty.
`PING` returns `PONG <six-bit-presence-mask>`; the Pi uses it to repair dropped transitions. Board 1 accepts:

```text
CMD abcdef123456 SEG 0 POS 3 COLOR 85 MODE DEEPPULSE
ACK abcdef123456
```

Commands must be complete, bounded and valid before ACK; modes are SOLID/FLASH/PULSE/DEEPPULSE.
A five-second heartbeat timeout returns LEDs to purple fallback; each segment also expires ten seconds after its last valid command, so PING alone cannot preserve a stale pick. USB reconnect resets command caches
and re-establishes snapshots. For a future larger cart, compile matching `CART_SLOT_COUNT`
and update `SLOT_COUNT` and the physical LED mapping deliberately; do not change slot counts
on only one machine.

Physical shielding/reader-field cross-talk is still a bench acceptance requirement. Firmware
compilation and conservative software matching do not prove that neighboring tags are read
reliably by the installed RF hardware.
