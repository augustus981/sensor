-- ===========================================================================
-- Durian Garden IoT — Database Schema
-- Year 1: Data Collection Phase
--
-- Tables:
--   devices        : Registry of SE02-LB sensors and their locations
--   zones          : Garden zones for future irrigation control
--   sensor_readings: Time-series soil moisture/EC/temperature data
--   device_events  : Device lifecycle events (join, battery, status)
-- ===========================================================================

-- Create the schema for our application (ChirpStack uses its own tables)
CREATE SCHEMA IF NOT EXISTS durian;

-- ──────────────────────────────────────────────────────────────────────────
-- Zones — Garden zones for grouping trees
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS durian.zones (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(64) NOT NULL UNIQUE,
    description     TEXT,
    tree_count      INTEGER DEFAULT 0,
    -- Grid coordinates (which area of the garden)
    grid_row_start  INTEGER,
    grid_row_end    INTEGER,
    grid_col_start  INTEGER,
    grid_col_end    INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ──────────────────────────────────────────────────────────────────────────
-- Devices — Registry of SE02-LB sensors
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS durian.devices (
    id              SERIAL PRIMARY KEY,
    dev_eui         VARCHAR(16) NOT NULL UNIQUE,  -- LoRaWAN Device EUI (hex)
    name            VARCHAR(64) NOT NULL,
    zone_id         INTEGER REFERENCES durian.zones(id),
    -- Physical placement
    grid_row        INTEGER,                       -- Row in the garden grid
    grid_col        INTEGER,                       -- Column in the garden grid
    depth_cm        INTEGER DEFAULT 30,            -- Probe burial depth in cm
    -- Device metadata
    device_model    VARCHAR(32) DEFAULT 'SE02-LB',
    firmware_ver    VARCHAR(16),
    -- Status
    battery_mv      INTEGER,
    last_seen_at    TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT TRUE,
    -- Metadata
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_devices_dev_eui ON durian.devices(dev_eui);
CREATE INDEX idx_devices_zone ON durian.devices(zone_id);

-- ──────────────────────────────────────────────────────────────────────────
-- Sensor Readings — Time-series data (the core of our data collection)
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS durian.sensor_readings (
    id              BIGSERIAL PRIMARY KEY,
    device_id       INTEGER NOT NULL REFERENCES durian.devices(id),
    dev_eui         VARCHAR(16) NOT NULL,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Channel 1 (probe 1)
    moisture_1      REAL,          -- Soil moisture % (0-100)
    temperature_1   REAL,          -- Soil temperature °C
    ec_1            REAL,          -- Electrical conductivity µS/cm

    -- Channel 2 (probe 2, if connected)
    moisture_2      REAL,
    temperature_2   REAL,
    ec_2            REAL,

    -- Device status
    battery_mv      INTEGER,       -- Battery voltage in millivolts

    -- LoRaWAN metadata
    rssi            INTEGER,       -- Signal strength (dBm)
    snr             REAL,          -- Signal-to-noise ratio (dB)
    spreading_factor INTEGER,
    f_cnt           INTEGER,       -- Frame counter

    -- Raw payload for debugging / reprocessing
    raw_payload     VARCHAR(512)
);

-- Partition-friendly index on time for fast range queries
CREATE INDEX idx_readings_time ON durian.sensor_readings(received_at DESC);
CREATE INDEX idx_readings_device ON durian.sensor_readings(device_id, received_at DESC);
CREATE INDEX idx_readings_dev_eui ON durian.sensor_readings(dev_eui, received_at DESC);

-- ──────────────────────────────────────────────────────────────────────────
-- Device Events — lifecycle tracking
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS durian.device_events (
    id              BIGSERIAL PRIMARY KEY,
    device_id       INTEGER REFERENCES durian.devices(id),
    dev_eui         VARCHAR(16) NOT NULL,
    event_type      VARCHAR(32) NOT NULL,  -- 'join', 'battery_low', 'offline', 'error'
    event_data      JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_events_device ON durian.device_events(device_id, created_at DESC);
CREATE INDEX idx_events_type ON durian.device_events(event_type, created_at DESC);

-- ──────────────────────────────────────────────────────────────────────────
-- Views — Convenient queries for common operations
-- ──────────────────────────────────────────────────────────────────────────

-- Latest reading per device
CREATE OR REPLACE VIEW durian.latest_readings AS
SELECT DISTINCT ON (sr.device_id)
    sr.device_id,
    d.name AS device_name,
    d.dev_eui,
    z.name AS zone_name,
    sr.received_at,
    sr.moisture_1,
    sr.temperature_1,
    sr.ec_1,
    sr.moisture_2,
    sr.temperature_2,
    sr.ec_2,
    sr.battery_mv,
    sr.rssi
FROM durian.sensor_readings sr
JOIN durian.devices d ON d.id = sr.device_id
LEFT JOIN durian.zones z ON z.id = d.zone_id
ORDER BY sr.device_id, sr.received_at DESC;

-- Daily averages per device (for trend analysis)
CREATE OR REPLACE VIEW durian.daily_averages AS
SELECT
    device_id,
    DATE(received_at) AS reading_date,
    COUNT(*) AS reading_count,
    ROUND(AVG(moisture_1)::numeric, 2) AS avg_moisture_1,
    ROUND(MIN(moisture_1)::numeric, 2) AS min_moisture_1,
    ROUND(MAX(moisture_1)::numeric, 2) AS max_moisture_1,
    ROUND(AVG(temperature_1)::numeric, 2) AS avg_temperature_1,
    ROUND(AVG(ec_1)::numeric, 2) AS avg_ec_1,
    ROUND(AVG(moisture_2)::numeric, 2) AS avg_moisture_2,
    ROUND(AVG(temperature_2)::numeric, 2) AS avg_temperature_2,
    ROUND(AVG(ec_2)::numeric, 2) AS avg_ec_2,
    MIN(battery_mv) AS min_battery_mv
FROM durian.sensor_readings
GROUP BY device_id, DATE(received_at);

-- ──────────────────────────────────────────────────────────────────────────
-- Insert default zone for prototype
-- ──────────────────────────────────────────────────────────────────────────
INSERT INTO durian.zones (name, description, tree_count)
VALUES ('Zone A - Prototype', 'Initial test zone for SE02-LB deployment', 10)
ON CONFLICT (name) DO NOTHING;
