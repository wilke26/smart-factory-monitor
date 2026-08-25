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
scikit-learn version, per-feature reference distribution, and fitted estimator. Inference ignores readings from other
machines. Rules continue to run independently, so ML cannot suppress a known-condition
finding.

An ML finding stores the score as `observed_value`, zero as `threshold`, `<` as the
comparison, and the model ID in its message. This is locally explainable evidence, not a
claim that Isolation Forest explains which input feature caused the score.

## Multi-machine registry

v0.7 stores one artifact as `<machine_id>.joblib`. `ML_MACHINE_IDS` defines the complete
active set: startup fails if one configured artifact is absent or its embedded identity
does not match the filename. The registry dispatches a reading only to its own detector;
unconfigured machines continue through deterministic rules and are counted as uncovered
ML inference without exposing machine IDs as metric labels.

## Offline evaluation and drift gates

Artifact format v2 stores decile-derived bin edges and training proportions for each
feature. `smart-factory-evaluate-model` verifies each configured signature and evaluates a
bounded set of readings whose event timestamps are later than the artifact's
`training_window_end`.
It calculates the fraction classified as anomalies and Population Stability Index (PSI)
for every feature using the artifact's fixed bins.

The report passes only if the minimum sample count is available, the anomaly fraction is
not above `ML_MAX_EVALUATION_ANOMALY_RATE`, and no feature PSI is above
`ML_MAX_FEATURE_PSI`. PSI is a monitoring heuristic for input-distribution change; it does
not measure accuracy and does not explain model output. The evaluation command reports
all configured machines and returns a failure status if any gate fails. It never promotes
or reloads an artifact.
