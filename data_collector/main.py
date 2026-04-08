"""
Durian Garden IoT — Data Collector Service

Subscribes to ChirpStack MQTT events, decodes SE02-LB sensor payloads,
and stores readings in PostgreSQL for analysis.

Usage:
    python main.py

The service runs two threads:
    1. MQTT subscriber — receives and processes sensor data in real-time
    2. REST API server — provides HTTP endpoints for querying stored data

Configuration: see config.py or set environment variables.
"""

import json
import logging
import signal
import sys
import threading

import paho.mqtt.client as mqtt

import config
import database
from decoder import decode_base64_payload
from api import create_app

# ──────────────────────────────────────────────────────────────────────────
# Logging Setup
# ──────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("durian_collector")


# ──────────────────────────────────────────────────────────────────────────
# MQTT Callbacks
# ──────────────────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, reason_code, properties):
    """Called when MQTT connection is established."""
    logger.info("Connected to MQTT broker (rc=%s)", reason_code)

    # Subscribe to ChirpStack uplink events
    client.subscribe(config.MQTT_TOPIC_UPLINK)
    client.subscribe(config.MQTT_TOPIC_JOIN)
    client.subscribe(config.MQTT_TOPIC_STATUS)

    logger.info("Subscribed to: %s", config.MQTT_TOPIC_UPLINK)
    logger.info("Subscribed to: %s", config.MQTT_TOPIC_JOIN)
    logger.info("Subscribed to: %s", config.MQTT_TOPIC_STATUS)


def on_disconnect(client, userdata, flags, reason_code, properties):
    """Called when MQTT connection is lost."""
    logger.warning("Disconnected from MQTT broker (rc=%s). Will auto-reconnect.",
                   reason_code)


def on_message(client, userdata, msg):
    """
    Called for each incoming MQTT message from ChirpStack.

    ChirpStack v4 publishes JSON messages on topics like:
        application/{app_id}/device/{dev_eui}/event/up
        application/{app_id}/device/{dev_eui}/event/join
        application/{app_id}/device/{dev_eui}/event/status
    """
    try:
        topic = msg.topic
        payload = json.loads(msg.payload.decode("utf-8"))

        # Extract event type from topic
        topic_parts = topic.split("/")
        event_type = topic_parts[-1] if len(topic_parts) >= 6 else "unknown"

        if event_type == "up":
            handle_uplink(payload)
        elif event_type == "join":
            handle_join(payload)
        elif event_type == "status":
            handle_status(payload)
        else:
            logger.debug("Ignoring event type: %s", event_type)

    except json.JSONDecodeError:
        logger.error("Failed to parse MQTT message as JSON: %s", msg.payload[:200])
    except Exception:
        logger.exception("Error processing MQTT message on topic: %s", msg.topic)


# ──────────────────────────────────────────────────────────────────────────
# Event Handlers
# ──────────────────────────────────────────────────────────────────────────

def handle_uplink(payload: dict):
    """
    Process an uplink message (sensor data from SE02-LB).

    ChirpStack v4 uplink JSON structure:
    {
        "deviceInfo": {
            "devEui": "...",
            "deviceName": "...",
            ...
        },
        "data": "<base64 encoded payload>",
        "fPort": 2,
        "fCnt": 123,
        "rxInfo": [{"rssi": -70, "snr": 8.5, ...}],
        "txInfo": {"frequency": 923200000, "modulation": {...}},
        ...
    }
    """
    device_info = payload.get("deviceInfo", {})
    dev_eui = device_info.get("devEui", "unknown")
    device_name = device_info.get("deviceName", "")

    # Get base64 payload
    b64_data = payload.get("data")
    if not b64_data:
        logger.warning("Uplink from %s has no data payload", dev_eui)
        return

    f_port = payload.get("fPort", 0)
    f_cnt = payload.get("fCnt", 0)

    # Decode the SE02-LB payload
    try:
        reading = decode_base64_payload(b64_data)
    except ValueError as e:
        logger.error("Failed to decode payload from %s: %s", dev_eui, e)
        return

    # Extract LoRaWAN RF metadata
    rssi = None
    snr = None
    rx_info = payload.get("rxInfo", [])
    if rx_info:
        rssi = rx_info[0].get("rssi")
        snr = rx_info[0].get("snr")

    # Extract spreading factor from txInfo
    spreading_factor = None
    tx_info = payload.get("txInfo", {})
    modulation = tx_info.get("modulation", {})
    lora_mod = modulation.get("lora", {})
    if lora_mod:
        spreading_factor = lora_mod.get("spreadingFactor")

    logger.info(
        "📡 [%s] %s | Moisture: %.1f%% | Temp: %.1f°C | EC: %.0f µS/cm | "
        "Bat: %dmV | RSSI: %s dBm",
        dev_eui[-4:].upper(), device_name,
        reading.moisture_1, reading.temperature_1, reading.ec_1,
        reading.battery_mv, rssi
    )

    # Ensure device is registered
    device_id = database.get_device_id(dev_eui)
    if device_id is None:
        if config.AUTO_REGISTER_DEVICES:
            device_id = database.auto_register_device(dev_eui, device_name)
        else:
            logger.warning("Unknown device %s — skipping (auto-register disabled)",
                           dev_eui)
            return

    # Store the reading
    database.store_reading(
        device_id=device_id,
        dev_eui=dev_eui,
        reading=reading.to_dict(),
        rssi=rssi,
        snr=snr,
        spreading_factor=spreading_factor,
        f_cnt=f_cnt,
        raw_payload=reading.raw_hex,
    )

    # Update device status
    database.update_device_status(dev_eui, reading.battery_mv)

    # Check for low battery
    if reading.battery_mv < config.BATTERY_LOW_THRESHOLD_MV:
        logger.warning(
            "⚠️ LOW BATTERY on %s (%s): %dmV (threshold: %dmV)",
            device_name, dev_eui, reading.battery_mv,
            config.BATTERY_LOW_THRESHOLD_MV
        )
        database.store_device_event(
            dev_eui, "battery_low",
            {"battery_mv": reading.battery_mv}
        )


def handle_join(payload: dict):
    """Process a device join event (device connected to LoRaWAN network)."""
    device_info = payload.get("deviceInfo", {})
    dev_eui = device_info.get("devEui", "unknown")
    device_name = device_info.get("deviceName", "")

    logger.info("🔗 Device JOIN: %s (%s)", device_name, dev_eui)

    # Auto-register if needed
    if config.AUTO_REGISTER_DEVICES:
        database.auto_register_device(dev_eui, device_name)

    database.store_device_event(dev_eui, "join", {"device_name": device_name})


def handle_status(payload: dict):
    """Process a device status event."""
    device_info = payload.get("deviceInfo", {})
    dev_eui = device_info.get("devEui", "unknown")

    logger.info("ℹ️ Device STATUS: %s — %s", dev_eui, json.dumps(payload)[:200])

    database.store_device_event(dev_eui, "status", payload)


# ──────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────────────────────────────────

def main():
    """Start the data collector: MQTT subscriber + REST API."""
    logger.info("=" * 60)
    logger.info("  Durian Garden IoT — Data Collector")
    logger.info("  Year 1: Data Collection Phase")
    logger.info("=" * 60)

    # Initialize database
    database.init_db()
    logger.info("Database initialized")

    # Setup MQTT client
    mqtt_client = mqtt.Client(
        client_id=config.MQTT_CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.on_message = on_message

    # Connect to MQTT broker
    logger.info("Connecting to MQTT broker at %s:%d...",
                config.MQTT_BROKER_HOST, config.MQTT_BROKER_PORT)
    mqtt_client.connect(config.MQTT_BROKER_HOST, config.MQTT_BROKER_PORT, keepalive=60)

    # Start MQTT loop in background thread
    mqtt_client.loop_start()
    logger.info("MQTT subscriber started — listening for sensor data")

    # Start REST API in a separate thread
    app = create_app()
    api_thread = threading.Thread(
        target=lambda: app.run(
            host=config.API_HOST,
            port=config.API_PORT,
            debug=False,
            use_reloader=False,
        ),
        daemon=True,
    )
    api_thread.start()
    logger.info("REST API started on http://%s:%d", config.API_HOST, config.API_PORT)

    # Graceful shutdown handler
    def shutdown(signum, frame):
        logger.info("Shutting down...")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        database.close_db()
        logger.info("Goodbye!")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Keep main thread alive
    logger.info("Data collector is running. Press Ctrl+C to stop.")
    signal.pause()


if __name__ == "__main__":
    main()
