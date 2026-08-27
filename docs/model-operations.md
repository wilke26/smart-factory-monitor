# Multi-machine model operations

## Registry contract

`ML_MODEL_DIRECTORY` contains candidate, immutable version, manifest-history, and active
manifest areas. `ML_MACHINE_IDS` is a
comma-separated allowlist used by
both the offline trainer and online consumer. IDs are normalized for whitespace,
deduplicated in order, and validated as lowercase slugs.

When ML is enabled, startup is all-or-nothing: `active.json` must reference every
configured machine. The consumer derives content-addressed paths, verifies digest and
Ed25519 signature before joblib deserialization, then applies format, feature, machine,
estimator, and scikit-learn-version checks. Unreferenced files remain inactive.

## Batch training

The model-trainer loads a bounded history and writes a separate artifact for each configured
machine:

```bash
ML_MACHINE_IDS=press-01,press-02 \
  docker compose --profile tools run --rm model-trainer
```

Every machine needs at least `ML_MINIMUM_TRAINING_SAMPLES` valid readings. The trainer
requires `ML_SIGNING_PRIVATE_KEY_PATH`, signs the serialized bytes, and writes the pair to
`candidates/`. Training remains operator-controlled; the consumer never reads candidates,
retrains, or reloads models in place.

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

The v0.14 recovery bundle includes the signed registry and its public verification key but
intentionally excludes this private key. A successful registry recovery therefore proves
that existing active models can still be authenticated and loaded; it does not prove that
new models can be signed. Test private-key disaster recovery independently under the key-
management policy.

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
failed gates. Before reporting the machine result it persists the same immutable evidence
to `model_evaluation_runs`. The command succeeds only when every configured machine has at least
`ML_EVALUATION_MINIMUM_SAMPLES`, stays at or below
`ML_MAX_EVALUATION_ANOMALY_RATE`, and stays at or below `ML_MAX_FEATURE_PSI` for all
features.

This gives deployment automation a deterministic quality gate and durable audit history,
but deliberately does not promote the model. Evidence persistence fails closed: a result
that cannot be stored cannot pass the command. Late readings at or before the stored
training boundary are deliberately not treated as post-training evidence. Existing
format-v1 artifacts are incompatible and must be retrained.

```sql
SELECT evaluated_at, model_id, artifact_sha256, sample_count, anomaly_rate,
       maximum_feature_psi, passed, failed_gates
FROM model_evaluation_runs
WHERE machine_id = 'press-01'
ORDER BY evaluated_at DESC;
```

## Promotion and rollback

After every configured candidate passes evaluation, promote the complete set:

```bash
ML_MACHINE_IDS=press-01,press-02 \
AUDIT_ACTOR=<trusted-identity> \
AUDIT_REASON=<ticket-or-reason> \
AUDIT_CORRELATION_ID=<uuid> \
  docker compose --profile tools run --rm model-promoter
```

Promotion queries a passed row matching machine ID, signed model ID, and exact artifact
SHA-256 for every candidate before writing anything active. It stores artifacts and
signatures below `versions/<machine-id>/<sha256>.joblib[.sig]`, archives a strict manifest
under `manifests/<generation-id>.json`, and atomically replaces `active.json`. A changed,
missing, unsigned, or unevaluated candidate rejects the complete batch.

Record the generation UUID emitted by `ml_models_promoted`. Restore an earlier complete
set by explicitly selecting its archived generation:

```bash
ML_ROLLBACK_GENERATION_ID=<generation-uuid> \
AUDIT_ACTOR=<trusted-identity> \
AUDIT_REASON=<ticket-or-reason> \
AUDIT_CORRELATION_ID=<uuid> \
  docker compose --profile tools run --rm model-rollback
```

Rollback revalidates every digest and signature and creates a new active generation whose
`source_generation_id` records the selected history entry. Restart the consumer after a
promotion or rollback; it deliberately does not hot-reload registry state.

## Privileged-operation audit

Promotion and rollback require complete audit context. The command first appends a
`started` event and stops before touching the registry if that write fails. It then appends
`succeeded` with the previous and resulting generation or `failed` with a bounded error
type. An unmatched `started` event identifies a crashed or partially completed operation
that needs reconciliation.

The PostgreSQL table rejects updates and deletes through a trigger. Writers take a
transaction-scoped advisory lock and bind every canonical event to the previous SHA-256,
so concurrent writers have one order and later mutation is detectable. Verify the chain
independently with:

```bash
docker compose --profile tools run --rm audit-verifier
```

```sql
SELECT sequence_number, occurred_at, actor, reason, correlation_id,
       action, outcome, previous_state, resulting_state, error_type
FROM operator_audit_events
ORDER BY sequence_number;
```

The local command accepts an asserted `AUDIT_ACTOR`; it does not authenticate that value.
Production release automation must inject an identity derived from its authenticated
operator or workload and restrict direct database ownership. External attestation,
retention, archival, query authorization, and audit events for key rotation and security
configuration remain deployment work.

### Signed audit checkpoints

After privileged operations, verify and sign the current chain head with a dedicated
attestation key. On a Linux host, provision the bind-mounted output directory for the
container's non-root UID and the invoking user's group first
(`sudo install -d -o 10001 -g "$(id -g)" -m 0770 audit-checkpoints`):

```bash
AUDIT_CHAIN_ID=smart-factory-local AUDIT_CHECKPOINT_NAME=manual-2026-08-27.json \
  docker compose --profile tools run --rm audit-checkpoint-exporter
```

The exporter refuses an invalid database chain and never replaces an existing checkpoint
path. Verify the resulting self-contained envelope without PostgreSQL:

```bash
AUDIT_CHAIN_ID=smart-factory-local AUDIT_CHECKPOINT_NAME=manual-2026-08-27.json \
  docker compose --profile tools run --rm --no-deps audit-checkpoint-verifier
```

Retain the JSON and trusted public key outside the database administrative boundary. A
valid historical checkpoint proves the exact event count and head hash observed at its
creation time; it does not prove that later events were retained or that checkpoints were
created on schedule. Production policy must define checkpoint cadence, freshness alerts,
immutable storage, retention, and attestation-key rotation.

## Remaining controls

The local registry is not a production model platform. Signatures establish integrity
and provenance under the configured key. The offline gates provide post-training
distribution evidence but not labelled accuracy or human approval. Approval integration,
generation retention, key rotation, registry distribution, scheduled external checkpoint retention,
and a defined retention and access policy remain explicit future work.
