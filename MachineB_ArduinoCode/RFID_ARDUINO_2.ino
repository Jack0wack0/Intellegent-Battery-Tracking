const int slotCount = 6;  // Number of charging slots you're monitoring
const int analogPins[slotCount] = {A0, A1, A2, A3, A4, A5}; // pins that the program is monitoring on
int lastState[slotCount]; 

const int threshold = 450;  // Adjust as needed, threshold for present/not present

void setup() {
  Serial.begin(9600); 
  for (int i = 0; i < slotCount; i++) {
    pinMode(analogPins[i], INPUT);
    lastState[i] = analogRead(analogPins[i]) > threshold ? 1 : 0; //pull the state from the slot and assign it to lastState
  }
}

void loop() {
  for (int i = 0; i < slotCount; i++) {
    int val = analogRead(analogPins[i]);
    int currentState = val > threshold ? 1 : 0;

    if (currentState != lastState[i]) { //output if the state is different.
      lastState[i] = currentState;
      delay(500); // if you are wondering what this is here for, dont touch it and read the comment in RFID_ARDUINO_1 
      Serial.print("SLOT_");
      Serial.print(i+6); //added +6 for the 2nd arduino.
      Serial.print(":");
      Serial.println(currentState == 1 ? "PRESENT" : "REMOVED");
    }
  }

  delay(50); // debounce
}
