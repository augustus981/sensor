-- ===========================================================================
-- Migration 002: Add QC-S8 soil sensor columns
--
-- The QC-S8 is a 7-in-1 RS485 Modbus sensor measuring:
--   moisture, temperature, EC, pH, salinity, nitrogen, phosphorus, potassium
--
-- We add these columns to the existing sensor_readings table so both
-- SE02-LB and QC-S8 readings coexist. Unused columns remain NULL.
-- ===========================================================================

-- New soil chemistry columns
ALTER TABLE durian.sensor_readings
    ADD COLUMN IF NOT EXISTS ph REAL,
    ADD COLUMN IF NOT EXISTS salinity REAL,
    ADD COLUMN IF NOT EXISTS nitrogen_mg_kg REAL,
    ADD COLUMN IF NOT EXISTS phosphorus_mg_kg REAL,
    ADD COLUMN IF NOT EXISTS potassium_mg_kg REAL;

-- Allow devices to identify as QC-S8 model
COMMENT ON COLUMN durian.sensor_readings.ph IS 'Soil pH (3-10), QC-S8 sensor';
COMMENT ON COLUMN durian.sensor_readings.salinity IS 'Soil salinity (µS/cm), QC-S8 sensor';
COMMENT ON COLUMN durian.sensor_readings.nitrogen_mg_kg IS 'Soil nitrogen (mg/kg), QC-S8 sensor';
COMMENT ON COLUMN durian.sensor_readings.phosphorus_mg_kg IS 'Soil phosphorus (mg/kg), QC-S8 sensor';
COMMENT ON COLUMN durian.sensor_readings.potassium_mg_kg IS 'Soil potassium (mg/kg), QC-S8 sensor';

-- Add a column to track data source (lorawan vs wifi-direct)
ALTER TABLE durian.devices
    ADD COLUMN IF NOT EXISTS connection_type VARCHAR(16) DEFAULT 'lorawan';

COMMENT ON COLUMN durian.devices.connection_type IS 'How the device sends data: lorawan or wifi';

-- Update the latest_readings view to include new columns
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
    sr.ph,
    sr.salinity,
    sr.nitrogen_mg_kg,
    sr.phosphorus_mg_kg,
    sr.potassium_mg_kg,
    sr.battery_mv,
    sr.rssi
FROM durian.sensor_readings sr
JOIN durian.devices d ON d.id = sr.device_id
LEFT JOIN durian.zones z ON z.id = d.zone_id
ORDER BY sr.device_id, sr.received_at DESC;

-- Update daily averages view to include new columns
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
    ROUND(AVG(ph)::numeric, 2) AS avg_ph,
    ROUND(AVG(salinity)::numeric, 2) AS avg_salinity,
    ROUND(AVG(nitrogen_mg_kg)::numeric, 1) AS avg_nitrogen,
    ROUND(AVG(phosphorus_mg_kg)::numeric, 1) AS avg_phosphorus,
    ROUND(AVG(potassium_mg_kg)::numeric, 1) AS avg_potassium,
    MIN(battery_mv) AS min_battery_mv
FROM durian.sensor_readings
GROUP BY device_id, DATE(received_at);
