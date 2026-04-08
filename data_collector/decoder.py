"""
SE02-LB LoRaWAN Payload Decoder

Decodes the raw byte payload from Dragino SE02-LB soil moisture & EC sensors.

The SE02-LB has TWO soil sensor probes, each measuring:
  - Soil Moisture (%)
  - Soil Temperature (°C)
  - Soil Electrical Conductivity (µS/cm)

Payload format (SE02-LB, 14 bytes on fPort=2):
  ┌──────────┬────────────┬───────────────────────────────────────────────┐
  │ Byte(s)  │ Field      │ Description                                   │
  ├──────────┼────────────┼───────────────────────────────────────────────┤
  │ 0-1      │ BAT        │ Battery voltage (mV), uint16 big-endian       │
  │ 2-3      │ MOIS_1     │ Soil moisture CH1 (×100 = %), uint16 BE       │
  │ 4-5      │ TEMP_1     │ Soil temperature CH1 (×100 = °C), int16 BE    │
  │ 6-7      │ EC_1       │ Soil conductivity CH1 (µS/cm), uint16 BE      │
  │ 8-9      │ MOIS_2     │ Soil moisture CH2 (×100 = %), uint16 BE       │
  │ 10-11    │ TEMP_2     │ Soil temperature CH2 (×100 = °C), int16 BE    │
  │ 12-13    │ EC_2       │ Soil conductivity CH2 (µS/cm), uint16 BE      │
  └──────────┴────────────┴───────────────────────────────────────────────┘

IMPORTANT: Verify this format against the actual SE02-LB datasheet when
you receive the sensors. Dragino may use slightly different byte orders
or scaling between firmware versions.

Reference: https://www.dragino.com/products/agriculture-weather-station/item/335-se02-lb.html
"""

import base64
import struct
import logging

logger = logging.getLogger(__name__)


class SE02LBReading:
    """Decoded sensor reading from an SE02-LB sensor."""

    def __init__(self):
        self.battery_mv: int = 0
        self.moisture_1: float = 0.0      # %
        self.temperature_1: float = 0.0   # °C
        self.ec_1: float = 0.0            # µS/cm
        self.moisture_2: float = 0.0      # %
        self.temperature_2: float = 0.0   # °C
        self.ec_2: float = 0.0            # µS/cm
        self.raw_hex: str = ""

    def __repr__(self):
        return (
            f"SE02LB("
            f"bat={self.battery_mv}mV, "
            f"CH1: moist={self.moisture_1}%, temp={self.temperature_1}°C, "
            f"ec={self.ec_1}µS/cm | "
            f"CH2: moist={self.moisture_2}%, temp={self.temperature_2}°C, "
            f"ec={self.ec_2}µS/cm)"
        )

    def to_dict(self) -> dict:
        return {
            "battery_mv": self.battery_mv,
            "moisture_1": self.moisture_1,
            "temperature_1": self.temperature_1,
            "ec_1": self.ec_1,
            "moisture_2": self.moisture_2,
            "temperature_2": self.temperature_2,
            "ec_2": self.ec_2,
            "raw_hex": self.raw_hex,
        }


def decode_se02lb(payload_bytes: bytes) -> SE02LBReading:
    """
    Decode raw SE02-LB payload bytes into a structured reading.

    Args:
        payload_bytes: Raw payload bytes (14 bytes expected).

    Returns:
        SE02LBReading with decoded values.

    Raises:
        ValueError: If payload is too short or contains invalid data.
    """
    reading = SE02LBReading()
    reading.raw_hex = payload_bytes.hex()

    if len(payload_bytes) < 8:
        raise ValueError(
            f"Payload too short: {len(payload_bytes)} bytes "
            f"(minimum 8 for single-channel). Hex: {reading.raw_hex}"
        )

    # Battery voltage (uint16, big-endian, mV)
    reading.battery_mv = struct.unpack(">H", payload_bytes[0:2])[0]

    # Channel 1
    raw_mois_1 = struct.unpack(">H", payload_bytes[2:4])[0]
    raw_temp_1 = struct.unpack(">h", payload_bytes[4:6])[0]  # signed
    raw_ec_1 = struct.unpack(">H", payload_bytes[6:8])[0]

    reading.moisture_1 = raw_mois_1 / 100.0
    reading.temperature_1 = raw_temp_1 / 100.0
    reading.ec_1 = float(raw_ec_1)

    # Channel 2 (if payload is long enough)
    if len(payload_bytes) >= 14:
        raw_mois_2 = struct.unpack(">H", payload_bytes[8:10])[0]
        raw_temp_2 = struct.unpack(">h", payload_bytes[10:12])[0]
        raw_ec_2 = struct.unpack(">H", payload_bytes[12:14])[0]

        reading.moisture_2 = raw_mois_2 / 100.0
        reading.temperature_2 = raw_temp_2 / 100.0
        reading.ec_2 = float(raw_ec_2)
    else:
        logger.debug("Payload has no channel 2 data (only %d bytes)", len(payload_bytes))

    # Sanity checks
    if reading.moisture_1 > 100:
        logger.warning(
            "Moisture CH1 out of range: %.2f%% (raw: %d). "
            "Check decoder format against SE02-LB datasheet.",
            reading.moisture_1, raw_mois_1
        )

    if reading.temperature_1 < -40 or reading.temperature_1 > 85:
        logger.warning(
            "Temperature CH1 out of range: %.2f°C. "
            "Possible sensor fault or decoder mismatch.",
            reading.temperature_1
        )

    return reading


def decode_base64_payload(b64_payload: str) -> SE02LBReading:
    """
    Decode a base64-encoded SE02-LB payload (as received from ChirpStack MQTT).

    Args:
        b64_payload: Base64-encoded payload string.

    Returns:
        SE02LBReading with decoded values.
    """
    payload_bytes = base64.b64decode(b64_payload)
    return decode_se02lb(payload_bytes)


# ──────────────────────────────────────────────────────────────────────────
# ChirpStack v4 codec function (can be used as a device profile codec)
# ──────────────────────────────────────────────────────────────────────────

# This JavaScript decoder can be pasted into ChirpStack's device profile
# as a codec function, so ChirpStack itself decodes the payload:
CHIRPSTACK_CODEC_JS = """
// SE02-LB Decoder for ChirpStack v4 Device Profile
// Paste this into: Device Profile → Codec → Decode (JavaScript)

function decodeUplink(input) {
    var bytes = input.bytes;
    var data = {};

    // Battery voltage (mV)
    data.battery_mv = (bytes[0] << 8) | bytes[1];

    // Channel 1
    data.moisture_1 = ((bytes[2] << 8) | bytes[3]) / 100.0;
    var temp1_raw = (bytes[4] << 8) | bytes[5];
    if (temp1_raw > 32767) temp1_raw -= 65536;  // signed
    data.temperature_1 = temp1_raw / 100.0;
    data.ec_1 = (bytes[6] << 8) | bytes[7];

    // Channel 2 (if available)
    if (bytes.length >= 14) {
        data.moisture_2 = ((bytes[8] << 8) | bytes[9]) / 100.0;
        var temp2_raw = (bytes[10] << 8) | bytes[11];
        if (temp2_raw > 32767) temp2_raw -= 65536;
        data.temperature_2 = temp2_raw / 100.0;
        data.ec_2 = (bytes[12] << 8) | bytes[13];
    }

    return { data: data };
}
"""
