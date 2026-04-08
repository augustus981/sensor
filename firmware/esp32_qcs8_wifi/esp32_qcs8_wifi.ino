/*
 * ESP32 + QC-S8 Soil Sensor — Wi-Fi Prototype Firmware
 *
 * Reads 7 soil parameters from a QC-S8 sensor via Modbus RTU (RS485),
 * then POSTs the data to the Durian IoT API over Wi-Fi.
 * Uses deep sleep between readings to conserve battery.
 *
 * Hardware:
 *   - ESP32-WROOM-32 DevKit (38-pin, Type-C)
 *   - QC-S8 7-in-1 soil sensor (RS485 Modbus RTU)
 *   - MAX485 TTL-to-RS485 module
 *   - MT3608 boost converter (3.7V → 5V)
 *   - IRLZ44N MOSFET for sensor power gating
 *   - 18650 battery + TP4056 charger
 *
 * Wiring (see hardware/circuit_blueprint.md):
 *   GPIO16 (RX2) ← RS485 module RO
 *   GPIO17 (TX2) → RS485 module DI
 *   GPIO4        → RS485 module DE + RE (direction control)
 *   GPIO27       → IRLZ44N Gate (sensor power switch)
 *   GPIO34       → Battery voltage divider (ADC, optional)
 */

#include <WiFi.h>
#include <HTTPClient.h>

// ==========================================================================
// Configuration — EDIT THESE FOR YOUR SETUP
// ==========================================================================

// Wi-Fi credentials
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// API endpoint (your server running data_collector)
const char* API_URL = "http://YOUR_SERVER_IP:5000/api/readings";

// Unique device identifier (used to register in the database)
const char* DEVICE_ID = "esp32-qcs8-0001";

// Deep sleep duration between readings
const int SLEEP_MINUTES = 15;

// Modbus settings for QC-S8
const uint8_t MODBUS_SLAVE_ADDR = 0x01;
const long    MODBUS_BAUD_RATE  = 4800;  // Common for QC-S8; try 9600 if no response

// ==========================================================================
// Pin Assignments
// ==========================================================================

const int PIN_RS485_RX  = 16;   // UART2 RX ← RS485 RO
const int PIN_RS485_TX  = 17;   // UART2 TX → RS485 DI
const int PIN_RS485_DE  = 4;    // RS485 direction: HIGH=transmit, LOW=receive
const int PIN_SENSOR_EN = 27;   // MOSFET gate: HIGH=sensor ON, LOW=sensor OFF
const int PIN_BATT_ADC  = 34;   // Battery voltage via divider (optional)

// ==========================================================================
// Modbus RTU helpers
// ==========================================================================

// CRC-16/Modbus lookup
uint16_t modbusRTU_CRC(const uint8_t* buf, int len) {
    uint16_t crc = 0xFFFF;
    for (int pos = 0; pos < len; pos++) {
        crc ^= (uint16_t)buf[pos];
        for (int i = 0; i < 8; i++) {
            if (crc & 0x0001) {
                crc >>= 1;
                crc ^= 0xA001;
            } else {
                crc >>= 1;
            }
        }
    }
    return crc;
}

/**
 * Send a Modbus RTU "Read Holding Registers" (function 0x03) request
 * and parse the response into an array of uint16_t register values.
 *
 * Returns the number of registers read, or -1 on error.
 */
int modbusReadHolding(uint8_t slaveAddr, uint16_t startReg,
                      uint16_t numRegs, uint16_t* outValues) {
    // Build request frame: [addr][0x03][startHi][startLo][numHi][numLo][crcLo][crcHi]
    uint8_t req[8];
    req[0] = slaveAddr;
    req[1] = 0x03;
    req[2] = (startReg >> 8) & 0xFF;
    req[3] = startReg & 0xFF;
    req[4] = (numRegs >> 8) & 0xFF;
    req[5] = numRegs & 0xFF;
    uint16_t crc = modbusRTU_CRC(req, 6);
    req[6] = crc & 0xFF;
    req[7] = (crc >> 8) & 0xFF;

    // Switch RS485 to transmit
    digitalWrite(PIN_RS485_DE, HIGH);
    delay(1);

    // Clear any stale data in the receive buffer
    while (Serial2.available()) Serial2.read();

    Serial2.write(req, 8);
    Serial2.flush();

    // Switch RS485 to receive
    delay(1);
    digitalWrite(PIN_RS485_DE, LOW);

    // Wait for response: [addr][0x03][byteCount][data...][crcLo][crcHi]
    int expectedLen = 3 + (numRegs * 2) + 2;
    uint8_t resp[64];
    int idx = 0;
    unsigned long startMs = millis();

    while (idx < expectedLen && (millis() - startMs) < 2000) {
        if (Serial2.available()) {
            resp[idx++] = Serial2.read();
        }
    }

    if (idx < expectedLen) {
        Serial.printf("[Modbus] Timeout: got %d/%d bytes\n", idx, expectedLen);
        return -1;
    }

    // Verify CRC
    uint16_t respCrc = modbusRTU_CRC(resp, idx - 2);
    uint16_t recvCrc = resp[idx - 2] | (resp[idx - 1] << 8);
    if (respCrc != recvCrc) {
        Serial.printf("[Modbus] CRC mismatch: calc=0x%04X recv=0x%04X\n", respCrc, recvCrc);
        return -1;
    }

    // Verify slave address and function code
    if (resp[0] != slaveAddr || resp[1] != 0x03) {
        Serial.printf("[Modbus] Bad response: addr=0x%02X func=0x%02X\n", resp[0], resp[1]);
        return -1;
    }

    // Parse register values (big-endian)
    int byteCount = resp[2];
    int regsRead = byteCount / 2;
    for (int i = 0; i < regsRead && i < numRegs; i++) {
        outValues[i] = (resp[3 + i * 2] << 8) | resp[3 + i * 2 + 1];
    }

    return regsRead;
}

// ==========================================================================
// Sensor reading struct
// ==========================================================================

struct SoilReading {
    float moisture;      // %
    float temperature;   // °C
    float ec;            // µS/cm
    float ph;
    float salinity;      // µS/cm
    float nitrogen;      // mg/kg
    float phosphorus;    // mg/kg
    float potassium;     // mg/kg
    bool  valid;
};

/**
 * Read all 7 parameters from the QC-S8 sensor.
 *
 * IMPORTANT: The register map below is a common layout for Chinese
 * 7-in-1 soil sensors. Your QC-S8 datasheet may differ — update
 * the start register and scaling factors if needed.
 *
 * Typical register map (Modbus holding registers starting at 0x0000):
 *   0x0000: Moisture     (÷10 = %)
 *   0x0001: Temperature  (÷10 = °C, signed)
 *   0x0002: Conductivity (raw µS/cm)
 *   0x0003: pH           (÷100)
 *   0x0004: Nitrogen     (mg/kg)
 *   0x0005: Phosphorus   (mg/kg)
 *   0x0006: Potassium    (mg/kg)
 */
SoilReading readQCS8() {
    SoilReading r = {0, 0, 0, 0, 0, 0, 0, 0, false};

    uint16_t regs[7];
    int result = modbusReadHolding(MODBUS_SLAVE_ADDR, 0x0000, 7, regs);

    if (result < 7) {
        Serial.printf("[QC-S8] Failed to read registers (got %d)\n", result);
        return r;
    }

    r.moisture    = regs[0] / 10.0;
    // Handle signed temperature: if value > 32767, it's negative
    r.temperature = ((int16_t)regs[1]) / 10.0;
    r.ec          = (float)regs[2];
    r.ph          = regs[3] / 100.0;
    r.nitrogen    = (float)regs[4];
    r.phosphorus  = (float)regs[5];
    r.potassium   = (float)regs[6];

    // Salinity is often the same as EC for these sensors,
    // or in a separate register. Adjust if your datasheet says otherwise.
    r.salinity    = r.ec;

    r.valid = true;

    Serial.println("[QC-S8] Reading successful:");
    Serial.printf("  Moisture:    %.1f %%\n", r.moisture);
    Serial.printf("  Temperature: %.1f °C\n", r.temperature);
    Serial.printf("  EC:          %.0f µS/cm\n", r.ec);
    Serial.printf("  pH:          %.2f\n", r.ph);
    Serial.printf("  Nitrogen:    %.0f mg/kg\n", r.nitrogen);
    Serial.printf("  Phosphorus:  %.0f mg/kg\n", r.phosphorus);
    Serial.printf("  Potassium:   %.0f mg/kg\n", r.potassium);

    return r;
}

// ==========================================================================
// Battery voltage reading (optional — requires voltage divider on GPIO34)
// ==========================================================================

/**
 * Read battery voltage via ADC with a voltage divider.
 * If you connect a 100kΩ + 100kΩ divider from battery to GPIO34,
 * the ADC reads half the battery voltage.
 * Returns voltage in millivolts, or 0 if not wired.
 */
int readBatteryMv() {
    int raw = analogRead(PIN_BATT_ADC);
    // ESP32 ADC: 0-4095 maps to 0-3.3V. With 1:1 divider, multiply by 2.
    // Calibration factor — adjust based on your actual measurements.
    float voltage = (raw / 4095.0) * 3.3 * 2.0;
    return (int)(voltage * 1000);
}

// ==========================================================================
// Wi-Fi connection
// ==========================================================================

bool connectWiFi() {
    Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 40) {
        delay(500);
        Serial.print(".");
        attempts++;
    }
    Serial.println();

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("[WiFi] Connected! IP: %s\n", WiFi.localIP().toString().c_str());
        return true;
    }

    Serial.println("[WiFi] Connection failed!");
    return false;
}

// ==========================================================================
// POST data to API
// ==========================================================================

bool postReading(const SoilReading& r, int batteryMv) {
    HTTPClient http;
    http.begin(API_URL);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(10000);

    // Build JSON payload
    char json[512];
    snprintf(json, sizeof(json),
        "{"
        "\"device_id\":\"%s\","
        "\"moisture\":%.1f,"
        "\"temperature\":%.1f,"
        "\"ec\":%.0f,"
        "\"ph\":%.2f,"
        "\"salinity\":%.0f,"
        "\"nitrogen\":%.0f,"
        "\"phosphorus\":%.0f,"
        "\"potassium\":%.0f,"
        "\"battery_mv\":%d"
        "}",
        DEVICE_ID,
        r.moisture, r.temperature, r.ec, r.ph,
        r.salinity, r.nitrogen, r.phosphorus, r.potassium,
        batteryMv
    );

    Serial.printf("[HTTP] POST %s\n", API_URL);
    Serial.printf("[HTTP] Body: %s\n", json);

    int httpCode = http.POST(json);

    if (httpCode == 201) {
        Serial.printf("[HTTP] Success (%d): %s\n", httpCode, http.getString().c_str());
        http.end();
        return true;
    }

    Serial.printf("[HTTP] Failed (%d): %s\n", httpCode, http.getString().c_str());
    http.end();
    return false;
}

// ==========================================================================
// Deep sleep
// ==========================================================================

void enterDeepSleep() {
    uint64_t sleepUs = (uint64_t)SLEEP_MINUTES * 60ULL * 1000000ULL;
    Serial.printf("[Sleep] Entering deep sleep for %d minutes...\n\n", SLEEP_MINUTES);
    Serial.flush();

    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);

    esp_sleep_enable_timer_wakeup(sleepUs);
    esp_deep_sleep_start();
}

// ==========================================================================
// Arduino setup & loop
// ==========================================================================

void setup() {
    // Debug serial
    Serial.begin(115200);
    delay(100);

    Serial.println("\n========================================");
    Serial.println("  Durian IoT — ESP32 + QC-S8 Prototype");
    Serial.println("========================================");

    // Configure pins
    pinMode(PIN_RS485_DE, OUTPUT);
    pinMode(PIN_SENSOR_EN, OUTPUT);
    digitalWrite(PIN_RS485_DE, LOW);   // Start in receive mode
    digitalWrite(PIN_SENSOR_EN, LOW);  // Sensor off initially

    // Step 1: Power on the sensor
    Serial.println("[Power] Enabling sensor power (MOSFET ON)...");
    digitalWrite(PIN_SENSOR_EN, HIGH);

    // Step 2: Initialize RS485 UART
    Serial2.begin(MODBUS_BAUD_RATE, SERIAL_8N1, PIN_RS485_RX, PIN_RS485_TX);

    // Step 3: Wait for sensor to stabilize after power-on
    Serial.println("[Sensor] Waiting 2s for QC-S8 to stabilize...");
    delay(2000);

    // Step 4: Read the sensor
    Serial.println("[Sensor] Reading QC-S8 via Modbus RTU...");
    SoilReading reading = readQCS8();

    // Retry once if the first read fails (common on cold start)
    if (!reading.valid) {
        Serial.println("[Sensor] Retrying in 1s...");
        delay(1000);
        reading = readQCS8();
    }

    // Step 5: Power off the sensor (save battery)
    Serial.println("[Power] Disabling sensor power (MOSFET OFF)...");
    digitalWrite(PIN_SENSOR_EN, LOW);

    if (!reading.valid) {
        Serial.println("[ERROR] Could not read sensor after retries. Going to sleep.");
        enterDeepSleep();
        return;
    }

    // Step 6: Read battery voltage (optional)
    int batteryMv = readBatteryMv();
    Serial.printf("[Battery] %d mV\n", batteryMv);

    // Step 7: Connect to Wi-Fi and send data
    if (connectWiFi()) {
        bool sent = postReading(reading, batteryMv);
        if (!sent) {
            Serial.println("[ERROR] Failed to send data. Will retry next cycle.");
        }
    } else {
        Serial.println("[ERROR] Wi-Fi failed. Will retry next cycle.");
    }

    // Step 8: Deep sleep
    enterDeepSleep();
}

void loop() {
    // Never reached — setup() ends with deep sleep
}
