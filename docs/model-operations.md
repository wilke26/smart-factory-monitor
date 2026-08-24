# Multi-machine model operations

## Registry contract

`ML_MODEL_DIRECTORY` is a trusted directory containing one artifact named
`<machine_id>.joblib` per machine. `ML_MACHINE_IDS` is a comma-separated allowlist used by
both the offline trainer and online consumer. IDs are normalized for whitespace,
deduplicated in order, and validated as lowercase slugs.

When ML is enabled, startup is all-or-nothing: every configured artifact must exist and
pass format, feature, machine, estimator, and scikit-learn-version checks. Files not listed
in `ML_MACHINE_IDS` remain inactive. This makes the deployed model set explicit and keeps
an old file in the volume from silently affecting inference.

## Batch training

The model-trainer loads a bounded history and writes a separate artifact for each configured
machine:

```bash
ML_MACHINE_IDS=press-01,press-02 \
  docker compose --profile tools run --rm model-trainer
```

Every machine needs at least `ML_MINIMUM_TRAINING_SAMPLES` valid readings. Artifacts are
replaced atomically per file. Training remains an operator-controlled offline action;
the consumer never retrains or reloads models in place.

## Coverage signals

`smart_factory_ml_models_loaded` reports the active registry size.
`smart_factory_ml_inference_total{coverage="scored"}` counts readings dispatched to a
model, while `coverage="uncovered"` counts valid readings for machines outside the active
registry. These aggregate labels remain bounded regardless of machine fleet size.

## Remaining controls

The local registry is not a production model platform. Promotion approval, signatures,
immutable version storage, rollback, hold-out evaluation, drift policy, and registry
distribution remain explicit future work.
