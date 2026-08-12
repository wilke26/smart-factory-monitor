# Architecture v0.3

## Scope

Version 0.3 adds durable time-series persistence to the v0.2 ingestion flow. It stops
before APIs and anomaly detection.

```text
MachineSimulator → MqttPublisher → Mosquitto → MqttTelemetryConsumer
                                                    │ validated TelemetryReading
                                                    ▼
                                      TelemetryApplicationService
                                                    │ TelemetryRepository port
                                                    ▼
                                      PsycopgTelemetryRepository
                                                    │ parameterized INSERT
                                                    ▼
                               TimescaleDB telemetry_readings hypertable
```

## Dependency direction

- `domain` owns the strict Pydantic v2 `TelemetryReading` contract.
- `application` defines the inbound `TelemetryHandler`, outbound
  `TelemetryRepository`, and orchestration service. It knows neither transport nor SQL.
- `infrastructure.mqtt` translates untrusted MQTT messages into validated application
  input.
- `infrastructure.database` implements the persistence port with Psycopg 3.
- `consumer_main` composes and owns both adapters and their lifecycles.

## Time-series model

`telemetry_readings` is a TimescaleDB hypertable partitioned on `recorded_at`. The
machine timestamp is preserved separately from `ingested_at`, which records arrival at
the database. The composite primary key `(machine_id, recorded_at)` includes the
partitioning column and provides the idempotency key.

The database repeats essential contract constraints as defense in depth. SQL uses bound
parameters. Schema creation is an idempotent container initialization script; changing
an already deployed schema will require explicit migrations in a later release.

## Delivery and failure semantics

- MQTT QoS 1 can redeliver messages.
- The consumer enables manual acknowledgements.
- A valid message is acknowledged only after the repository transaction commits.
- Invalid input is acknowledged and discarded after structured warning logging.
- A storage/application exception remains unacknowledged and is logged; duplicate
  delivery is safe because insertion uses `ON CONFLICT DO NOTHING`.
- The Psycopg pool bounds concurrent connections and checks a connection before use.

This is not exactly-once delivery: the design combines at-least-once transport with an
idempotent database write to achieve effectively-once storage for the chosen natural
key.

## Operational boundaries

Compose waits for both Mosquitto and TimescaleDB health before starting the consumer.
Local credentials and published ports are development conveniences. Production still
requires secret management, TLS, topic authorization, database backups, migrations,
metrics, and alerting.
