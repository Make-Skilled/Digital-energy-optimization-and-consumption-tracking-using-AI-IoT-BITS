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

// Current Sensor Pins (ACS712)
#define CURRENT_SENSOR_PIN3  35  // First ACS712 Sensor (A0)
#define CURRENT_SENSOR_PIN4  34  // Second ACS712 Sensor (A1)

// Constants for ACS712
#define ASSUMED_VOLTAGE 230.0    // Assume constant voltage (230V for AC mains)
#define ACS_SENSITIVITY 0.066    // For ACS712-30A (0.066V/A)
float ACS_OFFSET = 0.0;         // Will be calibrated

// Variables for power measurement
float currentValue3 = 0.0;
float currentValue4 = 0.0;
float powerValue3 = 0.0;
float powerValue4 = 0.0;
float totalCurrent = 0.0;
float totalPower = 0.0;
float kWh = 0.0;

// Timing variables
unsigned long lastPrintTime = 0;
unsigned long lastPowerAlertTime = 0;
unsigned long lastThingSpeakUpdate = 0;
#define PRINT_INTERVAL 5000  // Print every 5 seconds

// Measure Current & Calculate Power
void measurePower() {
  float totalCurrent3 = 0;
  float totalCurrent4 = 0;
  int numSamples = 100;  // Noise reduction

  // Read from first current sensor
  for (int i = 0; i < numSamples; i++) {
    float currentSensorValue3 = analogRead(CURRENT_SENSOR_PIN3);
    float currentVoltage3 = (currentSensorValue3 / 4095.0) * 3.3;
    totalCurrent3 += (currentVoltage3 - ACS_OFFSET) / ACS_SENSITIVITY;
    delayMicroseconds(100);
  }
  currentValue3 = totalCurrent3 / numSamples;

  // Read from second current sensor
  for (int i = 0; i < numSamples; i++) {
    float currentSensorValue4 = analogRead(CURRENT_SENSOR_PIN4);
    float currentVoltage4 = (currentSensorValue4 / 4095.0) * 3.3;
    totalCurrent4 += (currentVoltage4 - ACS_OFFSET) / ACS_SENSITIVITY;
    delayMicroseconds(100);
  }
  currentValue4 = totalCurrent4 / numSamples;

  // Calculate total current (sum of both sensors)
  totalCurrent = currentValue3 + currentValue4;

  // Calculate power (P = V * I) for both sensors
  powerValue3 = ASSUMED_VOLTAGE * currentValue3;
  powerValue4 = ASSUMED_VOLTAGE * currentValue4;
  totalPower = powerValue3 + powerValue4;

  // Update kWh
  unsigned long currentMillis = millis();
  kWh += totalPower * (currentMillis - lastPowerAlertTime) / 3600000.0;
  lastPowerAlertTime = currentMillis;

  // Store absolute values of power in new variables
  float absPowerValue3 = abs(powerValue3);
  float absPowerValue4 = abs(powerValue4);
  float absTotalPower = abs(totalPower);
  float absKWh = abs(kWh);

  // Print values at regular intervals
  if (currentMillis - lastPrintTime >= PRINT_INTERVAL) {
    Serial.println("\n=== Power Consumption Report ===");
    Serial.println("--------------------------------");
    Serial.print("Current Sensor 3: "); 
    Serial.print(abs(currentValue3), 2);  // Use original values
    Serial.println(" A");
    Serial.print("Current Sensor 4: "); 
    Serial.print(abs(currentValue4), 2);  // Use original values
    Serial.println(" A");
    
    Serial.print("Voltage:     ");
    Serial.print(ASSUMED_VOLTAGE, 1);
    Serial.println(" V");
    
    Serial.print("Power Sensor 3: ");
    Serial.print(absPowerValue3, 2);  // Use the absolute value
    Serial.println(" W");

    Serial.print("Power Sensor 4: ");
    Serial.print(absPowerValue4, 2);  // Use the absolute value
    Serial.println(" W");

    Serial.print("Total Power:  ");
    Serial.print(absTotalPower, 2);  // Use the absolute value
    Serial.println(" W");

    Serial.print("Energy:      ");
    Serial.print(absKWh, 3);  // Use the absolute value
    Serial.println(" kWh");

    Serial.println("--------------------------------\n");
    lastPrintTime = currentMillis;
  }
}

// Send Data to ThingSpeak
void sendDataToThingSpeak() {
  ThingSpeak.setField(4, abs(powerValue3));
  ThingSpeak.setField(5, abs(powerValue4));
  ThingSpeak.setField(6, abs(kWh));
  
  int responseCode = ThingSpeak.writeFields(channelid, thingSpeakWriteAPIKey);
  if (responseCode == 200) {
    Serial.println("✅ Data sent to ThingSpeak!");
  } else {
    Serial.print("❌ Error sending data: ");
    Serial.println(responseCode);
  }
}

// Dynamic Calibration for ACS712
void calibrateACS712() {
  Serial.println("Calibrating ACS712 sensor...");
  float total = 0;
  int numSamples = 1000;

  for (int i = 0; i < numSamples; i++) {
    total += (analogRead(CURRENT_SENSOR_PIN3) / 4095.0) * 3.3;
    total += (analogRead(CURRENT_SENSOR_PIN4) / 4095.0) * 3.3;
    delay(1);
  }

  ACS_OFFSET = total / (numSamples * 2);
  Serial.print("ACS712 Offset: ");
  Serial.println(ACS_OFFSET, 3);
}

void setup() {
  Serial.begin(115200);
  
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

  unsigned long currentMillis = millis();
  
  // Regular ThingSpeak updates
  if (currentMillis - lastThingSpeakUpdate >= 15000) {
    sendDataToThingSpeak();
    lastThingSpeakUpdate = currentMillis;
  }

  delay(2000); // Shorter delay for more responsive detection
}
