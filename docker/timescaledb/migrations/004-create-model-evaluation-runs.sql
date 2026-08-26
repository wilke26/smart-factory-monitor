CREATE TABLE IF NOT EXISTS model_evaluation_runs (
    evaluation_id UUID PRIMARY KEY,
    evaluated_at TIMESTAMPTZ NOT NULL,
    model_id TEXT NOT NULL,
    machine_id TEXT NOT NULL CHECK (machine_id ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    training_window_end TIMESTAMPTZ NOT NULL,
    sample_count INTEGER NOT NULL CHECK (sample_count >= 0),
    anomaly_rate DOUBLE PRECISION NOT NULL CHECK (anomaly_rate BETWEEN 0 AND 1),
    feature_psi JSONB NOT NULL CHECK (jsonb_typeof(feature_psi) = 'object'),
    maximum_feature_psi DOUBLE PRECISION NOT NULL CHECK (maximum_feature_psi >= 0),
    passed BOOLEAN NOT NULL,
    failed_gates TEXT[] NOT NULL,
    CHECK (training_window_end <= evaluated_at),
    CHECK (passed = (cardinality(failed_gates) = 0))
);

CREATE INDEX IF NOT EXISTS model_evaluation_runs_machine_time_idx
    ON model_evaluation_runs (machine_id, evaluated_at DESC);

CREATE INDEX IF NOT EXISTS model_evaluation_runs_model_id_idx
    ON model_evaluation_runs (model_id, evaluated_at DESC);
