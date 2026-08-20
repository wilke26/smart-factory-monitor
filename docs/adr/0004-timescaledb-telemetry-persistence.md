# ADR 0004: Persist telemetry in TimescaleDB behind an outbound port

- Status: Accepted
- Date: 2026-08-12

## Context

Telemetry must survive process restarts and support future time-window queries,
aggregations, trend analysis, and anomaly detection. The application layer must not
become coupled to SQL or one database driver.

## Decision

Store accepted readings in a TimescaleDB hypertable partitioned by measurement time.
Expose persistence to the application through `TelemetryRepository`; implement it with
Psycopg 3 and a bounded connection pool. Use `(machine_id, recorded_at)` as a natural
idempotency key. Exact duplicate inserts are idempotent; reuse of that identity with
different measurement values is rejected as a permanent conflict.

## Consequences

- PostgreSQL semantics and TimescaleDB time-series capabilities are available together.
- MQTT QoS 1 redelivery does not create duplicate rows for the same reading, while an
  identity collision cannot attach findings to unrelated stored measurements.
- The application service can be tested without a database and can accept another
  repository implementation later.
- Local Compose gains a stateful service and credential configuration.
- Fresh volumes use entrypoint initialization; existing volumes receive ordered SQL files
  through a tracked, transactional Compose migration job.
- A production deployment still needs coordinated migration rollout and rollback policy.
