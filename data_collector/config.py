"""
Configuration for the Durian Garden IoT Data Collector.

Environment variables override defaults. Use a .env file for local development.
"""

import os
from dotenv import load_dotenv

load_dotenv()


# ──────────────────────────────────────────────────────────────────────────
# MQTT (ChirpStack publishes sensor data here)
# ──────────────────────────────────────────────────────────────────────────
MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "localhost")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "durian-data-collector")

# ChirpStack v4 MQTT topic pattern for uplink events
# '#' subscribes to all applications and devices
MQTT_TOPIC_UPLINK = os.getenv(
    "MQTT_TOPIC_UPLINK",
    "application/+/device/+/event/up"
)

# Also listen for join events and device status
MQTT_TOPIC_JOIN = "application/+/device/+/event/join"
MQTT_TOPIC_STATUS = "application/+/device/+/event/status"

# ──────────────────────────────────────────────────────────────────────────
# PostgreSQL
# ──────────────────────────────────────────────────────────────────────────
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "durian_iot")
DB_USER = os.getenv("DB_USER", "durian")
DB_PASSWORD = os.getenv("DB_PASSWORD", "durian_iot_2026")
DB_SCHEMA = "durian"

# ──────────────────────────────────────────────────────────────────────────
# Data Collector Settings
# ──────────────────────────────────────────────────────────────────────────

# Battery voltage threshold for low battery warning (millivolts)
BATTERY_LOW_THRESHOLD_MV = 3200

# Auto-register unknown devices when they first send data
AUTO_REGISTER_DEVICES = True

# ──────────────────────────────────────────────────────────────────────────
# REST API
# ──────────────────────────────────────────────────────────────────────────
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "5000"))
API_DEBUG = os.getenv("API_DEBUG", "false").lower() == "true"
