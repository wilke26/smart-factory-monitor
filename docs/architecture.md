# Architecture v0.4

## Scope

Version 0.4 adds deterministic anomaly detection and durable findings to the v0.3
telemetry path. It stops before APIs and machine learning.

```text
MQTT → validation → TelemetryApplicationService
                            │
                            ├── RuleBasedAnomalyDetector → AnomalyFinding(s)
                            │
                            └── TelemetryRepository port
                                        │ one transaction
                                        ▼
                              telemetry_readings
                              anomaly_findings
```

## Dependency direction

- `domain` owns `TelemetryReading`, `AnomalyFinding`, severities, thresholds, and the
  pure rule evaluator.
- `application` orchestrates detection and persistence through ports. It knows no MQTT,
  Psycopg, or SQL.
- `infrastructure.mqtt` converts untrusted payloads into validated application input.
- `infrastructure.database` atomically stores a reading and all its findings.
- `consumer_main` supplies configured thresholds and composes the adapters.

The detector has no I/O and evaluates all rules so simultaneous symptoms remain
visible. Findings contain enough evidence to explain every decision without re-running
the current configuration.

## Persistence and idempotency

`telemetry_readings` remains a TimescaleDB hypertable. `anomaly_findings` references a
reading through `(machine_id, recorded_at)` and uses
`(machine_id, recorded_at, rule_id)` as its primary key. Reading and findings share the
same Psycopg transaction. QoS 1 redelivery therefore neither loses the relationship nor
duplicates findings.

The idempotent `schema-migrate` Compose service applies the anomaly table to both fresh
databases and retained v0.3 volumes before the consumer starts. This is deliberately a
small release migration; a versioned migration framework is still required before
multiple evolving production environments exist.

## Delivery and failure semantics

- Valid input is acknowledged only after detection and the database transaction finish.
- Invalid input is logged, acknowledged, and discarded.
- Detection or persistence failure leaves the MQTT message unacknowledged.
- Rule thresholds are validated against the outer telemetry contract bounds.
- Structured anomaly logs include evidence, not raw payloads.

## Operational boundaries

The rules are known-condition monitoring, not prediction. They do not learn baselines,
correlations, drift, or machine-specific behavior. Local credentials and published
ports remain development conveniences. Production still requires secrets, TLS,
authorization, backups, migration tracking, metrics, and alert routing.
