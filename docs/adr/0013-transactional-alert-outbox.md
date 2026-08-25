# ADR 0013: Route anomaly alerts through a transactional outbox

- Status: Accepted
- Date: 2026-08-25

## Context

Calling an external webhook inside telemetry processing would couple MQTT acknowledgement
to an unrelated network dependency. A webhook outage would leave valid messages
unacknowledged, increase redelivery pressure, and risk either duplicate notifications or
lost alerts if persistence and delivery were separate non-atomic steps.

## Decision

When alerting is configured, insert severity-eligible anomaly evidence into
`anomaly_alert_outbox` in the same transaction as the reading and finding. Use the finding
identity as the outbox primary key and derive a stable event UUID.

Run webhook delivery in a separate application process. It claims bounded rows with
`FOR UPDATE SKIP LOCKED`, a lease token, and a lease expiry. It marks delivery only after a
2xx response and otherwise clears the lease and schedules capped exponential backoff.
Require the lease duration to exceed the worst-case serial request time for a full batch.
Send the event UUID as `Idempotency-Key`, verify HTTPS normally, reject redirects, and keep
bearer credentials outside the consumer.

## Consequences

- Telemetry persistence and alert creation are atomic.
- Webhook availability does not affect MQTT processing or acknowledgement.
- Multiple dispatcher replicas cannot normally own the same unexpired row.
- Delivery is at-least-once; receivers must deduplicate the stable event ID.
- Retries survive restarts and expose attempt state in TimescaleDB.
- Plain HTTP requires an explicit development-only opt-in.
- Dead-letter handling, escalation policy, and durable alert metrics remain future work.

## Implementation note (v0.11.1)

A worker can lose its lease after expiry if another dispatcher claims the row before the
original worker records delivery or retry state. This is an expected concurrency outcome:
the stale worker logs the event ID and attempted state transition, skips the stale update,
and continues processing the remaining batch. The current lease owner remains responsible
for the row.
