#include <WiFi.h>
#include <WiFiClient.h>
#include <ThingSpeak.h>

// WiFi Credentials
char ssid[] = "Act";
char pass[] = "Madhumakeskilled";

// ThingSpeak API
WiFiClient client;
unsigned long channelid = 2571433;
char thingSpeakWriteAPIKey[] = "DKFMSF5LBO7MG9F5";

unsigned long billchannelid = 2463572;
char billWriteAPIKey[] = "D4DB9ZE264CRSE9P";

// Current Sensor Pins (ACS712)
#define CURRENT_SENSOR_PIN1  35  // First ACS712 Sensor (A0)
#define CURRENT_SENSOR_PIN2  34  // Second ACS712 Sensor (A1)

// Constants for ACS712
#define ASSUMED_VOLTAGE 230.0    // Assume constant voltage (230V for AC mains)
#define ACS_SENSITIVITY 0.066    // For ACS712-30A (0.066V/A)
float ACS_OFFSET = 0.0;         // Will be calibrated

// Variables for power measurement
float currentValue1 = 0.0;
float currentValue2 = 0.0;
float powerValue1 = 0.0;
float powerValue2 = 0.0;
float totalCurrent = 0.0;
float totalPower = 0.0;
float kWh = 0.0;


// Timing variables
unsigned long lastPrintTime = 0;
unsigned long lastPowerAlertTime = 0;
unsigned long lastThingSpeakUpdate = 0;
#define PRINT_INTERVAL 5000  // Print every 5 seconds

// RFID scan status
String rfidData = "";
bool cardScanned = false;

// Measure Current & Calculate Power
void measurePower() {
  float totalCurrent1 = 0;
  float totalCurrent2 = 0;
  int numSamples = 100;  // Noise reduction

  // Read from first current sensor
  for (int i = 0; i < numSamples; i++) {
    float currentSensorValue1 = analogRead(CURRENT_SENSOR_PIN1);
    float currentVoltage1 = (currentSensorValue1 / 4095.0) * 3.3;
    totalCurrent1 += (currentVoltage1 - ACS_OFFSET) / ACS_SENSITIVITY;
    delayMicroseconds(100);
  }
  currentValue1 = totalCurrent1 / numSamples;

  // Read from second current sensor
  for (int i = 0; i < numSamples; i++) {
    float currentSensorValue2 = analogRead(CURRENT_SENSOR_PIN2);
    float currentVoltage2 = (currentSensorValue2 / 4095.0) * 3.3;
    totalCurrent2 += (currentVoltage2 - ACS_OFFSET) / ACS_SENSITIVITY;
    delayMicroseconds(100);
  }
  currentValue2 = totalCurrent2 / numSamples;

  // Calculate total current (sum of both sensors)
  totalCurrent = currentValue1 + currentValue2;

  // Calculate power (P = V * I) for both sensors
  powerValue1 = ASSUMED_VOLTAGE * currentValue1;
  powerValue2 = ASSUMED_VOLTAGE * currentValue2;
  totalPower = powerValue1 + powerValue2;

  // Update kWh
  unsigned long currentMillis = millis();
  kWh += totalPower * (currentMillis - lastPowerAlertTime) / 3600000.0;
  lastPowerAlertTime = currentMillis;

  // Store absolute values of power in new variables
  float absPowerValue1 = abs(powerValue1);
  float absPowerValue2 = abs(powerValue2);
  float absTotalPower = abs(totalPower);
  float absKWh = abs(kWh);

  // Print values at regular intervals
  if (currentMillis - lastPrintTime >= PRINT_INTERVAL) {
    Serial.println("\n=== Power Consumption Report ===");
    Serial.println("--------------------------------");
    Serial.print("Current Sensor 1: "); 
    Serial.print(abs(currentValue1), 2);  // Use original values
    Serial.println(" A");
    Serial.print("Current Sensor 2: "); 
    Serial.print(abs(currentValue2), 2);  // Use original values
    Serial.println(" A");
    
    Serial.print("Voltage:     ");
    Serial.print(ASSUMED_VOLTAGE, 1);
    Serial.println(" V");
    
    Serial.print("Power Sensor 1: ");
    Serial.print(absPowerValue1, 2);  // Use the absolute value
    Serial.println(" W");

    Serial.print("Power Sensor 2: ");
    Serial.print(absPowerValue2, 2);  // Use the absolute value
    Serial.println(" W");

    Serial.print("Total Power:  ");
    Serial.print(absTotalPower, 2);  // Use the absolute value
    Serial.println(" W");

    Serial.print("Energy:      ");
    Serial.print(absKWh, 3);  // Use the absolute value
    Serial.println(" kWh");

    // Print the RFID data if a card is scanned
    if (cardScanned) {
      Serial.print("RFID Data: ");
      Serial.println(rfidData);  // Print the scanned RFID data
    }

    Serial.println("--------------------------------\n");
    lastPrintTime = currentMillis;
  }
}

// Send Data to ThingSpeak
void sendDataToThingSpeak() {
  ThingSpeak.setField(1, abs(powerValue1));
  ThingSpeak.setField(2, abs(powerValue2));
  ThingSpeak.setField(3, abs(kWh));
  ThingSpeak.setField(1, cardScanned ? 1 : 0);  // Send RFID scan status (1 for scanned, 0 for not scanned)
  
  int responseCode = ThingSpeak.writeFields(channelid, thingSpeakWriteAPIKey);
  if (responseCode == 200) {
    Serial.println("✅ Data sent to ThingSpeak!");
  } else {
    Serial.print("❌ Error sending data: ");
    Serial.println(responseCode);
  }
}

void sendDataToThingSpeakBill() {
  ThingSpeak.setField(1, cardScanned ? 1 : 0);  // Send RFID scan status (1 for scanned, 0 for not scanned)
  
  int responseCode = ThingSpeak.writeFields(billchannelid, billWriteAPIKey);
  if (responseCode == 200) {
    Serial.println("✅ Data sent to ThingSpeak!");
  } else {
    Serial.print("❌ Error sending data: ");
    Serial.println(responseCode);
  }
}

// Check for RFID scan status
bool isCardScanned() {
  // Check if data is available from RFID serial
  if (Serial.available()) {
    rfidData = "";
    while (Serial.available()) {
      char c = Serial.read();
      rfidData += c;
//      Serial.print(rfidData);
      delay(100);
    }
    // If RFID data is received, return true
    if (rfidData.length() > 0) {
      cardScanned = true;
      return true;
    }
  }
  // If no RFID data, return false
  cardScanned = false;
  return false;
}

// Dynamic Calibration for ACS712
void calibrateACS712() {
  Serial.println("Calibrating ACS712 sensor...");
  float total = 0;
  int numSamples = 1000;

  for (int i = 0; i < numSamples; i++) {
    total += (analogRead(CURRENT_SENSOR_PIN1) / 4095.0) * 3.3;
    total += (analogRead(CURRENT_SENSOR_PIN2) / 4095.0) * 3.3;
    delay(1);
  }

  ACS_OFFSET = total / (numSamples * 2);
  Serial.print("ACS712 Offset: ");
  Serial.println(ACS_OFFSET, 3);
}

void setup() {
  Serial.begin(9600);
  
  // Connect to Wi-Fi
  WiFi.begin(ssid, pass);
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.println("Connecting to WiFi...");
  }
  Serial.println("Connected to WiFi!");
  ThingSpeak.begin(client);

  // Calibrate ACS712
  calibrateACS712();
}

void loop() {
  // Measure power and check RFID scan status
  measurePower();
  isCardScanned();

  unsigned long currentMillis = millis();
  
  // Regular ThingSpeak updates
  if (currentMillis - lastThingSpeakUpdate >= 15000) {
    sendDataToThingSpeak();
    sendDataToThingSpeakBill();
    lastThingSpeakUpdate = currentMillis;
  }

  delay(2000); // Shorter delay for more responsive detection
}
