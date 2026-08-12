# Architecture v0.1

## Scope

Version 0.1 proves the smallest useful event-streaming slice: a simulated hydraulic press
creates validated telemetry and publishes it via MQTT. Persistence, consuming services,
anomaly detection, APIs and orchestration are deliberately deferred.

```text
MachineSimulator
      │ creates Telemetry (Pydantic v2)
      ▼
MqttPublisher
      │ QoS 1 / MQTT 5
      ▼
Eclipse Mosquitto
      │
      ▼
factory/hall-a/press-01/telemetry
```

## Package boundaries

- `domain`: external data contract without MQTT or simulator dependencies.
- `simulator`: plausible normal-operation measurements.
- `infrastructure.mqtt`: Paho-specific broker adapter.
- `config`: validated environment-to-runtime configuration.
- `main`: composition, process lifecycle and retry policy.

The dependency direction points toward the contract: infrastructure and simulation depend
on `domain`, while `domain` depends only on Pydantic.

## Reliability characteristics

- QoS 1 requests at-least-once delivery between publisher and broker.
- The process handles `SIGTERM`/`SIGINT` and closes its MQTT session.
- Initial broker failures use bounded exponential retry.
- Mosquitto persists broker state in a named volume.
- The contract rejects unknown fields, impossible ranges and timezone-naive timestamps.

These are useful foundations, not a production guarantee. Authentication, TLS, secrets,
consumer idempotency, dead-letter handling and observability remain future work.

## Planned evolution

1. v0.2: MQTT consumer and contract validation at ingestion.
2. v0.3: PostgreSQL/TimescaleDB and a read API.
3. v0.4: transparent rule-based anomaly detection.
4. v0.5: multivariate anomaly detection where rules are insufficient.
5. v0.6: production-oriented observability and deployment hardening.
