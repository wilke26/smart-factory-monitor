# Smart Factory Monitor

Version **0.2** is a small, production-minded Smart Factory telemetry pipeline. A
simulator publishes validated machine readings to Eclipse Mosquitto; an independent
consumer subscribes to telemetry topics, validates every JSON message with Pydantic v2,
and passes accepted `TelemetryReading` objects to a transport-independent application
service.

There is intentionally no database, HTTP API, anomaly detection, or ML yet.

## Quick start

```bash
docker compose up --build
```

This starts:

- `mosquitto`: MQTT 5 broker on `localhost:1883`;
- `simulator`: publishes to `factory/hall-a/press-01/telemetry`;
- `consumer`: subscribes to `factory/+/+/telemetry`, validates, and processes messages.

The application logs are newline-delimited JSON. Look for `telemetry_published`,
`telemetry_accepted`, and `telemetry_processed` events.

Observe raw messages in another terminal:

```bash
docker compose exec mosquitto \
  mosquitto_sub -h localhost -t 'factory/+/+/telemetry' -v
```

Stop the stack with `Ctrl+C`, then run `docker compose down`.

## Data flow

```text
MachineSimulator
      │ validated TelemetryReading → JSON
      ▼
MqttPublisher ── factory/<area>/<machine>/telemetry ──► Mosquitto
                                                            │
                                                            ▼
                                                   MqttTelemetryConsumer
                                                   decode + Pydantic validate
                                                            │
                                              TelemetryReading only
                                                            ▼
                                              TelemetryApplicationService
```

The MQTT adapter is the trust boundary. It never forwards malformed JSON,
schema-invalid messages, malformed topics, or a payload whose `machine_id` disagrees
with its topic. Rejections are logged without including raw payloads.

The application service imports neither Paho MQTT nor JSON code. Future HTTP, file, or
replay adapters can invoke the same `TelemetryHandler` port.

## Telemetry contract

```json
{
  "machine_id": "press-01",
  "timestamp": "2026-08-12T12:30:15.123000Z",
  "temperature_c": 68.4,
  "vibration_mm_s": 2.7,
  "power_kw": 17.3,
  "production_rate": 44
}
```

Unknown fields and type coercion are rejected, and timestamps require a UTC offset. The
numeric safety bounds are documented in [docs/data-contract.md](docs/data-contract.md).
`Telemetry` remains an alias for `TelemetryReading`, preserving the v0.1 public contract.

## Configuration

Copy `.env.example` to `.env` to override Compose defaults.

| Variable | Default outside Docker | Purpose |
|---|---|---|
| `MQTT_HOST` | `localhost` | Broker hostname |
| `MQTT_PORT` | `1883` | Broker port |
| `MQTT_KEEPALIVE` | `60` | MQTT keepalive seconds |
| `MQTT_QOS` | `1` | Publish and subscribe QoS |
| `MQTT_CLIENT_ID` | `smart-factory-simulator` | Publisher client ID |
| `MQTT_CONSUMER_CLIENT_ID` | `smart-factory-consumer` | Subscriber client ID |
| `MQTT_TOPIC_FILTER` | `factory/+/+/telemetry` | Consumer subscription |
| `FACTORY_AREA` | `hall-a` | Simulator area/topic segment |
| `MACHINE_ID` | `press-01` | Simulator machine/topic segment |
| `PUBLISH_INTERVAL_SECONDS` | `2.0` | Publish interval |
| `SIMULATOR_SEED` | empty | Optional deterministic seed |
| `LOG_LEVEL` | `INFO` | Structured log level |

> The local Mosquitto configuration permits anonymous, unencrypted access. Do not expose
> port 1883 to an untrusted network.

## Local development

Python 3.12 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
mypy
pytest --cov=smart_factory
python -m build
docker compose config --quiet
```

Tests cover the contract, configuration, application service, logging, MQTT callbacks,
valid/invalid ingestion pipelines, and property-based JSON round trips. CI checks Python
3.12 and 3.13 and enforces at least 80% branch-aware coverage.

Run the services outside Docker with a reachable broker:

```bash
MQTT_HOST=localhost smart-factory-consumer
MQTT_HOST=localhost smart-factory-simulator
```

## Design notes

- [Architecture](docs/architecture.md)
- [Data contract](docs/data-contract.md)
- [ADR 0001: MQTT transport](docs/adr/0001-mqtt-for-telemetry-transport.md)
- [ADR 0002: local anonymous broker](docs/adr/0002-anonymous-local-broker.md)
- [ADR 0003: MQTT/application separation](docs/adr/0003-separate-mqtt-adapter-from-application-service.md)
- [AI-assisted development](docs/ai-assisted-development.md)

v0.3 can add persistence behind an outbound application port without rewriting the
current application service or MQTT adapter.
