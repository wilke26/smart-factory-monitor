CREATE TABLE IF NOT EXISTS anomaly_findings (
    machine_id TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    rule_id TEXT NOT NULL CHECK (rule_id ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    severity TEXT NOT NULL CHECK (severity IN ('medium', 'high')),
    metric TEXT NOT NULL,
    observed_value DOUBLE PRECISION NOT NULL,
    threshold DOUBLE PRECISION NOT NULL,
    comparison TEXT NOT NULL CHECK (comparison IN ('>', '<')),
    message TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (machine_id, recorded_at, rule_id),
    FOREIGN KEY (machine_id, recorded_at)
        REFERENCES telemetry_readings (machine_id, recorded_at)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS anomaly_findings_recorded_at_idx
    ON anomaly_findings (recorded_at DESC);

CREATE INDEX IF NOT EXISTS anomaly_findings_rule_id_idx
    ON anomaly_findings (rule_id, recorded_at DESC);
