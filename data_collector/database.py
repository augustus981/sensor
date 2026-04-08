"""
Database operations for the Durian Garden IoT Data Collector.

Handles connection pooling, sensor reading storage, and queries.
"""

import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional

import psycopg2
import psycopg2.pool
import psycopg2.extras

import config

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────
# Connection Pool
# ──────────────────────────────────────────────────────────────────────────

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


def init_db():
    """Initialize the database connection pool."""
    global _pool
    _pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=2,
        maxconn=10,
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
    )
    logger.info("Database connection pool initialized (%s:%s/%s)",
                config.DB_HOST, config.DB_PORT, config.DB_NAME)


def close_db():
    """Close all database connections."""
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("Database connection pool closed")


@contextmanager
def get_conn():
    """Get a database connection from the pool."""
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


# ──────────────────────────────────────────────────────────────────────────
# Device Operations
# ──────────────────────────────────────────────────────────────────────────

def get_device_id(dev_eui: str) -> Optional[int]:
    """Look up a device's internal ID by its DevEUI."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM durian.devices WHERE dev_eui = %s",
                (dev_eui.lower(),)
            )
            row = cur.fetchone()
            return row[0] if row else None


def auto_register_device(dev_eui: str, name: str = None) -> int:
    """
    Auto-register an unknown device when it first sends data.
    Returns the new device ID.
    """
    if name is None:
        name = f"SE02-LB-{dev_eui[-4:].upper()}"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO durian.devices (dev_eui, name, device_model)
                VALUES (%s, %s, 'SE02-LB')
                ON CONFLICT (dev_eui) DO UPDATE SET updated_at = NOW()
                RETURNING id
                """,
                (dev_eui.lower(), name)
            )
            device_id = cur.fetchone()[0]
            logger.info("Auto-registered device: %s (id=%d, name=%s)",
                        dev_eui, device_id, name)
            return device_id


def update_device_status(dev_eui: str, battery_mv: int):
    """Update device last_seen and battery status."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE durian.devices
                SET last_seen_at = NOW(), battery_mv = %s, updated_at = NOW()
                WHERE dev_eui = %s
                """,
                (battery_mv, dev_eui.lower())
            )


# ──────────────────────────────────────────────────────────────────────────
# Sensor Reading Storage
# ──────────────────────────────────────────────────────────────────────────

def store_reading(
    device_id: int,
    dev_eui: str,
    reading: dict,
    rssi: int = None,
    snr: float = None,
    spreading_factor: int = None,
    f_cnt: int = None,
    raw_payload: str = None,
):
    """
    Store a decoded sensor reading in the database.

    Args:
        device_id: Internal device ID.
        dev_eui: LoRaWAN Device EUI.
        reading: Decoded SE02-LB reading dict.
        rssi: Signal strength (dBm).
        snr: Signal-to-noise ratio (dB).
        spreading_factor: LoRa spreading factor.
        f_cnt: Frame counter.
        raw_payload: Raw hex payload for debugging.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO durian.sensor_readings (
                    device_id, dev_eui, received_at,
                    moisture_1, temperature_1, ec_1,
                    moisture_2, temperature_2, ec_2,
                    battery_mv, rssi, snr, spreading_factor,
                    f_cnt, raw_payload
                ) VALUES (
                    %s, %s, NOW(),
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s
                )
                """,
                (
                    device_id, dev_eui.lower(),
                    reading.get("moisture_1"),
                    reading.get("temperature_1"),
                    reading.get("ec_1"),
                    reading.get("moisture_2"),
                    reading.get("temperature_2"),
                    reading.get("ec_2"),
                    reading.get("battery_mv"),
                    rssi, snr, spreading_factor,
                    f_cnt, raw_payload,
                )
            )
    logger.debug("Stored reading for device %s", dev_eui)


def store_wifi_reading(device_id: int, dev_eui: str, reading: dict):
    """
    Store a sensor reading submitted directly over Wi-Fi (QC-S8 sensor).

    Args:
        device_id: Internal device ID.
        dev_eui: Device identifier string.
        reading: Dict with keys: moisture, temperature, ec, ph,
                 salinity, nitrogen, phosphorus, potassium, battery_mv.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO durian.sensor_readings (
                    device_id, dev_eui, received_at,
                    moisture_1, temperature_1, ec_1,
                    ph, salinity,
                    nitrogen_mg_kg, phosphorus_mg_kg, potassium_mg_kg,
                    battery_mv
                ) VALUES (
                    %s, %s, NOW(),
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s
                )
                """,
                (
                    device_id, dev_eui.lower(),
                    reading.get("moisture"),
                    reading.get("temperature"),
                    reading.get("ec"),
                    reading.get("ph"),
                    reading.get("salinity"),
                    reading.get("nitrogen"),
                    reading.get("phosphorus"),
                    reading.get("potassium"),
                    reading.get("battery_mv"),
                )
            )
    logger.debug("Stored Wi-Fi reading for device %s", dev_eui)


def auto_register_wifi_device(dev_eui: str, name: str = None) -> int:
    """
    Auto-register a Wi-Fi-connected device (e.g. ESP32 + QC-S8).
    Returns the device ID.
    """
    if name is None:
        name = f"QC-S8-{dev_eui[-4:].upper()}"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO durian.devices (dev_eui, name, device_model, connection_type)
                VALUES (%s, %s, 'QC-S8', 'wifi')
                ON CONFLICT (dev_eui) DO UPDATE SET updated_at = NOW()
                RETURNING id
                """,
                (dev_eui.lower(), name)
            )
            device_id = cur.fetchone()[0]
            logger.info("Auto-registered Wi-Fi device: %s (id=%d, name=%s)",
                        dev_eui, device_id, name)
            return device_id


def store_device_event(dev_eui: str, event_type: str, event_data: dict = None):
    """Store a device lifecycle event."""
    device_id = get_device_id(dev_eui)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO durian.device_events (device_id, dev_eui, event_type, event_data)
                VALUES (%s, %s, %s, %s)
                """,
                (device_id, dev_eui.lower(), event_type,
                 psycopg2.extras.Json(event_data) if event_data else None)
            )


# ──────────────────────────────────────────────────────────────────────────
# Query Operations (used by REST API)
# ──────────────────────────────────────────────────────────────────────────

def get_latest_readings() -> list:
    """Get the most recent reading from each device."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM durian.latest_readings
                ORDER BY device_name
            """)
            return cur.fetchall()


def get_device_readings(
    dev_eui: str,
    hours: int = 24,
    limit: int = 1000
) -> list:
    """Get readings for a specific device within a time window."""
    since = datetime.utcnow() - timedelta(hours=hours)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    received_at, moisture_1, temperature_1, ec_1,
                    moisture_2, temperature_2, ec_2,
                    ph, salinity, nitrogen_mg_kg, phosphorus_mg_kg, potassium_mg_kg,
                    battery_mv, rssi
                FROM durian.sensor_readings
                WHERE dev_eui = %s AND received_at >= %s
                ORDER BY received_at DESC
                LIMIT %s
                """,
                (dev_eui.lower(), since, limit)
            )
            return cur.fetchall()


def get_daily_averages(dev_eui: str, days: int = 30) -> list:
    """Get daily averages for a device over a number of days."""
    since = datetime.utcnow() - timedelta(days=days)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    DATE(received_at) AS reading_date,
                    COUNT(*) AS reading_count,
                    ROUND(AVG(moisture_1)::numeric, 2) AS avg_moisture_1,
                    ROUND(MIN(moisture_1)::numeric, 2) AS min_moisture_1,
                    ROUND(MAX(moisture_1)::numeric, 2) AS max_moisture_1,
                    ROUND(AVG(temperature_1)::numeric, 2) AS avg_temperature_1,
                    ROUND(AVG(ec_1)::numeric, 2) AS avg_ec_1,
                    MIN(battery_mv) AS min_battery_mv
                FROM durian.sensor_readings
                WHERE dev_eui = %s AND received_at >= %s
                GROUP BY DATE(received_at)
                ORDER BY reading_date DESC
                """,
                (dev_eui.lower(), since)
            )
            return cur.fetchall()


def get_all_devices() -> list:
    """Get all registered devices with their status."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    d.id, d.dev_eui, d.name, d.device_model,
                    d.grid_row, d.grid_col, d.depth_cm,
                    d.battery_mv, d.last_seen_at, d.is_active,
                    z.name AS zone_name
                FROM durian.devices d
                LEFT JOIN durian.zones z ON z.id = d.zone_id
                ORDER BY d.name
            """)
            return cur.fetchall()


def get_zone_summary() -> list:
    """Get average readings per zone (latest readings only)."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    lr.zone_name,
                    COUNT(*) AS device_count,
                    ROUND(AVG(lr.moisture_1)::numeric, 2) AS avg_moisture,
                    ROUND(AVG(lr.temperature_1)::numeric, 2) AS avg_temperature,
                    ROUND(AVG(lr.ec_1)::numeric, 2) AS avg_ec,
                    MIN(lr.battery_mv) AS min_battery
                FROM durian.latest_readings lr
                GROUP BY lr.zone_name
                ORDER BY lr.zone_name
            """)
            return cur.fetchall()
