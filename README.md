# Smart Factory Monitor

Version **0.9.0** is a small, production-minded Smart Factory telemetry pipeline. A
simulator publishes validated machine readings to Eclipse Mosquitto; an independent
consumer subscribes to telemetry topics, validates every JSON message with Pydantic v2,
combines deterministic rules with optional multivariate Isolation Forest inference, and
atomically persists readings plus findings in TimescaleDB. v0.6 hardens identity-conflict
handling, MQTT delivery, local network exposure, schema migrations, dependency auditing,
health probes, and metrics. v0.7 adds an explicit multi-machine model registry so one
consumer can safely route each reading to its configured machine-specific model. v0.8
adds verified MQTT TLS/mTLS, broker credentials, and a hardened Kubernetes/AKS deployment
baseline without committing secrets or certificates. v0.8.1 keeps runtime readiness
accurate when the database becomes unavailable after startup and restores it after the
next successful database operation. v0.9 authenticates the bundled broker with
least-privilege topic ACLs, signs every ML artifact with Ed25519 before publication,
verifies it before deserialization, adds default-deny Kubernetes network policy, pins
container bases by digest, and scans the built image for actionable high and critical
vulnerabilities.

There is intentionally no HTTP API, online learning, or automatic model promotion yet.

## Quick start

```bash
docker compose up --build
```

This starts:

- `mosquitto`: MQTT 5 broker on `localhost:1883`;
- `timescaledb`: PostgreSQL 16 with the TimescaleDB extension on `localhost:5432`;
- `simulator`: publishes to `factory/hall-a/press-01/telemetry`;
- `schema-migrate`: applies the idempotent v0.4 anomaly schema and exits successfully;
- `model-key-init`: creates or reuses the local Ed25519 model-signing key pair and exits;
- `consumer`: validates messages, evaluates enabled detectors, and stores results.

Published host ports bind to `127.0.0.1` only. The consumer exposes liveness, readiness,
and Prometheus metrics on `http://127.0.0.1:8000`.

ML is disabled by default until a machine-specific model has been trained. Known safety
rules are always active.

The application logs are newline-delimited JSON. Look for `telemetry_published`,
`telemetry_accepted`, `telemetry_processed`, and `anomaly_detected` events.

Observe raw messages in another terminal:

```bash
docker compose exec mosquitto \
  mosquitto_sub -h localhost \
  -u smart-factory-consumer -P consumer_dev \
  -t 'factory/+/+/telemetry' -v
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
                                            CompositeAnomalyDetector
                                             ├── deterministic rules
                                             └── optional model registry
                                                  └── Isolation Forest by machine
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
NOTHING` make exact QoS 1 redelivery idempotent. If the same identity arrives with
different measurement values, the consumer logs an identity conflict, stores no
inconsistent findings, and acknowledges the permanently invalid collision.

The consumer requests a bounded MQTT 5 receive window and a persistent broker session.
The stable consumer client ID and configurable session expiry allow the broker to retain
QoS messages across temporary disconnects and process restarts.

## Multivariate ML anomaly detection

The Isolation Forest complements rules by detecting unusual combinations across all
four numeric telemetry features. Training is an explicit offline operation over recent
readings from one machine; the live consumer never retrains a model.

After at least 100 readings for every configured training machine have been collected:

```bash
docker compose --profile tools run --rm model-trainer
ML_ANOMALY_DETECTION_ENABLED=true docker compose up -d --force-recreate consumer
```

The comma-separated `ML_MACHINE_IDS` setting controls both the training batch and the
active registry. The trainer writes `<machine_id>.joblib` and a detached
`<machine_id>.joblib.sig` for each configured machine to the shared `ml-models` volume. It
signs the exact serialized bytes with Ed25519 and publishes the signature and artifact
using atomic replacement. With ML enabled, the consumer requires every configured pair,
verifies the signature before any joblib/pickle deserialization, and then validates the
filename-to-machine mapping, artifact format, feature order, machine identity, estimator
type, and exact scikit-learn runtime version. Extra stale files are not activated.
An enabled consumer fails fast with a dedicated artifact error if the model is missing,
unreadable, or invalid; permanent model configuration failures never enter the
infrastructure retry loop.

The artifact still uses joblib/pickle semantics. Signature verification prevents an
untrusted or corrupted file from reaching the unsafe deserializer, provided the public
verification key is distributed through a trusted channel and the signing private key
remains restricted to the trainer. Signing proves provenance and integrity; it is not an
approval workflow. Immutable promotion, rollback, evaluation datasets, and drift
monitoring remain production-hardening work.

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
| `MQTT_SESSION_EXPIRY_SECONDS` | `86400` | Broker session retention for the consumer |
| `MQTT_RECEIVE_MAXIMUM` | `20` | Maximum unacknowledged inbound QoS messages |
| `MQTT_USERNAME` | empty | Optional broker identity |
| `MQTT_PASSWORD` | empty | Optional broker password; requires a username |
| `SIMULATOR_MQTT_USERNAME` | `smart-factory-simulator` in Compose | Local publisher identity |
| `SIMULATOR_MQTT_PASSWORD` | `simulator_dev` in Compose | Local publisher development password |
| `CONSUMER_MQTT_USERNAME` | `smart-factory-consumer` in Compose | Local subscriber identity |
| `CONSUMER_MQTT_PASSWORD` | `consumer_dev` in Compose | Local subscriber development password |
| `MQTT_TLS_ENABLED` | `false` | Enable verified TLS |
| `MQTT_TLS_CA_CERT_PATH` | empty | Optional private CA bundle |
| `MQTT_TLS_CLIENT_CERT_PATH` | empty | Optional mTLS client certificate |
| `MQTT_TLS_CLIENT_KEY_PATH` | empty | Optional mTLS private key; paired with certificate |
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
| `ML_ANOMALY_DETECTION_ENABLED` | `false` | Enable model loading and inference |
| `ML_MODEL_DIRECTORY` | `/models` | Trusted machine-model registry directory |
| `ML_MACHINE_IDS` | `press-01` | Comma-separated machines trained and activated |
| `ML_CONTAMINATION` | `0.05` | Expected anomaly fraction during training |
| `ML_MINIMUM_TRAINING_SAMPLES` | `100` | Minimum history required to train |
| `ML_TRAINING_LIMIT` | `10000` | Maximum recent readings loaded for training |
| `ML_SIGNATURE_PUBLIC_KEY_PATH` | empty | Required Ed25519 public key for ML inference |
| `ML_SIGNING_PRIVATE_KEY_PATH` | empty | Required Ed25519 private key for offline training |
| `MONITORING_HOST` | `0.0.0.0` | Monitoring listener inside the consumer container |
| `MONITORING_PORT` | `8000` | Monitoring listener port |
| `MONITORING_HOST_PORT` | `8000` | Loopback-only Compose host port |

> The local Mosquitto configuration requires separate simulator and consumer credentials
> and restricts both identities with topic ACLs, but it remains unencrypted and uses
> documented development passwords. Do not expose port 1883 to an untrusted network.

The simulator may publish only its exact configured telemetry topic. The consumer may
read telemetry and the broker-version health topic but cannot publish. For a shared
broker, provision equivalent server-side identities and ACLs, rotate managed credentials,
enable TLS, and mount the required CA/client files. TLS hostname and certificate
verification are never disabled.

## Health and metrics

The monitoring listener uses only Python's standard library and exposes aggregate data;
it does not include machine IDs or raw payloads.

```bash
curl --fail http://127.0.0.1:8000/healthz
curl --fail http://127.0.0.1:8000/readyz
curl --fail http://127.0.0.1:8000/metrics
```

- `/healthz` reports that the process and monitoring thread are alive.
- `/readyz` succeeds only while the database pool is ready and MQTT is subscribed.
- `/metrics` exports connection gauges, message outcomes, processing duration, inserts,
  anomaly counts, loaded-model count, and covered/uncovered ML inference counts in
  Prometheus text format.

## Local development

Python 3.12 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
mypy
python -m pip_audit
pytest --cov=smart_factory
python -m build
docker compose config --quiet
kubectl kustomize deploy/kubernetes/overlays/azure >/tmp/smart-factory-azure.yaml
```

Tests cover the contract, configuration, application service, observability, MQTT callbacks,
valid/invalid ingestion pipelines, rule boundaries, model training/inference, pre-load
signature verification, atomic idempotent persistence, and property-based JSON round
trips. CI checks Python 3.12 and 3.13, audits dependencies, renders Kubernetes policy,
scans the built consumer image, exercises a denied broker topic, trains and reloads a
signed model in Docker, runs the complete Compose ingestion path, and enforces at least
80% branch-aware coverage.

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
- [ADR 0002: original local anonymous broker (superseded)](docs/adr/0002-anonymous-local-broker.md)
- [ADR 0003: MQTT/application separation](docs/adr/0003-separate-mqtt-adapter-from-application-service.md)
- [ADR 0004: TimescaleDB persistence](docs/adr/0004-timescaledb-telemetry-persistence.md)
- [ADR 0005: deterministic rules](docs/adr/0005-rule-based-anomaly-detection.md)
- [ADR 0006: offline Isolation Forest](docs/adr/0006-offline-isolation-forest.md)
- [ADR 0007: v0.6 operational hardening](docs/adr/0007-operational-hardening.md)
- [ADR 0008: explicit machine-model registry](docs/adr/0008-explicit-machine-model-registry.md)
- [ADR 0009: verified MQTT identity and Kubernetes baseline](docs/adr/0009-secure-mqtt-kubernetes-baseline.md)
- [ADR 0010: signed model artifacts](docs/adr/0010-signed-model-artifacts.md)
- [ADR 0011: least-privilege runtime and supply-chain baseline](docs/adr/0011-least-privilege-runtime-and-supply-chain.md)
- [Operations and observability](docs/operations.md)
- [Multi-machine model operations](docs/model-operations.md)
- [Kubernetes and Azure deployment](docs/deployment-kubernetes-azure.md)
- [AI-assisted development](docs/ai-assisted-development.md)

v0.10 can add alert routing, offline model evaluation and drift thresholds,
retention/compression policies, immutable image/model promotion, backup/restore tests,
and infrastructure-as-code for managed dependencies. Local Compose remains a development
environment rather than a production deployment.
