# ADR-0007: Bound delivery state and expose aggregate operational health

- Status: Accepted
- Date: 2026-08-20

## Context

The v0.5 pipeline validates and persists telemetry but leaves several operational contracts
implicit: MQTT sessions expire on disconnect by default, publish acknowledgement timeouts
are not distinguished from success, identity-key collisions can mix findings with an older
reading, and operators have no readiness or aggregate processing signals.

## Decision

- Treat `(machine_id, recorded_at)` as a natural identity: exact duplicates are idempotent,
  while different data under the same identity is a permanent acknowledged conflict.
- Require the configured machine ID when loading an ML artifact.
- Request a persistent MQTT 5 consumer session and explicit Receive Maximum.
- Fail a simulator publish when Paho did not confirm publication before the timeout.
- Expose dependency-free liveness, readiness, and bounded Prometheus metrics from the
  consumer process.
- Bind local Compose host ports to loopback, track applied SQL migrations, audit Python
  dependencies in CI, and run a full Compose ingestion smoke test.

## Consequences

- Temporary disconnects retain broker-side QoS state for a configured period.
- Permanent identity collisions do not redeliver forever or corrupt finding evidence.
- Operators and container orchestration can distinguish alive from ready.
- Monitoring remains intentionally aggregate and process-local; production collection and
  alert policy are separate deployment concerns.
- Anonymous MQTT and development credentials remain acceptable only for local Compose.
