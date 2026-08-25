# Architecture v0.10.0

## Scope

Version 0.10 retains the v0.9 integrity and least-privilege boundaries and adds an
independent model-quality gate. Signed artifacts carry per-feature training reference
distributions. The evaluator verifies those artifacts, reads only post-training telemetry,
and produces a pass/fail result without changing the online registry.

```text
Offline paths                                      Online path
telemetry_readings                   MQTT → validation → application service
        │                                                │
        ▼                                                ▼
model-trainer → reference + sign → registry        CompositeAnomalyDetector
 private key              artifact + sig            ├── rules (always)
                                  │                 └── MachineModelRegistry (opt-in)
 public key ── verify ─────────────┤                      └── Isolation Forest by machine
                                  ▼
                    model-evaluator ← post-training telemetry
                    sample/anomaly/PSI quality gates
                                                       │
                                                       ▼ one transaction
                                      telemetry_readings + anomaly_findings
```

## Dependency direction

- `domain` owns validated telemetry, finding contracts, and deterministic rules.
- `application` owns the technology-neutral `AnomalyDetector` port, detector composition,
  processing orchestration, and persistence ports.
- `infrastructure.ml` owns scikit-learn training, artifact signing and verification,
  reference distributions, offline evaluation, registry validation, and machine-aware
  inference dispatch.
- `infrastructure.database` supplies both atomic persistence and bounded historical reads.
- `consumer_main`, `train_model_main`, and `evaluate_model_main` are separate composition
  roots.

The real-time application service sees only the detector protocol. It neither imports
scikit-learn nor decides whether ML is enabled.

## Model lifecycle boundary

Training reads a bounded window for one machine and uses a fixed random seed. It signs the
serialized bytes with an offline Ed25519 private key and atomically publishes the detached
signature and artifact, but does not promote or activate them. Operators explicitly
restart the consumer with ML enabled after training. The consumer has only the public key
and fails closed on a missing, unsigned, invalid, or incompatible enabled model.

The registry requires `<machine_id>.joblib` and `<machine_id>.joblib.sig` for every
configured machine and activates no unconfigured file. It verifies the exact bytes read
into memory before passing those same bytes to joblib, then validates format version,
exact feature order, filename identity, estimator type, and scikit-learn version. Because
joblib has pickle semantics, public-key distribution and private-key custody remain trust
boundaries even though the model volume itself no longer grants authority to deserialize.

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
model approval, durable evaluation history, key rotation, alerts, backups, retention/compression, managed-service
infrastructure, and automatic deployment remain explicit future work. PSI indicates
distribution change, not failure causality or predictive accuracy.

## Deployment boundary

The base Kubernetes manifests deploy only the consumer, simulator, monitoring service,
model-registry claim, and network policies. They do not embed a broker, database,
passwords, certificates, private signing keys, or production SQL migration credentials.
Runtime values come from a ConfigMap and named Secrets; the consumer mounts only the
model verification public key. The Azure overlay selects an Azure Files CSI storage class
and an ACR image. Database schema migration remains an explicit release prerequisite.

Standard Kubernetes `NetworkPolicy` cannot select external dependencies by DNS name. The
base therefore defaults application pods to deny and permits only DNS, monitoring ingress,
MQTT/TLS port 8883, and PostgreSQL port 5432. Production overlays must narrow destination
CIDRs or use a CNI with FQDN-aware policy. Enforcement also depends on the cluster CNI.
