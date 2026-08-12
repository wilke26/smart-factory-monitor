# Telemetry data contract v0.1

Topic: `factory/{area}/{machine_id}/telemetry`

Canonical v0.1 example:

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
require a versioned contract/topic decision before consumers are introduced.
