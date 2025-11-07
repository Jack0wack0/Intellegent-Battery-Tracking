#include <FastLED.h>

// ---------------- LED Config ----------------
#define LED_PIN     3
#define NUM_LEDS    300
#define BRIGHTNESS  100
#define LED_TYPE    WS2812B
#define COLOR_ORDER GRB

CRGB leds[NUM_LEDS];

// ---------------- Slot Monitoring ----------------
const int slotCount = 6;
const int analogPins[slotCount] = {A0, A1, A2, A3, A4, A5};
int lastState[slotCount];
const int threshold = 450;

// ---------------- Segment / Mode Control ----------------
#define NUM_SEGMENTS 7
#define SEGMENT_WIDTH 5

enum Mode { SOLID = 0, FLASH = 1, PULSE = 2, DEEP_PULSE = 3 };

struct Segment {
  int startIndex;   // starting LED index
  uint8_t hue;      // CHSV hue (0-255)
  Mode mode;        // color mode
};

Segment segments[NUM_SEGMENTS];

// ---------------- Serial + Animation Timers ----------------
unsigned long lastSerialCmdTime = 0;
const unsigned long SERIAL_TIMEOUT = 5000;

float modePhase = 0.0f;
float modeSpeed = 0.005f;

float fallbackPhase = 0.0f;
float fallbackSpeed = 0.09f;

// ---------------- Serial boolean ----------------
bool serialConnected = false; //global flag

// ---------------- Setup ----------------
void setup() {
  Serial.begin(9600);
  delay(200);

  FastLED.addLeds<LED_TYPE, LED_PIN, COLOR_ORDER>(leds, NUM_LEDS);
  FastLED.setBrightness(BRIGHTNESS);
  FastLED.clear(true);

  // Slot setup
  for (int i = 0; i < slotCount; i++) {
    pinMode(analogPins[i], INPUT);
    lastState[i] = analogRead(analogPins[i]) > threshold ? 1 : 0;
  }

  // Default segments evenly spaced
  for (int i = 0; i < NUM_SEGMENTS; i++) {
    segments[i].startIndex = i * (NUM_LEDS / NUM_SEGMENTS);
    segments[i].hue = (i * 36) % 255;  // rainbow start hues
    segments[i].mode = PULSE;
  }

  lastSerialCmdTime = millis();

  Serial.println("Ready. Commands:");
  Serial.println("  SEG <id 0-6> POS <index> COLOR <hue 0-255> MODE SOLID|FLASH|PULSE|DEEPPULSE");
  Serial.println("  Example: SEG 3 POS 120 COLOR 90 MODE PULSE");
}

// ---------------- Loop ----------------
void loop() {
  unsigned long now = millis();

  // slot monitoring
  for (int i = 0; i < slotCount; i++) {
    int val = analogRead(analogPins[i]);
    int state = val > threshold ? 1 : 0;
    if (state != lastState[i]) {
      lastState[i] = state;
      delay(500); // the arduinos are too fast. listener function listens to usb inputs before arduinos, which means if this delay doesnt exist the whole program breaks.
      Serial.print("SLOT_");
      Serial.print(i);
      Serial.print(":");
      Serial.println(state ? "PRESENT" : "REMOVED");
    }
  }

  handleSerialInput();

  if (!serialConnected) {
      runFallbackPurple();  // stay purple until serial is active
    } else {
      runSegments();  // always show segments once connected
    }

    delay(20);
  }

// ---------------- Segment Rendering ----------------
void runSegments() {
  FastLED.clear();

  // advance phase (0..1)
  modePhase += modeSpeed;
  if (modePhase >= 1.0f) modePhase -= 1.0f;

  // triangular waveform value in [0.0 .. 1.0 .. 0.0]
  float tri = (modePhase < 0.5f) ? (modePhase * 2.0f) : (2.0f * (1.0f - modePhase));

  for (int s = 0; s < NUM_SEGMENTS; s++) {
    Segment &seg = segments[s];
    bool on = true;
    uint8_t outV = BRIGHTNESS; // default output brightness value (0-255)

    switch (seg.mode) {
      case SOLID:
        on = true;
        outV = BRIGHTNESS;
        break;

      case FLASH: {
        static unsigned long lastToggle = 0;
        static bool state = false;
        if (millis() - lastToggle > 150) {
          lastToggle = millis();
          state = !state;
        }
        on = state;
        outV = on ? BRIGHTNESS : 0;
        break;
      }

      case PULSE: {
        // PULSE should go 20% -> 100%
        float perc = 0.2f + tri * 0.8f;             // 0.2 .. 1.0
        outV = (uint8_t)constrain(BRIGHTNESS * perc, 0, 255);
        break;
      }

      case DEEP_PULSE: {
        // DEEPPULSE should go 0% -> 100%
        float perc = tri;                           // 0.0 .. 1.0
        outV = (uint8_t)constrain(BRIGHTNESS * perc, 0, 255);
        break;
      }
    }

    // draw flat block of SEGMENT_WIDTH LEDs at equal brightness outV
    for (int i = 0; i < SEGMENT_WIDTH; i++) {
      int ledIndex = seg.startIndex + i;
      if (ledIndex >= NUM_LEDS || ledIndex < 0) continue;

      if (outV > 0)
        leds[ledIndex] = CHSV(seg.hue, 255, outV);
      else
        leds[ledIndex] = CRGB::Black;
    }
  }

  FastLED.show();
}

// ---------------- Fallback Mode ----------------
void runFallbackPurple() {
  fallbackPhase += fallbackSpeed;
  if (fallbackPhase > 6.283f) fallbackPhase -= 6.283f;

  float b = 0.8f * (sin(fallbackPhase) * 0.5f + 0.5f) + 0.05f;
  uint8_t r = (uint8_t)(180.0f * b);
  uint8_t g = 0;
  uint8_t bl = (uint8_t)(255.0f * b);

  fill_solid(leds, NUM_LEDS, CRGB(r, g, bl));
  FastLED.show();
}

// ---------------- Serial Commands ----------------
void handleSerialInput() {
  while (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (!line.length()) continue;

    String u = line;
    u.toUpperCase();
    
    // --- Keepalive command ---
    if (u == "PING") {
      lastSerialCmdTime = millis();  // ✅ only reset here
      serialConnected = true;
      Serial.println("PONG");
      continue;
    }

    if (u.startsWith("SEG")) {
      int segID = -1;
      int posIdx = -1;
      int colorVal = -1;
      String modeStr = "";

      int segPos = u.indexOf("SEG");
      int posPos = u.indexOf("POS");
      int colorPos = u.indexOf("COLOR");
      int modePos = u.indexOf("MODE");

      if (segPos >= 0) {
        int after = segPos + 3;
        segID = line.substring(after, posPos > 0 ? posPos : line.length()).toInt();
      }
      if (posPos >= 0) {
        int after = posPos + 3;
        posIdx = line.substring(after, colorPos > 0 ? colorPos : line.length()).toInt();
      }
      if (colorPos >= 0) {
        int after = colorPos + 5;
        colorVal = line.substring(after, modePos > 0 ? modePos : line.length()).toInt();
      }
      if (modePos >= 0) {
        modeStr = line.substring(modePos + 4);
        modeStr.trim();
        modeStr.toUpperCase();
      }

      if (segID >= 0 && segID < NUM_SEGMENTS) {
        if (posIdx >= 0) segments[segID].startIndex = posIdx;
        if (colorVal >= 0 && colorVal <= 255) segments[segID].hue = colorVal;
        if (modeStr.length()) {
          if (modeStr == "SOLID") segments[segID].mode = SOLID;
          else if (modeStr == "FLASH") segments[segID].mode = FLASH;
          else if (modeStr == "PULSE") segments[segID].mode = PULSE;
          else if (modeStr == "DEEPPULSE") segments[segID].mode = DEEP_PULSE;
        }
        Serial.println("ACK");
        Serial.flush();
        Serial.print("Segment "); Serial.print(segID);
        Serial.print(" -> POS "); Serial.print(segments[segID].startIndex);
        Serial.print(" COLOR "); Serial.print(segments[segID].hue);
        Serial.print(" MODE "); Serial.println(modeStr);

        lastSerialCmdTime = millis();  // reset only after valid SEG command
        serialConnected = true; // mark it as connected
      } else {
        Serial.println("Invalid SEG ID (0-6)");
      }
    }
  }
}
