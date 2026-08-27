ALTER TABLE model_evaluation_runs
    ADD COLUMN IF NOT EXISTS artifact_sha256 TEXT;

ALTER TABLE model_evaluation_runs
    DROP CONSTRAINT IF EXISTS model_evaluation_runs_artifact_sha256_check;

ALTER TABLE model_evaluation_runs
    ADD CONSTRAINT model_evaluation_runs_artifact_sha256_check
    CHECK (artifact_sha256 IS NULL OR artifact_sha256 ~ '^[0-9a-f]{64}$');

CREATE INDEX IF NOT EXISTS model_evaluation_runs_approved_artifact_idx
    ON model_evaluation_runs (machine_id, model_id, artifact_sha256)
    WHERE passed AND artifact_sha256 IS NOT NULL;
