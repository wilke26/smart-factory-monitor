# Multi-machine model operations

## Registry contract

`ML_MODEL_DIRECTORY` contains one artifact named `<machine_id>.joblib` and one detached
signature named `<machine_id>.joblib.sig` per machine. `ML_MACHINE_IDS` is a
comma-separated allowlist used by
both the offline trainer and online consumer. IDs are normalized for whitespace,
deduplicated in order, and validated as lowercase slugs.

When ML is enabled, startup is all-or-nothing: every configured artifact and signature
must exist. The consumer verifies the exact artifact bytes with the configured Ed25519
public key before joblib deserialization, then applies format, feature, machine,
estimator, and scikit-learn-version checks. Files not listed in `ML_MACHINE_IDS` remain
inactive. This makes the deployed model set explicit and keeps an old file in the volume
from silently affecting inference.

## Batch training

The model-trainer loads a bounded history and writes a separate artifact for each configured
machine:

```bash
ML_MACHINE_IDS=press-01,press-02 \
  docker compose --profile tools run --rm model-trainer
```

Every machine needs at least `ML_MINIMUM_TRAINING_SAMPLES` valid readings. The trainer
requires `ML_SIGNING_PRIVATE_KEY_PATH`, signs the serialized bytes, and atomically replaces
the signature and artifact. Training remains an operator-controlled offline action; the
consumer never retrains or reloads models in place.

Compose runs `model-key-init` automatically to create a persistent development key pair.
The trainer mounts only its private-key volume and the consumer mounts only its public-key
volume. For a non-Compose environment, generate a pair once with:

```bash
ML_SIGNING_PRIVATE_KEY_PATH=/secure/private.pem \
ML_SIGNATURE_PUBLIC_KEY_PATH=/config/public.pem \
smart-factory-generate-model-key
```

Back up the private key separately from the registry, limit it to the training identity,
and distribute the public key through the deployment secret system. Key compromise or
intentional rotation requires a new pair, re-signing approved artifacts, and coordinated
consumer rollout. The command reuses a valid matching pair rather than rotating it.

## Coverage signals

`smart_factory_ml_models_loaded` reports the active registry size.
`smart_factory_ml_inference_total{coverage="scored"}` counts readings dispatched to a
model, while `coverage="uncovered"` counts valid readings for machines outside the active
registry. These aggregate labels remain bounded regardless of machine fleet size.

## Post-training evaluation

Artifact format v2 binds the training reference distribution to the signed model bytes.
After enough new telemetry has arrived, run:

```bash
ML_MACHINE_IDS=press-01,press-02 \
  docker compose --profile tools run --rm model-evaluator
```

For each machine the evaluator verifies the signature, reads at most
`ML_EVALUATION_LIMIT` rows with `recorded_at` later than the artifact's recorded training
window end,
and logs `evaluation_samples`, `anomaly_rate`, every feature PSI, the largest PSI, and the
failed gates. The command succeeds only when every configured machine has at least
`ML_EVALUATION_MINIMUM_SAMPLES`, stays at or below
`ML_MAX_EVALUATION_ANOMALY_RATE`, and stays at or below `ML_MAX_FEATURE_PSI` for all
features.

This gives deployment automation a deterministic quality gate but deliberately does not
promote the model. Archive the structured result outside the container if durable evidence
is required. Late readings at or before the stored training boundary are deliberately not
treated as post-training evidence. Existing format-v1 artifacts are incompatible and must
be retrained.

## Remaining controls

The local registry is not a production model platform. Signatures establish integrity
and provenance under the configured key. The offline gates provide post-training
distribution evidence but not labelled accuracy or approval. Immutable version storage,
rollback, controlled promotion, durable evaluation history, key rotation, and registry
distribution remain explicit future work.
