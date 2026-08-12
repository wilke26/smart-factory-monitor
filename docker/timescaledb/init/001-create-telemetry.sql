CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS telemetry_readings (
    machine_id TEXT NOT NULL CHECK (machine_id ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    recorded_at TIMESTAMPTZ NOT NULL,
    temperature_c DOUBLE PRECISION NOT NULL CHECK (temperature_c BETWEEN -50 AND 250),
    vibration_mm_s DOUBLE PRECISION NOT NULL CHECK (vibration_mm_s BETWEEN 0 AND 100),
    power_kw DOUBLE PRECISION NOT NULL CHECK (power_kw BETWEEN 0 AND 500),
    production_rate INTEGER NOT NULL CHECK (production_rate BETWEEN 0 AND 10000),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (machine_id, recorded_at)
);

SELECT create_hypertable(
    'telemetry_readings',
    by_range('recorded_at'),
    if_not_exists => TRUE
);
