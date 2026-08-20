# Architecture v0.6

## Scope

Version 0.6 retains the offline-trained multivariate anomaly inference from v0.5 and adds
operational hardening: bounded persistent MQTT sessions, identity-conflict detection,
health/readiness probes, aggregate metrics, tracked schema migrations, dependency audits,
and loopback-only host port publication. It deliberately excludes online learning, a
business HTTP API, automatic model promotion, and production model operations.

```text
Offline path                         Online path
telemetry_readings                   MQTT → validation → application service
        │                                                │
        ▼                                                ▼
model-trainer → trusted artifact     CompositeAnomalyDetector
                     │                ├── rules (always)
                     └───────────────►└── Isolation Forest (opt-in)
                                                       │
                                                       ▼ one transaction
                                      telemetry_readings + anomaly_findings
```

## Dependency direction

- `domain` owns validated telemetry, finding contracts, and deterministic rules.
- `application` owns the technology-neutral `AnomalyDetector` port, detector composition,
  processing orchestration, and persistence ports.
- `infrastructure.ml` owns scikit-learn training, artifact I/O, and inference.
- `infrastructure.database` supplies both atomic persistence and bounded historical reads.
- `consumer_main` and `train_model_main` are separate composition roots.

The real-time application service sees only the detector protocol. It neither imports
scikit-learn nor decides whether ML is enabled.

## Model lifecycle boundary

Training reads a bounded window for one machine and uses a fixed random seed. It writes
the artifact atomically, but does not promote or activate it. Operators explicitly
restart the consumer with ML enabled after training. The consumer fails closed on a
missing or incompatible enabled model rather than silently changing detection behavior.

The artifact validates format version, exact feature order, configured target machine,
estimator type, and scikit-learn version. Because joblib has pickle semantics, the model
volume is a trust boundary and must not accept untrusted uploads.

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

## Operational boundaries

Isolation Forest detects statistical rarity, not equipment failure and not causality.
Training data quality, hold-out evaluation, drift, model approval, registry/signing,
alerts, production secrets, TLS/client identities, backups, retention/compression,
model evaluation, and deployment automation remain explicit v0.7+ work.
