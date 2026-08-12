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
idempotency key and ignore duplicate inserts.

## Consequences

- PostgreSQL semantics and TimescaleDB time-series capabilities are available together.
- MQTT QoS 1 redelivery does not create duplicate rows for the same reading.
- The application service can be tested without a database and can accept another
  repository implementation later.
- Local Compose gains a stateful service and credential configuration.
- Initial SQL is sufficient for a fresh development volume; future schema changes need
  a real migration tool before production deployment.
