CREATE TABLE IF NOT EXISTS operator_audit_events (
    sequence_number BIGSERIAL PRIMARY KEY,
    event_id UUID NOT NULL UNIQUE,
    occurred_at TIMESTAMPTZ NOT NULL,
    actor TEXT NOT NULL CHECK (length(actor) BETWEEN 1 AND 255),
    reason TEXT NOT NULL CHECK (length(reason) BETWEEN 1 AND 2000),
    correlation_id UUID NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('model_promotion', 'model_rollback')),
    outcome TEXT NOT NULL CHECK (outcome IN ('started', 'succeeded', 'failed')),
    previous_state JSONB NOT NULL CHECK (jsonb_typeof(previous_state) = 'object'),
    resulting_state JSONB NOT NULL CHECK (jsonb_typeof(resulting_state) = 'object'),
    error_type TEXT CHECK (error_type IS NULL OR length(error_type) BETWEEN 1 AND 255),
    previous_hash TEXT NOT NULL CHECK (previous_hash ~ '^[0-9a-f]{64}$'),
    event_hash TEXT NOT NULL UNIQUE CHECK (event_hash ~ '^[0-9a-f]{64}$'),
    CHECK ((outcome = 'failed') = (error_type IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS operator_audit_events_correlation_idx
    ON operator_audit_events (correlation_id, sequence_number);

CREATE INDEX IF NOT EXISTS operator_audit_events_action_time_idx
    ON operator_audit_events (action, occurred_at DESC);

CREATE OR REPLACE FUNCTION reject_operator_audit_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'operator audit events are append-only';
END;
$$;

DROP TRIGGER IF EXISTS operator_audit_events_immutable ON operator_audit_events;

CREATE TRIGGER operator_audit_events_immutable
BEFORE UPDATE OR DELETE ON operator_audit_events
FOR EACH ROW
EXECUTE FUNCTION reject_operator_audit_mutation();
