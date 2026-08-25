CREATE TABLE IF NOT EXISTS anomaly_alert_outbox (
    event_id UUID NOT NULL UNIQUE,
    machine_id TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    rule_id TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('medium', 'high')),
    metric TEXT NOT NULL,
    observed_value DOUBLE PRECISION NOT NULL,
    threshold DOUBLE PRECISION NOT NULL,
    comparison TEXT NOT NULL CHECK (comparison IN ('>', '<')),
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    last_error TEXT,
    PRIMARY KEY (machine_id, recorded_at, rule_id),
    FOREIGN KEY (machine_id, recorded_at, rule_id)
        REFERENCES anomaly_findings (machine_id, recorded_at, rule_id)
        ON DELETE CASCADE,
    CHECK ((lease_token IS NULL) = (lease_expires_at IS NULL))
);

CREATE INDEX IF NOT EXISTS anomaly_alert_outbox_pending_idx
    ON anomaly_alert_outbox (available_at, created_at)
    WHERE delivered_at IS NULL;
