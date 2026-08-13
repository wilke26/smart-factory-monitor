# Rule-based anomaly detection

## Rules

| Rule ID | Metric | Default condition | Severity |
|---|---|---|---|
| `temperature-high` | `temperature_c` | `> 90.0` | high |
| `vibration-high` | `vibration_mm_s` | `> 7.0` | high |
| `power-high` | `power_kw` | `> 30.0` | high |
| `production-rate-low` | `production_rate` | `< 25` | medium |

Equality is normal. Rules are independent and returned in the table order, so a single
reading can have several findings. Thresholds come from validated environment settings.

## Finding contract

Each immutable `AnomalyFinding` contains:

- stable `rule_id`;
- `severity` (`medium` or `high`);
- affected `metric`;
- `observed_value` and configured `threshold`;
- `comparison` (`>` or `<`);
- human-readable `message`.

Findings are stored with the reading identity and detection timestamp. The evidence
fields make historical decisions explainable even if configuration later changes.

These values are business thresholds, not validation limits. For example, 95 °C is a
valid sensor value that crosses the operational temperature rule.
