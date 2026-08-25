# ADR 0006: Add offline Isolation Forest alongside deterministic rules

- Status: Accepted
- Date: 2026-08-13

## Context

Independent thresholds cannot detect unusual combinations that remain individually
inside known limits. Training inside the MQTT callback would mix model lifecycle with
message delivery, make behavior nondeterministic, and risk corrupting the live baseline.

## Decision

Train a machine-specific Isolation Forest in an explicit offline command from bounded
TimescaleDB history. Store a versioned artifact in a trusted local model volume and
require its embedded machine identity to match the configured inference machine when
loading it. Compose the loaded model with the existing rules through an application-owned
detector port.
Keep ML disabled until an operator trains and explicitly enables a compatible artifact.

## Consequences

- Known safety rules always remain active and explainable.
- Live ingestion performs inference only; it never mutates the model.
- A model cannot accidentally score telemetry from another machine.
- Artifact incompatibility stops enabled ML rather than silently degrading.
- joblib/pickle requires a trusted artifact supply chain.
- v0.7 adds a local per-machine registry, v0.9 adds pre-deserialization Ed25519
  verification, and v0.10 adds post-training anomaly-rate and PSI gates. Promotion,
  labelled outcome evaluation, key rotation, and durable evaluation evidence remain
  required before production use.
