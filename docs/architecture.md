# Architecture v0.8

## Scope

Version 0.8 retains the machine-model registry and adds a deployment security boundary.
Both MQTT adapters can authenticate and use server-verified TLS or mutual TLS. Hardened
Kubernetes manifests run the two application processes as a fixed non-root identity with
read-only root filesystems, explicit resources, probes, external secrets, and a shared
model volume. Managed MQTT, PostgreSQL/TimescaleDB, PKI, and secret lifecycle remain
deployment-owned dependencies.

```text
Offline path                         Online path
telemetry_readings                   MQTT → validation → application service
        │                                                │
        ▼                                                ▼
model-trainer → trusted registry     CompositeAnomalyDetector
                     │                ├── rules (always)
                     └───────────────►└── MachineModelRegistry (opt-in)
                                          └── Isolation Forest by machine
                                                       │
                                                       ▼ one transaction
                                      telemetry_readings + anomaly_findings
```

## Dependency direction

- `domain` owns validated telemetry, finding contracts, and deterministic rules.
- `application` owns the technology-neutral `AnomalyDetector` port, detector composition,
  processing orchestration, and persistence ports.
- `infrastructure.ml` owns scikit-learn training, artifact I/O, registry validation,
  and machine-aware inference dispatch.
- `infrastructure.database` supplies both atomic persistence and bounded historical reads.
- `consumer_main` and `train_model_main` are separate composition roots.

The real-time application service sees only the detector protocol. It neither imports
scikit-learn nor decides whether ML is enabled.

## Model lifecycle boundary

Training reads a bounded window for one machine and uses a fixed random seed. It writes
the artifact atomically, but does not promote or activate it. Operators explicitly
restart the consumer with ML enabled after training. The consumer fails closed on a
missing or incompatible enabled model rather than silently changing detection behavior.

The registry requires `<machine_id>.joblib` for every configured machine and activates no
unconfigured file. Each artifact validates format version, exact feature order, filename
identity, estimator type, and scikit-learn version. Because joblib has pickle semantics,
the model volume is a trust boundary and must not accept untrusted uploads.

Missing, unreadable, and incompatible artifacts are normalized to `MlArtifactError`.
That permanent startup/configuration error is deliberately outside the MQTT/database
retry policy, so an enabled consumer fails fast with an actionable cause.

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

## Operational boundaries

Isolation Forest detects statistical rarity, not equipment failure and not causality.
Training data quality, hold-out evaluation, drift, model approval, registry/signing,
alerts, backups, retention/compression, model evaluation, broker ACL provisioning,
managed-service infrastructure, and automatic deployment remain explicit v0.9+ work.

## Deployment boundary

The base Kubernetes manifests deploy only the consumer, simulator, monitoring service,
and model-registry claim. They do not embed a broker, database, passwords, certificates,
or production SQL migration credentials. Runtime values come from a ConfigMap and named
Secrets; the Azure overlay selects an Azure Files CSI storage class and an ACR image.
Database schema migration remains an explicit release prerequisite.
