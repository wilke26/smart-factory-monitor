# Architecture v0.2

## Scope

Version 0.2 extends the publishing slice with a complete inbound flow. It consumes MQTT
telemetry, validates the untrusted boundary, and invokes an in-memory application use
case. Persistence, APIs, and anomaly detection remain deferred.

```text
domain.TelemetryReading
      ▲              ▲
      │              │
simulator       application.TelemetryApplicationService
      │              ▲ implements TelemetryHandler
      ▼              │
MqttPublisher   MqttTelemetryConsumer
      │              ▲
      └──► Mosquitto ─┘
```

## Dependency direction

- `domain` owns the strict Pydantic v2 data contract.
- `application` accepts only `TelemetryReading` through a small inbound protocol and
  knows nothing about MQTT, topics, payload bytes, or Paho.
- `infrastructure.mqtt` owns connections, subscriptions, topic interpretation, JSON
  validation, rejection behavior, and transport logging.
- `main` and `consumer_main` are the two composition roots.

The consumer rejects invalid JSON/UTF-8, invalid schemas, malformed telemetry topics,
and payload/topic machine-ID mismatches. Expected input failures do not stop the MQTT
network loop. Unexpected application failures are logged and isolated. Raw payloads are
not logged.

## Reliability characteristics

- QoS 1 requests at-least-once delivery; later stateful consumers must be idempotent.
- Both processes handle `SIGTERM`/`SIGINT` and close their MQTT sessions.
- Broker failures use bounded retry delays.
- Stable client IDs and Paho reconnect backoff support reconnection.
- Mosquitto persists broker state in a named volume.
- Compose waits for broker health before starting both clients.

These remain development foundations. Authentication, TLS, per-topic authorization,
dead-letter handling, metrics, and production deployment are future work.
