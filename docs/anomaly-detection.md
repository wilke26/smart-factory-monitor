# Anomaly detection

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

## Isolation Forest

The optional ML detector scores the vector `(temperature_c, vibration_mm_s, power_kw,
production_rate)`. A negative scikit-learn `decision_function` score produces the
medium-severity finding `ml-isolation-forest`; non-negative scores are normal.

Models are trained offline from bounded recent history for exactly one machine. The
artifact records its format, feature order, machine ID, training timestamp, sample count,
scikit-learn version, and fitted estimator. Inference ignores readings from other
machines. Rules continue to run independently, so ML cannot suppress a known-condition
finding.

An ML finding stores the score as `observed_value`, zero as `threshold`, `<` as the
comparison, and the model ID in its message. This is locally explainable evidence, not a
claim that Isolation Forest explains which input feature caused the score.
