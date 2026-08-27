# Operations and observability

## Local exposure

Docker Compose publishes MQTT, PostgreSQL, and monitoring ports on `127.0.0.1` only. The
services remain reachable to each other through the internal Compose network. Mosquitto
requires distinct simulator and consumer credentials and grants least-privilege topic
ACLs. The broker transport is still plaintext and the documented development passwords
remain unsuitable for a shared environment.

v0.8 supports username/password authentication, a custom CA, and optional client
certificate authentication for external brokers. TLS uses normal hostname and trust-chain
verification; there is no insecure-skip-verify setting. Client certificate and key paths
must be provided together.

The simulator identity can write only `factory/<area>/<machine>/telemetry`. The consumer
identity can read `factory/+/+/telemetry` and `$SYS/broker/version`; it has no write grant.
The broker regenerates its password and ACL files atomically at startup from the
specialized Compose variables. A production broker must provision equivalent controls
with managed, rotated credentials and verified TLS.

## Health probes

The consumer exposes three endpoints on port 8000:

- `/healthz` returns HTTP 200 while the monitoring process is alive;
- `/readyz` returns HTTP 200 only when the database pool is ready and the MQTT subscription
  is active, otherwise HTTP 503;
- `/metrics` returns Prometheus text exposition.

The Compose healthcheck uses `/readyz`. A disconnected broker, unavailable startup
database, or runtime persistence failure therefore makes the consumer unready. The next
successful database operation restores database readiness. Permanent telemetry identity
conflicts do not mark the database unavailable because the database interaction itself
succeeded.

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

## Image vulnerability gate

Application images pin their Python base manifest by digest, apply available Debian
security updates during the build, and remove `pip` from the runtime layer. CI pins the
Trivy action by commit and fails for high or critical OS/library findings that have an
available fix. This keeps the gate actionable; operators must still review the complete
report for unfixed or deferred upstream findings and rebuild when fixes become available.

Third-party Compose services are also pinned by manifest digest. A promoted production
image should itself be stored and deployed by digest because package repositories can
change after the source-level base pin.

## Model evaluation gate

The offline evaluator emits one structured `ml_model_evaluated` event per configured
machine. It includes bounded sample count, anomaly rate, per-feature PSI, maximum PSI,
pass/fail status, stable failed-gate names, and the exact artifact SHA-256. The same
immutable record is committed to
`model_evaluation_runs` before the log is emitted. The process exits unsuccessfully after
all machines are reported if any gate fails, so release automation can stop before the
explicit promotion step. The evidence table is separate from the online Prometheus
endpoint and deliberately records failed as well as successful evaluations.

```sql
SELECT machine_id, evaluated_at, model_id, artifact_sha256, passed, failed_gates
FROM model_evaluation_runs
ORDER BY evaluated_at DESC;
```

## Durable alert delivery

Alert routing is disabled until `ALERT_WEBHOOK_URL` is configured. The consumer uses the
configured minimum severity only to create an immutable outbox event in the existing
telemetry transaction. It never performs HTTP. The optional alert-dispatcher profile owns
delivery credentials and webhook connectivity:

```bash
ALERT_WEBHOOK_URL=https://alerts.example.test/events \
ALERT_WEBHOOK_BEARER_TOKEN=replace-me \
docker compose --profile alerts up -d
```

The dispatcher logs `anomaly_alert_delivered` after a successful 2xx response and
`anomaly_alert_failed` when it reschedules an attempt. Logs contain event IDs, attempt
numbers, retry delay, and exception type, but not credentials, response bodies, or full
URLs. If a lease expires and is replaced before the original worker records delivery or
retry state, that worker logs `anomaly_alert_lease_lost` and continues the rest of its
batch. The current lease owner remains responsible for the event. Operators can inspect
backlog health with:

```sql
SELECT
    COUNT(*) FILTER (WHERE delivered_at IS NULL) AS pending,
    MAX(attempt_count) FILTER (WHERE delivered_at IS NULL) AS maximum_attempts,
    MIN(created_at) FILTER (WHERE delivered_at IS NULL) AS oldest_pending
FROM anomaly_alert_outbox;
```

Delivery is at-least-once. Receivers must deduplicate the `Idempotency-Key`. HTTPS is
verified, redirects are rejected, and bearer credentials belong only to the dispatcher.
`ALERT_LEASE_SECONDS` must remain greater than `ALERT_BATCH_SIZE` multiplied by
`ALERT_REQUEST_TIMEOUT_SECONDS`. Persistent failures retry indefinitely with capped
backoff; dead-letter policy and destination-specific escalation remain deployment choices.

## Remaining production work

A shared or production environment still needs managed broker ACL provisioning and secret
rotation, backup/restore tests, alert rules, durable metric collection, migration rollback
policy, alert dead-letter/escalation policy, TimescaleDB retention/compression, human model
approval integration, registry-generation retention, and signing-key rotation.
