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

The ML feature contract uses the four numeric fields in the table order shown above and
does not include identifiers or timestamps. A model artifact is bound separately to one
`machine_id`; changing feature meaning or order requires a new artifact format.
In the v0.7 registry the trusted artifact filename is `<machine_id>.joblib` and must match
the embedded artifact identity.
