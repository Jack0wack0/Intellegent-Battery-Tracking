#pragma once
#include <Arduino.h>
#ifdef CART_LEDS
#include <FastLED.h>
// Seven active segments end at pixel 53; avoid reserving 900 bytes for 300 pixels.
// For a larger cart, change both constants and the Pi's explicit slot/position configuration.
#define NUM_LEDS 60
#define NUM_SEGMENTS 7
CRGB leds[NUM_LEDS];
struct Segment { int position; uint8_t hue; uint8_t mode; };
Segment segments[NUM_SEGMENTS];
#endif

const uint8_t sensorPins[6] = {A0, A1, A2, A3, A4, A5};
bool stableState[6], candidateState[6];
unsigned long changedAt[6];
unsigned long lastCommand = 0;
bool connected = false;
char commandBuffer[112];
uint8_t commandLength = 0;
bool commandOverflow = false;

void emitSlot(uint8_t index) {
  Serial.print("SLOT_"); Serial.print(SLOT_OFFSET + index); Serial.print(":");
  Serial.println(stableState[index] ? "PRESENT" : "REMOVED");
}

void snapshot() {
  Serial.print("BEGIN "); Serial.print(BOARD_ID); Serial.println(" V2");
  for (uint8_t i=0; i<6; i++) emitSlot(i);
  Serial.print("END "); Serial.println(BOARD_ID);
}

bool validIdentity(const char* value) {
  if (strlen(value) != 12) return false;
  for (uint8_t i=0; i<12; i++) if (!isxdigit(value[i])) return false;
  return true;
}

void handleCommand(char* line) {
  if (strcmp(line, "PING") == 0) {
    lastCommand = millis(); connected = true; Serial.println("PONG"); return;
  }
  if (strcmp(line, "SNAPSHOT") == 0) { snapshot(); return; }
#ifdef CART_LEDS
  char identity[13] = {0}, mode[12] = {0}, extra;
  int segment, position, hue;
  // Width limits protect SRAM; extra captures trailing garbage.
  int parsed = sscanf(line, "CMD %12s SEG %d POS %d COLOR %d MODE %11s %c",
                      identity, &segment, &position, &hue, mode, &extra);
  uint8_t modeId = 255;
  if (strcmp(mode, "SOLID") == 0) modeId=0;
  else if (strcmp(mode, "FLASH") == 0) modeId=1;
  else if (strcmp(mode, "PULSE") == 0) modeId=2;
  else if (strcmp(mode, "DEEPPULSE") == 0) modeId=3;
  if (parsed == 5 && validIdentity(identity) && segment >= 0 && segment < NUM_SEGMENTS &&
      position >= 0 && position + 5 <= NUM_LEDS && hue >= 0 && hue <= 255 && modeId != 255) {
    segments[segment] = {position, (uint8_t)hue, modeId};
    lastCommand=millis(); connected=true;
    Serial.print("ACK "); Serial.println(identity); return;
  }
#endif
  Serial.println("ERROR INVALID_COMMAND");
}

void setup() {
  Serial.begin(9600);
  for (uint8_t i=0; i<6; i++) {
    pinMode(sensorPins[i], INPUT);
    stableState[i] = candidateState[i] = analogRead(sensorPins[i]) > 450;
    changedAt[i] = millis();
  }
#ifdef CART_LEDS
  FastLED.addLeds<WS2812B, 3, GRB>(leds, NUM_LEDS);
  FastLED.setBrightness(100);
  for (uint8_t i=0; i<NUM_SEGMENTS; i++) segments[i] = {i*8, 200, 1};
#endif
  delay(200);
  snapshot();
}

void loop() {
  unsigned long now=millis();
  for (uint8_t i=0; i<6; i++) {
    int analog=analogRead(sensorPins[i]);
    // Hysteresis plus non-blocking 500ms settle retains the scan timing window.
    bool observed = candidateState[i] ? analog >= 430 : analog > 470;
    if (observed != candidateState[i]) { candidateState[i]=observed; changedAt[i]=now; }
    if (candidateState[i] != stableState[i] && now-changedAt[i] >= 500) {
      stableState[i]=candidateState[i]; emitSlot(i);
    }
  }
  while (Serial.available()) {
    char value=Serial.read();
    if (value=='\n') {
      if (!commandOverflow) {
        commandBuffer[commandLength]='\0'; handleCommand(commandBuffer);
      } else Serial.println("ERROR COMMAND_TOO_LONG");
      commandLength=0; commandOverflow=false;
    } else if (value!='\r') {
      if (commandLength < sizeof(commandBuffer)-1) commandBuffer[commandLength++]=value;
      else commandOverflow=true;
    }
  }
  if (millis()-lastCommand > 5000) connected=false;
#ifdef CART_LEDS
  FastLED.clear();
  if (!connected) fill_solid(leds, NUM_LEDS, CRGB(60,0,80));
  else {
    uint8_t phase=(now / 12) % 256;
    uint8_t triangle=phase<128 ? phase*2 : (255-phase)*2;
    for (uint8_t i=0; i<NUM_SEGMENTS; i++) {
      Segment &s=segments[i];
      uint8_t brightness = s.mode==0 ? 255 : s.mode==1 ? ((now/200)%2 ? 255:0) :
                           s.mode==2 ? 51+((uint16_t)triangle*204)/255 : triangle;
      for (uint8_t j=0; j<5; j++) leds[s.position+j]=CHSV(s.hue,255,brightness);
    }
  }
  FastLED.show();
#endif
  delay(10);
}
