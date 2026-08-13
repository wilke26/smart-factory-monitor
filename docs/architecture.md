# Architecture v0.5

## Scope

Version 0.5 adds offline-trained, multivariate anomaly inference alongside the v0.4
deterministic rules. It deliberately excludes online learning, an HTTP API, automatic
model promotion, and production model operations.

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

The artifact validates format version, exact feature order, target machine, estimator
type, and scikit-learn version. Because joblib has pickle semantics, the model volume is
a trust boundary and must not accept untrusted uploads.

Missing, unreadable, and incompatible artifacts are normalized to `MlArtifactError`.
That permanent startup/configuration error is deliberately outside the MQTT/database
retry policy, so an enabled consumer fails fast with an actionable cause.

## Delivery and persistence semantics

Rules and ML are evaluated before the existing TimescaleDB transaction. Every finding
uses the same `(machine_id, recorded_at, rule_id)` idempotency key as v0.4. A processing,
inference, or persistence failure leaves the QoS 1 message unacknowledged. Invalid input
is acknowledged and discarded.

## Operational boundaries

Isolation Forest detects statistical rarity, not equipment failure and not causality.
Training data quality, hold-out evaluation, drift, model approval, registry/signing,
metrics, alerts, secrets, TLS, backups, and deployment automation remain explicit v0.6+
work.
