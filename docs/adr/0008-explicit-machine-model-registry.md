# ADR 0008: Activate an explicit machine-model registry

- Status: Accepted
- Date: 2026-08-24

## Context

The MQTT subscription accepts telemetry from multiple machines, while v0.5/v0.6 loaded one
configured Isolation Forest. Loading every artifact found in a shared directory would let
stale files become active accidentally; silently skipping a configured machine would hide
incomplete ML coverage.

## Decision

- Store trusted artifacts as `<machine_id>.joblib` in one configured directory.
- Use `ML_MACHINE_IDS` as the ordered, deduplicated allowlist for training and activation.
- Fail startup when any configured artifact is missing or fails validation.
- Ignore extra files and route each reading only to the detector for its machine identity.
- Export only aggregate model-count and coverage metrics to keep cardinality bounded.

## Consequences

- One consumer can safely apply different models across its multi-machine subscription.
- The active model set is explicit and deployment failures are visible before readiness.
- Machines without an active model still receive deterministic rule evaluation.
- v0.9 adds detached signatures and verification before deserialization. Model hot reload,
  version promotion, key rotation, evaluation, and drift policy remain out of scope.

## Implementation note (v0.13)

ADR 0015 replaces root-level active files with a strict atomic manifest referencing
content-addressed signed versions. The explicit machine allowlist and all-or-nothing
startup invariant remain unchanged.
