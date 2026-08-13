# Smart Factory Monitor

Version **0.4** is a small, production-minded Smart Factory telemetry pipeline. A
simulator publishes validated machine readings to Eclipse Mosquitto; an independent
consumer subscribes to telemetry topics, validates every JSON message with Pydantic v2,
detects explainable rule violations, and atomically persists readings plus findings in
TimescaleDB through a transport-independent application service.

There is intentionally no HTTP API or ML yet.

## Quick start

```bash
docker compose up --build
```

This starts:

- `mosquitto`: MQTT 5 broker on `localhost:1883`;
- `timescaledb`: PostgreSQL 16 with the TimescaleDB extension on `localhost:5432`;
- `simulator`: publishes to `factory/hall-a/press-01/telemetry`;
- `schema-migrate`: applies the idempotent v0.4 anomaly schema and exits successfully;
- `consumer`: validates messages, evaluates rules, and stores readings and findings.

The application logs are newline-delimited JSON. Look for `telemetry_published`,
`telemetry_accepted`, `telemetry_processed`, and `anomaly_detected` events.

Observe raw messages in another terminal:

```bash
docker compose exec mosquitto \
  mosquitto_sub -h localhost -t 'factory/+/+/telemetry' -v
```

Stop the stack with `Ctrl+C`, then run `docker compose down`.

Inspect persisted readings:

```bash
docker compose exec timescaledb psql \
  -U smart_factory -d smart_factory \
  -c 'SELECT machine_id, recorded_at, temperature_c FROM telemetry_readings ORDER BY recorded_at DESC LIMIT 5;'
```

Inspect detected anomalies:

```bash
docker compose exec timescaledb psql \
  -U smart_factory -d smart_factory \
  -c 'SELECT machine_id, recorded_at, rule_id, severity, observed_value, threshold FROM anomaly_findings ORDER BY recorded_at DESC LIMIT 10;'
```

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
                                                            │
                                             RuleBasedAnomalyDetector
                                                            │ TelemetryRepository
                                                            ▼
                                             PsycopgTelemetryRepository
                                                            │
                                                            ▼
                                              TimescaleDB transaction
                                           ┌───────────────────────┐
                                           │ telemetry_readings    │
                                           │ anomaly_findings      │
                                           └───────────────────────┘
```

The MQTT adapter is the trust boundary. It never forwards malformed JSON,
schema-invalid messages, malformed topics, or a payload whose `machine_id` disagrees
with its topic. Rejections are logged without including raw payloads.

The application service imports neither Paho MQTT, Psycopg, SQL, nor JSON code. MQTT is
an inbound adapter; TimescaleDB is an outbound adapter. Future input transports or
storage implementations can replace either side independently.

## Rule-based anomaly detection

Rules are deterministic, independently evaluated, and trigger only after a threshold is
crossed (not when equal). One reading can therefore produce multiple findings.

| Rule | Condition | Severity |
|---|---|---|
| `temperature-high` | `temperature_c > 90` | high |
| `vibration-high` | `vibration_mm_s > 7` | high |
| `power-high` | `power_kw > 30` | high |
| `production-rate-low` | `production_rate < 25` | medium |

Each finding records the rule, metric, observed value, threshold, operator, message, and
severity. These are operational defaults, configurable through the environment; they
are distinct from the wider transport-validity bounds in the data contract.

MQTT acknowledgements are manual. Valid readings are acknowledged only after the
database transaction succeeds. Invalid input is acknowledged and discarded so poison
messages do not loop. The `(machine_id, recorded_at)` primary key and `ON CONFLICT DO
NOTHING` make QoS 1 redelivery idempotent.

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
| `DATABASE_URL` | local PostgreSQL URL | Psycopg connection string |
| `DATABASE_POOL_MIN_SIZE` | `1` | Minimum database connections |
| `DATABASE_POOL_MAX_SIZE` | `4` | Maximum database connections |
| `DATABASE_CONNECT_TIMEOUT_SECONDS` | `10.0` | Startup database timeout |
| `ANOMALY_MAX_TEMPERATURE_C` | `90.0` | High-temperature threshold |
| `ANOMALY_MAX_VIBRATION_MM_S` | `7.0` | High-vibration threshold |
| `ANOMALY_MAX_POWER_KW` | `30.0` | High-power threshold |
| `ANOMALY_MIN_PRODUCTION_RATE` | `25` | Low-production threshold |

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
valid/invalid ingestion pipelines, rule boundaries and multi-rule findings, atomic
idempotent persistence, and property-based JSON round trips. CI checks Python 3.12 and
3.13 and enforces at least 80% branch-aware coverage.

Run the services outside Docker with a reachable broker:

```bash
MQTT_HOST=localhost smart-factory-consumer
MQTT_HOST=localhost smart-factory-simulator
```

## Design notes

- [Architecture](docs/architecture.md)
- [Data contract](docs/data-contract.md)
- [Anomaly rules and findings](docs/anomaly-detection.md)
- [ADR 0001: MQTT transport](docs/adr/0001-mqtt-for-telemetry-transport.md)
- [ADR 0002: local anonymous broker](docs/adr/0002-anonymous-local-broker.md)
- [ADR 0003: MQTT/application separation](docs/adr/0003-separate-mqtt-adapter-from-application-service.md)
- [ADR 0004: TimescaleDB persistence](docs/adr/0004-timescaledb-telemetry-persistence.md)
- [ADR 0005: deterministic rules](docs/adr/0005-rule-based-anomaly-detection.md)
- [AI-assisted development](docs/ai-assisted-development.md)

v0.5 can add multivariate ML anomaly detection alongside these transparent rules where
individual thresholds are insufficient.
