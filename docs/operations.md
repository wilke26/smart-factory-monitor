# Operations and observability

## Local exposure

Docker Compose publishes MQTT, PostgreSQL, and monitoring ports on `127.0.0.1` only. The
services remain reachable to each other through the internal Compose network. Anonymous
MQTT and the development database credential are intentionally retained for the one-command
local demonstration; neither is suitable for a shared environment.

## Health probes

The consumer exposes three endpoints on port 8000:

- `/healthz` returns HTTP 200 while the monitoring process is alive;
- `/readyz` returns HTTP 200 only when the database pool is ready and the MQTT subscription
  is active, otherwise HTTP 503;
- `/metrics` returns Prometheus text exposition.

The Compose healthcheck uses `/readyz`. A disconnected broker or unavailable startup
database therefore makes the consumer unready while its retry/reconnect behavior continues.

## Metrics

The consumer exports:

- `smart_factory_mqtt_connected` and `smart_factory_database_ready` gauges;
- `smart_factory_mqtt_messages_total{outcome=...}` for accepted, rejected, conflicted,
  and failed messages;
- processed and newly inserted telemetry counters;
- detected anomaly count;
- processing-duration sum and count.
- loaded machine-model count and aggregate scored/uncovered inference counters.

Metrics are process-local and reset on restart. They deliberately contain no machine IDs,
topics, payloads, or exception messages, keeping cardinality bounded and avoiding sensitive
telemetry in the monitoring channel.

## Delivery semantics

The consumer uses manual acknowledgement. It requests a persistent MQTT 5 session and an
explicit Receive Maximum. Valid telemetry is acknowledged only after the database
transaction; schema-invalid and permanent identity-conflict messages are acknowledged and
discarded. Unexpected application or infrastructure failures remain unacknowledged for
redelivery.

## Remaining production work

A shared or production environment still needs TLS, client authentication and topic ACLs,
managed secrets, backup/restore tests, alert rules, durable metric collection, migration
rollback policy, TimescaleDB retention/compression, and model promotion/signing.
