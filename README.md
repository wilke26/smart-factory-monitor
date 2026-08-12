# Smart Factory Monitor

A small, production-minded Smart Factory learning project. Version **0.1** simulates a
hydraulic press, validates each measurement through a Pydantic v2 data contract and
publishes it via MQTT 5 to Eclipse Mosquitto.

## v0.1 acceptance criterion

```bash
docker compose up --build
```

starts Mosquitto and the simulator. The simulator continuously publishes to:

```text
factory/hall-a/press-01/telemetry
```

Example payload:

```json
{
  "machine_id": "press-01",
  "timestamp": "2026-08-12T12:30:15.123Z",
  "temperature_c": 68.4,
  "vibration_mm_s": 2.7,
  "power_kw": 17.3,
  "production_rate": 44
}
```

## Observe the messages

In a second terminal, while the stack is running:

```bash
docker compose exec mosquitto \
  mosquitto_sub -h localhost -t 'factory/hall-a/press-01/telemetry' -v
```

Stop the stack with `Ctrl+C`, then remove its containers with:

```bash
docker compose down
```

## Configure it

Docker Compose provides useful defaults. To customize them:

```bash
cp .env.example .env
```

Common settings are `MACHINE_ID`, `FACTORY_AREA`, `PUBLISH_INTERVAL_SECONDS` and
`SIMULATOR_SEED`. With defaults, the topic is exactly the v0.1 acceptance topic.

> Security note: the included Mosquitto configuration permits anonymous, unencrypted
> access for local development. Do not expose port 1883 to an untrusted network.

## Local Python development

Requirements: Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest --cov=smart_factory
ruff check .
ruff format --check .
mypy
```

The CI quality gate requires at least 80% branch-aware coverage.

To run the simulator outside Docker, start the broker first and override its hostname:

```bash
docker compose up mosquitto
MQTT_HOST=localhost smart-factory-simulator
```

## Repository map

```text
src/smart_factory/domain/          Pydantic telemetry contract
src/smart_factory/simulator/       Hydraulic-press simulator
src/smart_factory/infrastructure/  MQTT publishing adapter
tests/unit/                         Example-based tests
tests/property/                     Hypothesis round-trip property
tests/integration/                  Producer/contract boundary test
docker/mosquitto/                   Local broker configuration
docs/adr/                           Architectural decisions
.github/workflows/ci.yml            Quality and container checks
```

See [architecture](docs/architecture.md), [data contract](docs/data-contract.md),
[AI-assisted development](docs/ai-assisted-development.md) and the
[architectural decisions](docs/adr/).

## Scope and roadmap

v0.1 intentionally contains no database, API, anomaly detector or Kubernetes manifests.
Those features arrive only after the MQTT slice works end to end:

- v0.2: MQTT consumer and validation
- v0.3: TimescaleDB persistence and read API
- v0.4: rule-based anomaly detection
- v0.5: ML-assisted multivariate detection
- v0.6: observability and deployment hardening

## License

MIT
