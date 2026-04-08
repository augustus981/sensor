"""
Durian Garden IoT — REST API

Provides HTTP endpoints for querying sensor data and receiving
direct Wi-Fi submissions from ESP32 sensor nodes.

Endpoints:
    GET  /api/health              — Service health check
    POST /api/readings            — Submit sensor reading (ESP32 Wi-Fi direct)
    GET  /api/devices             — List all registered devices
    GET  /api/readings/latest     — Latest reading from each device
    GET  /api/readings/<dev_eui>  — Readings for a specific device
    GET  /api/readings/<dev_eui>/daily — Daily averages for a device
    GET  /api/zones/summary       — Zone-level aggregated data
    GET  /api/export/<dev_eui>    — Export readings as CSV
"""

import csv
import io
import logging
from datetime import datetime

from flask import Flask, jsonify, request, Response
from flask_cors import CORS

import database

logger = logging.getLogger(__name__)

_WIFI_READING_FIELDS = {
    "moisture", "temperature", "ec", "ph",
    "salinity", "nitrogen", "phosphorus", "potassium", "battery_mv",
}


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    CORS(app)  # Allow cross-origin requests for future dashboard

    # ──────────────────────────────────────────────────────────────────
    # Health Check
    # ──────────────────────────────────────────────────────────────────

    @app.route("/api/health")
    def health():
        return jsonify({
            "status": "ok",
            "service": "durian-iot-data-collector",
            "phase": "year-1-data-collection",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })

    # ──────────────────────────────────────────────────────────────────
    # Wi-Fi Direct Ingestion (ESP32 → HTTP POST)
    # ──────────────────────────────────────────────────────────────────

    @app.route("/api/readings", methods=["POST"])
    def submit_reading():
        """
        Receive a sensor reading from an ESP32 over Wi-Fi.

        Expected JSON body:
        {
            "device_id": "esp32-qcs8-0001",
            "moisture": 45.2,
            "temperature": 28.5,
            "ec": 350,
            "ph": 6.8,
            "salinity": 280,
            "nitrogen": 120,
            "phosphorus": 45,
            "potassium": 180,
            "battery_mv": 3850
        }
        """
        try:
            data = request.get_json(silent=True)
            if not data:
                return jsonify({"error": "Request body must be JSON"}), 400

            dev_eui = data.get("device_id")
            if not dev_eui:
                return jsonify({"error": "Missing required field: device_id"}), 400

            reading = {k: data.get(k) for k in _WIFI_READING_FIELDS if data.get(k) is not None}
            if not reading:
                return jsonify({"error": "No sensor values provided"}), 400

            device_id = database.get_device_id(dev_eui)
            if device_id is None:
                device_id = database.auto_register_wifi_device(dev_eui)

            database.store_wifi_reading(device_id, dev_eui, reading)

            battery_mv = reading.get("battery_mv")
            if battery_mv:
                database.update_device_status(dev_eui, battery_mv)

            logger.info(
                "[WiFi] %s | M:%.1f%% T:%.1f°C EC:%.0f pH:%s N:%s P:%s K:%s",
                dev_eui,
                reading.get("moisture", 0),
                reading.get("temperature", 0),
                reading.get("ec", 0),
                reading.get("ph", "-"),
                reading.get("nitrogen", "-"),
                reading.get("phosphorus", "-"),
                reading.get("potassium", "-"),
            )

            return jsonify({"status": "ok", "device_id": dev_eui}), 201

        except Exception as e:
            logger.exception("Error storing Wi-Fi reading")
            return jsonify({"error": str(e)}), 500

    # ──────────────────────────────────────────────────────────────────
    # Devices
    # ──────────────────────────────────────────────────────────────────

    @app.route("/api/devices")
    def list_devices():
        """List all registered sensor devices."""
        try:
            devices = database.get_all_devices()
            return jsonify({
                "count": len(devices),
                "devices": _serialize_rows(devices),
            })
        except Exception as e:
            logger.exception("Error fetching devices")
            return jsonify({"error": str(e)}), 500

    # ──────────────────────────────────────────────────────────────────
    # Readings
    # ──────────────────────────────────────────────────────────────────

    @app.route("/api/readings/latest")
    def latest_readings():
        """Get the most recent reading from each device."""
        try:
            readings = database.get_latest_readings()
            return jsonify({
                "count": len(readings),
                "readings": _serialize_rows(readings),
            })
        except Exception as e:
            logger.exception("Error fetching latest readings")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/readings/<dev_eui>")
    def device_readings(dev_eui):
        """
        Get readings for a specific device.

        Query params:
            hours (int): Time window in hours (default: 24)
            limit (int): Max number of readings (default: 1000)
        """
        try:
            hours = request.args.get("hours", 24, type=int)
            limit = request.args.get("limit", 1000, type=int)

            readings = database.get_device_readings(dev_eui, hours=hours, limit=limit)
            return jsonify({
                "dev_eui": dev_eui,
                "hours": hours,
                "count": len(readings),
                "readings": _serialize_rows(readings),
            })
        except Exception as e:
            logger.exception("Error fetching readings for %s", dev_eui)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/readings/<dev_eui>/daily")
    def daily_averages(dev_eui):
        """
        Get daily averages for a device.

        Query params:
            days (int): Number of days to look back (default: 30)
        """
        try:
            days = request.args.get("days", 30, type=int)

            averages = database.get_daily_averages(dev_eui, days=days)
            return jsonify({
                "dev_eui": dev_eui,
                "days": days,
                "count": len(averages),
                "averages": _serialize_rows(averages),
            })
        except Exception as e:
            logger.exception("Error fetching daily averages for %s", dev_eui)
            return jsonify({"error": str(e)}), 500

    # ──────────────────────────────────────────────────────────────────
    # Zones
    # ──────────────────────────────────────────────────────────────────

    @app.route("/api/zones/summary")
    def zone_summary():
        """Get aggregated readings per zone."""
        try:
            summary = database.get_zone_summary()
            return jsonify({
                "count": len(summary),
                "zones": _serialize_rows(summary),
            })
        except Exception as e:
            logger.exception("Error fetching zone summary")
            return jsonify({"error": str(e)}), 500

    # ──────────────────────────────────────────────────────────────────
    # CSV Export
    # ──────────────────────────────────────────────────────────────────

    @app.route("/api/export/<dev_eui>")
    def export_csv(dev_eui):
        """
        Export readings as CSV for analysis in Excel/Google Sheets.

        Query params:
            hours (int): Time window in hours (default: 720 = 30 days)
        """
        try:
            hours = request.args.get("hours", 720, type=int)
            readings = database.get_device_readings(dev_eui, hours=hours, limit=100000)

            if not readings:
                return jsonify({"error": "No readings found"}), 404

            # Build CSV
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=readings[0].keys())
            writer.writeheader()
            for row in readings:
                # Convert datetime objects to strings
                serialized = {}
                for k, v in row.items():
                    serialized[k] = v.isoformat() if isinstance(v, datetime) else v
                writer.writerow(serialized)

            csv_data = output.getvalue()

            return Response(
                csv_data,
                mimetype="text/csv",
                headers={
                    "Content-Disposition":
                        f"attachment; filename=durian_iot_{dev_eui}_{datetime.utcnow().strftime('%Y%m%d')}.csv"
                },
            )
        except Exception as e:
            logger.exception("Error exporting CSV for %s", dev_eui)
            return jsonify({"error": str(e)}), 500

    return app


def _serialize_rows(rows: list) -> list:
    """Convert psycopg2 RealDictRow objects to JSON-serializable dicts."""
    result = []
    for row in rows:
        item = {}
        for key, value in row.items():
            if isinstance(value, datetime):
                item[key] = value.isoformat() + "Z"
            else:
                item[key] = value
        result.append(item)
    return result
