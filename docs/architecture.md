# Architecture v0.16.0

## Scope

Version 0.11 retains the model-quality gate and adds durable alert routing without placing
external HTTP inside MQTT processing. Eligible anomaly evidence is written to a
transactional outbox, then a separate dispatcher leases and delivers it.
Version 0.11.1 makes a lost lease an explicit non-fatal concurrency outcome so a stale
worker cannot stop delivery of the remaining claimed batch.
Version 0.12 adds an outbound model-evaluation store so release evidence survives the
one-shot evaluator process without coupling gate calculation to PostgreSQL.
Version 0.13 binds that evidence to exact candidate bytes and separates training,
evaluation, atomic promotion, active inference, and rollback into explicit lifecycle steps.
Version 0.14 packages the database, model registry, and verification public key into a
checksummed recovery bundle and proves restoration against isolated targets in CI.
Version 0.14.1 orders TimescaleDB restoration so hypertable keys are created in restore
mode and application foreign keys are validated only after `timescaledb_post_restore()`.
Version 0.15 makes model promotion and rollback fail closed on an append-only,
hash-chained operator audit trail and adds independent chain verification.
Version 0.16 signs a verified chain head with a separate Ed25519 attestation key and
exports a portable checkpoint that can be verified without database access.

```text
Offline ML lifecycle                              Online telemetry path
telemetry_readings                                MQTT → validation → application service
        │                                                               │
        ▼                                                               ▼
model-trainer → reference + sign → candidates              CompositeAnomalyDetector
 private key                         │                       ├── rules (always)
                                     ▼                       └── MachineModelRegistry
post-training telemetry → model-evaluator                              ▲
                         quality gates                                 │ startup load
                               │                                       │
                               ├── model_evaluation_runs + SHA-256     │
                               ▼                                       │
                        model-promoter → signed versions ← rollback    │
                               │                 │                     │
                               ├── atomic active.json ──────────────────┘
                               └── operator_audit_events hash chain
                                             │ verify + sign
                                             ▼
                                  external checkpoint JSON

application service → one transaction → telemetry_readings + anomaly_findings
                                               + alert outbox
                                                       │
                                                       ▼
                                      alert-dispatcher → HTTPS webhook

quiesced writers → pg_dump + model registry + public key → checksummed backup bundle
                                                                  │
                                                                  ▼
                              isolated recovery database + volumes → verification
```

## Dependency direction

- `domain` owns validated telemetry, finding contracts, and deterministic rules.
- `application` owns the technology-neutral detector, alert-outbox and alert-sink ports,
  processing orchestration, detector composition, and retry scheduling.
- `infrastructure.ml` owns scikit-learn training, artifact signing and verification,
  reference distributions, offline evaluation, immutable version publication, atomic
  registry manifests, rollback, validation, and machine-aware inference dispatch.
- `infrastructure.database` supplies atomic telemetry/outbox persistence, leased alert
  claims, delivery-state transitions, bounded historical reads, and immutable model
  evaluation evidence plus serialized, hash-chained operator events.
- `infrastructure.alerts` owns verified webhook transport.
- `infrastructure.audit` owns canonical checkpoint signing, write-once publication, and
  verification independent of PostgreSQL.
- `consumer_main`, `alert_dispatcher_main`, `train_model_main`, `evaluate_model_main`,
  `promote_model_main`, `rollback_model_main`, `verify_audit_main`,
  `export_audit_checkpoint_main`, and `verify_audit_checkpoint_main` are separate
  composition roots.
- Containerized recovery adapters own PostgreSQL dump/restore and filesystem packaging;
  they do not enter the online application dependency graph.

The real-time application service sees only the detector protocol. It neither imports
scikit-learn nor decides whether ML is enabled.

## Model lifecycle boundary

Training reads bounded windows, uses a fixed random seed, signs serialized bytes with the
offline Ed25519 private key, and writes only candidate pairs. Evaluation binds each result
to the candidate digest. Promotion requires passed evidence for every exact candidate,
publishes content-addressed signed versions, and activates the complete set through one
atomic manifest replacement. No partial multi-machine set becomes active.

The consumer has only the public key and loads only entries in `active.json`. Paths are
derived from validated machine IDs and digests, then the consumer verifies digest and
signature before passing the bytes to joblib. It also validates format version, exact
feature order, embedded machine and model identity, estimator type, and scikit-learn
version. Archived generations enable explicit reverified rollback without mutating model
history. Because joblib has pickle semantics, public-key distribution and private-key
custody remain trust boundaries.

Missing, unreadable, and incompatible artifacts are normalized to `MlArtifactError`.
That permanent startup/configuration error is deliberately outside the MQTT/database
retry policy, so an enabled consumer fails fast with an actionable cause.

Artifact format v2 embeds decile-based reference proportions for the exact four-feature
contract. Offline evaluation uses the same authenticated artifact and a bounded database
query constrained to `recorded_at > training_window_end`, preventing any training row from
being reused as evaluation evidence. It computes model
anomaly rate and PSI against the artifact's fixed bins. Minimum sample count, maximum
anomaly rate, and maximum feature PSI are independently configurable; any failed gate
makes the command fail after all configured machines have been reported. Evaluation does
not mutate or promote the registry.

## Delivery and persistence semantics

Rules and ML are evaluated before the existing TimescaleDB transaction. Every finding
uses the same `(machine_id, recorded_at, rule_id)` idempotency key as v0.4. A processing,
inference, or persistence failure leaves the QoS 1 message unacknowledged. Invalid input
is acknowledged and discarded. An exact identity duplicate is idempotent; the repository
compares an existing reading before writing findings and raises a permanent conflict if
the same `(machine_id, recorded_at)` identifies different measurements.

The MQTT 5 consumer requests a persistent session with a stable client ID and a bounded
Receive Maximum. This preserves broker-side QoS state across reconnects for the configured
expiry period while limiting unacknowledged inbound work.

## Alert delivery semantics

When alerting is enabled, the telemetry transaction inserts immutable evidence into
`anomaly_alert_outbox` for configured severities. Its natural finding identity prevents
duplicate outbox rows on QoS redelivery. The consumer has no webhook dependency and an
external outage does not delay MQTT acknowledgement after the database commits.

The dispatcher claims available rows with `FOR UPDATE SKIP LOCKED`, assigns a bounded
lease, and increments the attempt count. It marks delivery only after a 2xx response;
failures clear the lease and schedule capped exponential backoff. The configured lease
must exceed the worst-case serial duration of the claimed batch. A crash after remote
acceptance but before the delivery update can resend the event, so the deterministic
event UUID is also the HTTP `Idempotency-Key`. This is at-least-once delivery, not
exactly-once delivery.

## Operational visibility

The consumer composition root shares one thread-safe runtime-observability object between
the application service, MQTT adapter, and monitoring server. The application service
depends only on `TelemetryProcessingObserver`; it has no HTTP or Prometheus dependency.
The standard-library monitoring adapter exposes `/healthz`, `/readyz`, and `/metrics`.
Metrics contain bounded aggregate outcomes rather than machine identifiers or payloads.
The model count and aggregate scored/uncovered counters expose registry coverage without
creating a machine-ID metric label.

The database adapter reports availability through an optional composition callback. A
failed open, save, or training read makes the database gauge and readiness false; the next
successful operation restores them. The application service remains unaware of database
and monitoring technology, while permanent telemetry identity conflicts continue to count
as a healthy database interaction.

## Operational boundaries

Isolation Forest detects statistical rarity, not equipment failure and not causality.
Handling of late readings at or before the training boundary, labelled outcome evaluation,
human model approval, key rotation, registry archival policy, destination-specific alert
escalation policy, production backup scheduling/off-site retention, retention/compression, managed-service
infrastructure, and automatic deployment remain explicit future work. PSI indicates
distribution change, not failure causality or predictive accuracy.

The database hash chain detects mutation only while at least one trusted earlier head is
available. Signed v0.16 checkpoints provide that anchor. Their attestation private key is
separate from the model-signing key, and the verifier needs only the checkpoint, expected
chain ID, attestation public key, and no database connection. Scheduling, immutable
external retention, key rotation, and checkpoint freshness policy remain deployment
responsibilities.

## Deployment boundary

The base Kubernetes manifests deploy the consumer, alert dispatcher, simulator,
monitoring service, model-registry claim, and network policies. They do not embed a broker,
database,
passwords, certificates, private signing keys, or production SQL migration credentials.
Runtime values come from a ConfigMap and named Secrets; the consumer mounts only the
model verification public key. The Azure overlay selects an Azure Files CSI storage class
and an ACR image. Database schema migration remains an explicit release prerequisite.

Standard Kubernetes `NetworkPolicy` cannot select external dependencies by DNS name. The
base therefore defaults application pods to deny and permits only DNS, monitoring ingress,
HTTPS port 443, MQTT/TLS port 8883, and PostgreSQL port 5432. Production overlays must
narrow destination
CIDRs or use a CNI with FQDN-aware policy. Enforcement also depends on the cluster CNI.
