# Telemetry data contract

Topic: `factory/{area}/{machine_id}/telemetry`

Canonical example:

```json
{
  "machine_id": "press-01",
  "timestamp": "2026-08-12T12:30:15.123Z",
  "temperature_c": 68.4,
  "vibration_mm_s": 2.7,
  "power_kw": 17.3,
  "production_rate": 44
}
```

| Field | Type | Constraint | Meaning |
|---|---|---|---|
| `machine_id` | string | lowercase slug, 3–64 chars | Stable machine identity |
| `timestamp` | ISO-8601 datetime | timezone required | Measurement time |
| `temperature_c` | float | −50…250 | Temperature in °C |
| `vibration_mm_s` | float | 0…100 | Vibration velocity in mm/s |
| `power_kw` | float | 0…500 | Active power in kW |
| `production_rate` | integer | 0…10,000 | Parts per minute |

Unknown fields are rejected. The model is immutable after validation. Breaking changes
require a versioned contract/topic decision before producers and consumers change.

## Persistence mapping

| Contract field | Database column |
|---|---|
| `machine_id` | `machine_id` |
| `timestamp` | `recorded_at` |
| `temperature_c` | `temperature_c` |
| `vibration_mm_s` | `vibration_mm_s` |
| `power_kw` | `power_kw` |
| `production_rate` | `production_rate` |

The database adds `ingested_at`. `(machine_id, recorded_at)` is the idempotency key. An
exact duplicate is accepted idempotently. Reusing that identity with different measurement
values is a permanent contract conflict: it is logged and acknowledged without storing
findings that would disagree with the original row.
Anomaly findings reference that same key; their evidence contract is documented in
[anomaly-detection.md](anomaly-detection.md).

## Alert event contract

An enabled alert route copies one finding's immutable evidence into
`anomaly_alert_outbox` in the same transaction. The webhook JSON contains `event_id`,
`machine_id`, `recorded_at`, `rule_id`, `severity`, `metric`, `observed_value`, `threshold`,
`comparison`, and `message`. It contains neither the complete telemetry payload nor
credentials. `event_id` is deterministic for the finding identity and is also sent as the
HTTP `Idempotency-Key` so receivers can deduplicate at-least-once delivery.

The ML feature contract uses the four numeric fields in the table order shown above and
does not include identifiers or timestamps. A model artifact is bound separately to one
`machine_id`; changing feature meaning or order requires a new artifact format.
In the v0.7 registry the trusted artifact filename is `<machine_id>.joblib` and must match
the embedded artifact identity.
Artifact format v2 additionally binds deterministic histogram edges and training
proportions for these exact features. They are evaluation metadata, not telemetry fields.

## Model-evaluation evidence contract

Each evaluator run stores one immutable `model_evaluation_runs` row per machine. It
contains `evaluation_id`, `evaluated_at`, `model_id`, `artifact_sha256`, `machine_id`,
`training_window_end`, `sample_count`, `anomaly_rate`, a JSON object of per-feature PSI,
`maximum_feature_psi`, `passed`, and the stable `failed_gates` array. Timestamps require a
UTC offset, probabilities are finite and bounded, feature names are unique, the maximum
must match the feature values, and `passed` is true exactly when `failed_gates` is empty.
Rows created before v0.13 can have a null digest after the non-destructive migration and
never authorize promotion; rerun evaluation against the current candidate to bind it.

## Active model-registry contract

`active.json` is a strict schema-v1 manifest with a generation UUID, timestamp, optional
previous and rollback-source generations, and one unique entry per machine. Each entry
binds `machine_id`, signed `model_id`, and the lowercase SHA-256 of the exact artifact
bytes. The referenced path is derived from these validated values rather than accepted
from the manifest. A generation becomes visible through one atomic manifest replacement.
