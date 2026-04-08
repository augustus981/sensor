# ESP32 Soil Sensor Node — Circuit Blueprint

## Components

| # | Component | Qty |
|---|---|---|
| 1 | ESP32-WROOM-32 38-Pin DevKit (Type-C) | 1 |
| 2 | QC-S8 Soil Sensor (7-in-1, RS485) | 1 |
| 3 | UART TTL to RS485 Module (3-5V) | 1 |
| 4 | MT3608 Boost Converter (adjusted to 5V) | 1 |
| 5 | TP4056 Charging Module (with protection IC) | 1 |
| 6 | 18650 Battery + Holder (single cell) | 1 |
| 7 | IRLZ44N N-Channel MOSFET (TO-220) | 1 |
| 8 | 10kΩ Resistor | 1 |

## Circuit Diagram

```
                        ┌─────────────────────────────────────────────┐
                        │              ESP32 DevKit                   │
                        │                                             │
  ┌─────────────────────┤ VIN (5V)                        GPIO17 (TX2)├──────────► RS485 Module DI
  │                     │                                             │
  │                     │ GND ──┬──────────────────────── GPIO16 (RX2)├──────────► RS485 Module RO
  │                     │       │                                     │
  │                     │       │                          GPIO4      ├──────────► RS485 Module DE & RE
  │                     │       │                                     │
  │                     │       │                          GPIO27     ├──────┐
  │                     │       │                                     │      │
  │                     └───────┼─────────────────────────────────────┘      │
  │                             │                                            │
  │                             │ COMMON GND BUS                             │
  │                             │ ════════════════════════════               │
  │                             │                           ║                │
  │  ┌──────────┐    ┌─────────┴────────┐                  ║          ┌──────┴───────┐
  │  │ 18650    │    │ TP4056 Module    │                  ║          │  IRLZ44N     │
  │  │ Battery  │    │                  │                  ║          │  (MOSFET)    │
  │  │ in       ├────┤ B+          OUT+ ├──► MT3608 IN+    ║          │              │
  │  │ Holder   │    │                  │                  ║   ┌──────┤ Gate         │
  │  │          ├────┤ B-          OUT- ├──► MT3608 IN-    ║   │      │              │
  │  └──────────┘    └─────────────────┘   (GND)   ║       ║   │      │ Drain ───────╫──► SENSOR GND LINE
  │                                                ║       ║   │      │              │    (see below)
  │                    ┌──────────────────┐        ║       ║   │      │ Source ──────╫──► GND BUS
  │                    │ MT3608 Boost     │        ║       ║   │      └──────────────┘
  │                    │ (set to 5V out)  │        ║       ║   │
  └────────────────────┤ OUT+         IN+├────◄────╝       ║   ├───── 10kΩ Resistor ──► GND BUS
                       │                  │                ║   │
      5V RAIL ════════►│ OUT-         IN-├────◄────════════╝   │
                       └──────────────────┘                    │
                                                               │
  GPIO27 ──────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────┐
  │                    RS485 Module (TTL side)                       │
  │                                                                  │
  │  VCC ◄──── 5V RAIL (from MT3608 OUT+)                           │
  │  GND ─────► MOSFET Drain (switched GND)                         │
  │  DI  ◄──── ESP32 GPIO17 (TX2)                                   │
  │  RO  ─────► ESP32 GPIO16 (RX2)                                  │
  │  DE  ◄──┬─ ESP32 GPIO4                                          │
  │  RE  ◄──┘  (tied together)                                      │
  │                                                                  │
  │                    RS485 Module (RS485 side)                     │
  │  A ◄──────────────► QC-S8 Sensor A                              │
  │  B ◄──────────────► QC-S8 Sensor B                              │
  └──────────────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────┐
  │                    QC-S8 Soil Sensor                             │
  │                                                                  │
  │  VCC (red)  ◄──── 5V RAIL (from MT3608 OUT+)                    │
  │  GND (black) ────► MOSFET Drain (switched GND)                  │
  │  A   (yellow) ◄──► RS485 Module A                               │
  │  B   (blue)   ◄──► RS485 Module B                               │
  └──────────────────────────────────────────────────────────────────┘
```

## Pin-by-Pin Connection Table

### ESP32 DevKit

| ESP32 Pin | Connects To | Wire Color (suggested) |
|-----------|------------|----------------------|
| VIN (5V) | MT3608 OUT+ | Red |
| GND | Common GND bus | Black |
| GPIO17 (TX2) | RS485 Module DI | Green |
| GPIO16 (RX2) | RS485 Module RO | Yellow |
| GPIO4 | RS485 Module DE + RE (tied together) | Orange |
| GPIO27 | IRLZ44N Gate + 10kΩ to GND | Blue |

### TP4056 Module

| TP4056 Pin | Connects To |
|-----------|------------|
| B+ | 18650 holder red wire (+) |
| B- | 18650 holder black wire (-) |
| OUT+ | MT3608 IN+ |
| OUT- | MT3608 IN- (GND bus) |
| USB | For charging (plug in USB cable) |

### MT3608 Boost Converter

| MT3608 Pin | Connects To |
|-----------|------------|
| IN+ | TP4056 OUT+ |
| IN- | TP4056 OUT- (GND bus) |
| OUT+ | 5V rail → ESP32 VIN, Sensor VCC, RS485 VCC |
| OUT- | GND bus |

> **IMPORTANT**: Before connecting anything, adjust the MT3608 trimpot
> with a multimeter to output exactly 5.0V. Power it from USB or battery
> and turn the screw until output reads 5V.

### IRLZ44N MOSFET (TO-220, facing label side)

```
  ┌───────────┐
  │  IRLZ44N  │
  │           │
  │  (label)  │
  │           │
  └─┬───┬───┬┘
    │   │   │
    G   D   S
    │   │   │
    │   │   └──► GND bus (common ground)
    │   │
    │   └──────► Sensor GND + RS485 Module GND (switched ground)
    │
    ├──────────► ESP32 GPIO27
    │
    └── 10kΩ ──► GND bus
```

- **Gate (G)**: Left pin — connects to ESP32 GPIO27 and 10kΩ resistor to GND
- **Drain (D)**: Center pin — connects to QC-S8 sensor GND and RS485 module GND
- **Source (S)**: Right pin — connects to common GND bus

### RS485 TTL Module

| RS485 Pin (TTL side) | Connects To |
|---------------------|------------|
| VCC | MT3608 OUT+ (5V) |
| GND | IRLZ44N Drain (switched GND) |
| DI | ESP32 GPIO17 (TX2) |
| RO | ESP32 GPIO16 (RX2) |
| DE | ESP32 GPIO4 (tied to RE) |
| RE | ESP32 GPIO4 (tied to DE) |

| RS485 Pin (bus side) | Connects To |
|---------------------|------------|
| A | QC-S8 Sensor wire A |
| B | QC-S8 Sensor wire B |

### QC-S8 Soil Sensor

| Sensor Wire | Connects To |
|------------|------------|
| VCC (red) | MT3608 OUT+ (5V) |
| GND (black) | IRLZ44N Drain (switched GND) |
| A (yellow) | RS485 Module A |
| B (blue) | RS485 Module B |

> Wire colors may vary — check your sensor's datasheet.

## Power Flow

```
[18650 3.7V] → [TP4056 charge/protect] → [MT3608 boost to 5V] → 5V rail
                                                                    │
                                              ┌─────────────────────┼────────────┐
                                              │                     │            │
                                          ESP32 VIN          Sensor VCC    RS485 VCC
                                              │                     │            │
                                          ESP32 GND            Sensor GND   RS485 GND
                                              │                     │            │
                                              │                     └─────┬──────┘
                                              │                           │
                                              │                    IRLZ44N Drain
                                              │                           │
                                              │                    IRLZ44N Source
                                              │                           │
                                              └───────────────────────────┘
                                                        Common GND bus
```

## How It Works

1. **Battery → TP4056**: Charges the 18650 via USB, provides over-discharge protection
2. **TP4056 → MT3608**: Boosts 3.7V to 5V for all components
3. **5V → ESP32 VIN**: Powers the ESP32 through its onboard 3.3V regulator
4. **5V → Sensor + RS485**: Powers the sensor subsystem
5. **MOSFET on GND path**: ESP32 GPIO27 HIGH = sensor ON, LOW = sensor OFF
6. **10kΩ pull-down**: Ensures MOSFET stays OFF during ESP32 boot/reset/deep-sleep

## Assembly Without Soldering

All connections can be made with **female-to-female Dupont jumper wires**:

- ESP32 DevKit: female jumpers onto pin headers
- RS485 module: female jumpers onto pin headers
- MT3608 module: female jumpers onto pin headers (or solder wires to pads)
- TP4056 module: female jumpers onto pads (may need to solder header pins on)
- IRLZ44N MOSFET: female jumpers onto the 3 legs
- 10kΩ Resistor: twist one leg onto MOSFET Gate leg, other leg into GND jumper
- QC-S8 Sensor: typically comes with bare wires — use screw terminals or twist into jumpers

**Tip**: For the resistor, bend its legs into hooks, hook one onto the MOSFET Gate
leg and the other onto the Source leg (GND). Then press the female jumper connector
over both the MOSFET leg + resistor leg together. This makes a secure no-solder joint.

## Pre-Power Checklist

- [ ] MT3608 output adjusted to 5.0V with multimeter BEFORE connecting other components
- [ ] TP4056 is the version WITH protection IC (2 ICs visible on board)
- [ ] 18650 battery holder is single-cell (not series)
- [ ] IRLZ44N variant selected (not IRFZ44N)
- [ ] RS485 module DE and RE pins tied together to same ESP32 GPIO
- [ ] Double-check no short circuits between 5V rail and GND

## Firmware

The firmware is in `firmware/esp32_qcs8_wifi/esp32_qcs8_wifi.ino`.

### Before Flashing — Edit These Values

Open the `.ino` file and update the configuration section at the top:

```cpp
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* API_URL       = "http://YOUR_SERVER_IP:5000/api/readings";
const char* DEVICE_ID     = "esp32-qcs8-0001";
const int   SLEEP_MINUTES = 15;
```

### Flashing with Arduino IDE

1. Install Arduino IDE and add ESP32 board support:
   - File → Preferences → Additional Board Manager URLs:
     `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
   - Tools → Board Manager → search "esp32" → install
2. Select board: Tools → Board → ESP32 Dev Module
3. Select port: Tools → Port → (your ESP32 serial port)
4. Upload speed: 921600
5. Open `firmware/esp32_qcs8_wifi/esp32_qcs8_wifi.ino`
6. Click Upload

### Serial Monitor

Open Serial Monitor at **115200 baud** to see debug output:
```
========================================
  Durian IoT — ESP32 + QC-S8 Prototype
========================================
[Power] Enabling sensor power (MOSFET ON)...
[Sensor] Waiting 2s for QC-S8 to stabilize...
[Sensor] Reading QC-S8 via Modbus RTU...
[QC-S8] Reading successful:
  Moisture:    45.2 %
  Temperature: 28.5 °C
  EC:          350 µS/cm
  pH:          6.80
  Nitrogen:    120 mg/kg
  Phosphorus:  45 mg/kg
  Potassium:   180 mg/kg
[Power] Disabling sensor power (MOSFET OFF)...
[WiFi] Connecting to MyNetwork...
[WiFi] Connected! IP: 192.168.1.100
[HTTP] POST http://192.168.1.50:5000/api/readings
[HTTP] Success (201)
[Sleep] Entering deep sleep for 15 minutes...
```

### Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `[Modbus] Timeout` | Wrong baud rate or wiring | Try `9600` instead of `4800`. Check A/B wires. |
| `[Modbus] CRC mismatch` | Noise on RS485 line | Shorter wires, check connections |
| `[WiFi] Connection failed` | Wrong SSID/password | Double-check credentials |
| `[HTTP] Failed (-1)` | Server not reachable | Check server IP, firewall, is API running? |
| No output on Serial Monitor | Wrong baud rate in monitor | Set to 115200 |
| ESP32 not detected on Mac | Charge-only USB cable | Use a data cable |

### Modbus Register Map

The firmware assumes this register layout (common for QC-S8 type sensors).
**Verify against your sensor's datasheet** and update `readQCS8()` if different:

| Register | Parameter | Scaling |
|----------|-----------|---------|
| 0x0000 | Moisture | ÷10 = % |
| 0x0001 | Temperature | ÷10 = °C (signed) |
| 0x0002 | Conductivity | raw µS/cm |
| 0x0003 | pH | ÷100 |
| 0x0004 | Nitrogen | raw mg/kg |
| 0x0005 | Phosphorus | raw mg/kg |
| 0x0006 | Potassium | raw mg/kg |
