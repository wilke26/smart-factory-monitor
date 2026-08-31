# Smart Factory Monitor

Version **0.20.1** is a small, production-minded Smart Factory telemetry pipeline. A
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
vulnerabilities. v0.10 adds a signed-artifact-bound reference distribution and an
explicit offline evaluation command that gates post-training data on sample count,
anomaly rate, and per-feature Population Stability Index (PSI). v0.11 adds durable,
severity-filtered webhook alert routing through a transactional outbox and a separately
deployable, lease-based dispatcher. v0.11.1 treats a concurrently replaced or expired
dispatcher lease as an expected delivery outcome, logs it without sensitive error text,
and continues processing the remaining batch. v0.12 persists every signed post-training
model-evaluation result as immutable, queryable audit evidence before reporting success or
gate failure. v0.13 binds that evidence to the exact signed artifact and adds explicit,
atomic multi-machine promotion plus generation-based rollback. v0.14 adds checksummed,
versioned database-and-model backup bundles and a non-destructive recovery drill that
restores only into isolated targets and verifies the recovered signed registry.
v0.14.1 restores TimescaleDB in its required restore mode and defers foreign-key
validation until hypertable restoration is complete. v0.15 records model promotion and
rollback as fail-closed, append-only operator events whose SHA-256 chain can be verified
independently. v0.16 signs verified chain-head checkpoints with a separate Ed25519
attestation key so retained evidence can reveal even a complete database-side rewrite.
v0.17 adds audited attestation-key rotation with a transition signed by both the previous
and replacement keys. A separately pinned root fingerprint anchors the transition chain,
so checkpoints created before and after rotation remain verifiable without silently
trusting an unconnected replacement key. v0.17.1 validates that the active key is still
reachable from that root before mutation and serializes the complete audited rotation so
concurrent operators cannot create a fork or record a stale previous key.
v0.18 makes Python installation reproducible through separate hash-pinned build,
runtime, ML, and development locks; pins every third-party GitHub Action to a full commit;
and adds a fail-closed Kubernetes release renderer that binds all application workloads
to one immutable registry digest. v0.19 adds release-tag-only package provenance where the
repository plan supports it and a deterministic release manifest on every matching tag.
CI creates and validates a complete SPDX inventory of the locked ML runtime without
publishing that dependency inventory; the manifest retains its digest and package count so
an independently retained SBOM can be correlated later. v0.20 encrypts those exact SBOM
bytes for an externally controlled RSA recipient, stores only ciphertext with the durable
GitHub Release, requires an annotated release tag reachable from `main`, and separates
build, optional attestation, and release-publication permissions into isolated jobs.

There is intentionally no HTTP API, online learning, or automatic model promotion.

## Quick start

```bash
docker compose up --build
```

This starts:

- `mosquitto`: MQTT 5 broker on `localhost:1883`;
- `timescaledb`: PostgreSQL 16 with the TimescaleDB extension on `localhost:5432`;
- `simulator`: publishes to `factory/hall-a/press-01/telemetry`;
- `schema-migrate`: applies all idempotent database migrations and exits successfully;
- `model-key-init`: creates or reuses the local Ed25519 model-signing key pair and exits;
- `consumer`: validates messages, evaluates enabled detectors, and stores results.

Published host ports bind to `127.0.0.1` only. The consumer exposes liveness, readiness,
and Prometheus metrics on `http://127.0.0.1:8000`.

ML is disabled by default until a machine-specific model has been trained. Known safety
rules are always active.

The application logs are newline-delimited JSON. Look for `telemetry_published`,
`telemetry_accepted`, `telemetry_processed`, and `anomaly_detected` events.

Alerting remains disabled without a destination. Start the optional dispatcher and enable
outbox creation with a verified HTTPS endpoint:

```bash
ALERT_WEBHOOK_URL=https://alerts.example.test/events \
ALERT_WEBHOOK_BEARER_TOKEN=replace-me \
docker compose --profile alerts up --build
```

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

Inspect pending or delivered alert events:

```bash
docker compose exec timescaledb psql \
  -U smart_factory -d smart_factory \
  -c 'SELECT event_id, severity, attempt_count, delivered_at FROM anomaly_alert_outbox ORDER BY created_at DESC LIMIT 10;'
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
                                           ┌────────────────────────┐
                                           │ telemetry_readings     │
                                           │ anomaly_findings       │
                                           │ anomaly_alert_outbox   │
                                           └───────────┬────────────┘
                                                       │ leased batch
                                                       ▼
                                              AlertDispatcher
                                                       │ HTTPS + Idempotency-Key
                                                       ▼
                                                external webhook
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

## Durable webhook alerting

When `ALERT_WEBHOOK_URL` is configured, findings at or above
`ALERT_MINIMUM_SEVERITY` create an outbox row in the same transaction as the reading and
finding. A QoS redelivery therefore cannot create a second alert event, and an external
webhook outage does not block telemetry ingestion.

The separate `smart-factory-alert-dispatcher` claims bounded batches with database leases,
sends the immutable anomaly evidence as JSON, and marks a row delivered only after a 2xx
response. Failures are rescheduled with capped exponential backoff. Delivery is
at-least-once: a crash after the webhook accepts an event but before the database update
can resend it, so every request carries the stable `event_id` as `Idempotency-Key`.
If another dispatcher has already replaced an expired lease, the stale worker skips that
state transition and continues its remaining batch instead of terminating the process.

HTTPS certificate and hostname verification use the platform trust store or an optional
CA file. Redirects are rejected so credentials cannot cross to another endpoint. Plain
HTTP requires the explicit development-only `ALERT_WEBHOOK_ALLOW_INSECURE_HTTP=true`.

## Multivariate ML anomaly detection

The Isolation Forest complements rules by detecting unusual combinations across all
four numeric telemetry features. Training is an explicit offline operation over recent
readings from one machine; the live consumer never retrains a model.

After at least 100 readings for every configured training machine have been collected:

```bash
docker compose --profile tools run --rm model-trainer
```

After a separate post-training window has arrived, evaluate and explicitly promote the
complete candidate set before restarting the consumer with the approved registry:

```bash
docker compose --profile tools run --rm model-evaluator
AUDIT_ACTOR=<trusted-identity> AUDIT_REASON=<ticket-or-reason> \
AUDIT_CORRELATION_ID=<uuid> docker compose --profile tools run --rm model-promoter
ML_ANOMALY_DETECTION_ENABLED=true docker compose up -d --force-recreate consumer
```

The comma-separated `ML_MACHINE_IDS` setting controls training, evaluation, promotion,
and the active registry. The trainer writes `<machine_id>.joblib` and its detached
signature below `candidates/`; these files are never active. Evaluation stores the exact
candidate SHA-256 with its gate result. Promotion requires a passed result for the same
machine, model ID, and digest, then publishes signed content-addressed versions and
atomically replaces `active.json` for the complete batch. With ML enabled, the consumer
loads only that manifest, verifies every digest and signature before joblib/pickle
deserialization, and then validates artifact format, feature order, machine identity,
estimator type, and exact scikit-learn runtime version. Extra files are not activated.
An enabled consumer fails fast with a dedicated artifact error if the model is missing,
unreadable, or invalid; permanent model configuration failures never enter the
infrastructure retry loop.

Artifact format v2 also records decile-based training proportions for every feature.
The evaluator verifies the signed artifact, loads only readings with timestamps after the
recorded `training_window_end`, and fails unless the bounded window meets all configured gates: minimum
sample count, maximum predicted anomaly rate, and maximum per-feature PSI. Its structured
`ml_model_evaluated` log contains the complete result for each machine. The same result is
stored in `model_evaluation_runs`, including its evaluation UUID, artifact identity and digest,
training boundary, sample count, anomaly rate, per-feature PSI, decision, and failed gates.
A successful evaluation authorizes the separate promotion command for those exact bytes;
the evaluator itself never activates, copies, or replaces a deployed model.

```sql
SELECT evaluated_at, machine_id, model_id, artifact_sha256, passed, failed_gates
FROM model_evaluation_runs
ORDER BY evaluated_at DESC;
```

Every active manifest is archived under `manifests/<generation-id>.json`. Roll back by
supplying an explicit earlier generation; rollback revalidates every referenced digest
and signature and activates a new generation without modifying history:

```bash
ML_ROLLBACK_GENERATION_ID=<generation-uuid> \
AUDIT_ACTOR=<trusted-identity> AUDIT_REASON=<ticket-or-reason> \
AUDIT_CORRELATION_ID=<uuid> \
  docker compose --profile tools run --rm model-rollback
ML_ANOMALY_DETECTION_ENABLED=true docker compose up -d --force-recreate consumer
```

The artifact still uses joblib/pickle semantics. Signature verification prevents an
untrusted or corrupted file from reaching the unsafe deserializer, provided the public
verification key is distributed through a trusted channel and the signing private key
remains restricted to the trainer. Signing proves provenance and integrity; evaluation
adds quality evidence, but neither is human approval. Versioned promotion and rollback
are explicit operator actions. Durable evaluation evidence is an audit trail, not an
approval. v0.9 format-v1 artifacts must be retrained for v0.10.

Promotion and rollback write a `started` event before any registry mutation and then a
`succeeded` or `failed` event. The database rejects updates and deletes, while every row
binds the previous hash to the canonical event content. Verify the complete chain with:

```bash
docker compose --profile tools run --rm audit-verifier
```

Export a self-contained signed checkpoint and verify it without database access:

```bash
AUDIT_CHAIN_ID=smart-factory-local AUDIT_CHECKPOINT_NAME=manual-2026-08-27.json \
  docker compose --profile tools run --rm audit-checkpoint-exporter
AUDIT_CHAIN_ID=smart-factory-local AUDIT_CHECKPOINT_NAME=manual-2026-08-27.json \
  docker compose --profile tools run --rm --no-deps audit-checkpoint-verifier
```

The checkpoint contains the verified event count and chain head, a deployment-specific
chain ID, creation time, and the fingerprint of a separate attestation key. Its Ed25519
signature is stored in the same immutable JSON envelope. Copy the file from
`audit-checkpoints/` to storage controlled independently from the database. CI uploads
its checkpoint as a workflow artifact and proves that modified checkpoint content no
longer verifies. Rotate the local attestation key explicitly with an authenticated actor,
reason, correlation ID, and the same deployment chain ID:

```bash
AUDIT_ACTOR=<trusted-identity> AUDIT_REASON=<ticket-or-reason> \
AUDIT_CORRELATION_ID=<uuid> AUDIT_CHAIN_ID=smart-factory-local \
  docker compose --profile tools run --rm audit-key-rotator
```

The transition is immutable and signed by both keys. Verification begins at
`AUDIT_ATTESTATION_ROOT_KEY_ID_PATH` and accepts a checkpoint key only if every transition
from that root is valid and belongs to the expected chain. Production must pin the root
fingerprint outside the writable keyring boundary; the local Compose volume is only a
development demonstration of the protocol.

`AUDIT_ACTOR` is an asserted identity. Production automation must derive it from an
authenticated workload or operator context rather than accepting arbitrary user input.

## Backup and recovery drill

The recovery profile backs up the complete PostgreSQL database, model registry, and model
verification public key. Stop database and model writers before creating a coordinated
bundle; the database dump itself uses a consistent PostgreSQL snapshot.

```bash
docker compose stop consumer simulator alert-dispatcher
BACKUP_ID=manual-2026-08-27 \
  docker compose --profile recovery run --rm backup-create
```

The bundle is written below `BACKUP_DIRECTORY` (`./backups` by default) only after every
payload exists. It contains format metadata and SHA-256 checksums. It deliberately excludes
all service credentials and the signing private key, which requires separate protected
disaster recovery.

A recovery drill verifies the bundle before restoring. The target database must differ
from the active database, and models are written only to dedicated recovery volumes:

```bash
BACKUP_ID=manual-2026-08-27 RESTORE_DATABASE_NAME=smart_factory_restore \
  docker compose --profile recovery run --rm backup-restore
docker compose --profile recovery run --rm recovery-model-verifier
docker compose exec timescaledb psql \
  -U smart_factory -d smart_factory_restore \
  -c 'SELECT COUNT(*) FROM telemetry_readings;'
```

This proves that the local artifacts can be restored without replacing live state. A
production runbook must additionally define encrypted off-site storage, scheduling,
retention, access control, RPO/RTO, managed-database recovery, and private-key custody.

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
| `ML_MODEL_DIRECTORY` | `/models` | Candidate, versioned, and active model-registry root |
| `ML_MACHINE_IDS` | `press-01` | Comma-separated machines trained and activated |
| `ML_CONTAMINATION` | `0.05` | Expected anomaly fraction during training |
| `ML_MINIMUM_TRAINING_SAMPLES` | `100` | Minimum history required to train |
| `ML_TRAINING_LIMIT` | `10000` | Maximum recent readings loaded for training |
| `ML_EVALUATION_MINIMUM_SAMPLES` | `30` | Minimum post-training evaluation window |
| `ML_EVALUATION_LIMIT` | `1000` | Maximum post-training readings evaluated per machine |
| `ML_MAX_EVALUATION_ANOMALY_RATE` | `0.15` | Highest accepted model anomaly fraction |
| `ML_MAX_FEATURE_PSI` | `0.25` | Highest accepted PSI for any feature |
| `ML_SIGNATURE_PUBLIC_KEY_PATH` | empty | Required Ed25519 public key for ML inference |
| `ML_SIGNING_PRIVATE_KEY_PATH` | empty | Required Ed25519 private key for offline training |
| `AUDIT_ACTOR` | empty | Required trusted identity for promotion and rollback |
| `AUDIT_REASON` | empty | Required reason or ticket for the privileged operation |
| `AUDIT_CORRELATION_ID` | empty | Required operation correlation UUID |
| `AUDIT_CHAIN_ID` | `smart-factory-local` in Compose | Deployment identity bound into checkpoints |
| `AUDIT_CHECKPOINT_PATH` | `/audit-checkpoints/checkpoint.json` in Compose | Signed checkpoint artifact |
| `AUDIT_ATTESTATION_PRIVATE_KEY_PATH` | empty | Export-only Ed25519 attestation key |
| `AUDIT_ATTESTATION_PUBLIC_KEY_PATH` | empty | Independent checkpoint-verification key |
| `AUDIT_ATTESTATION_KEYRING_PATH` | empty | Archived public keys and dual-signed transitions |
| `AUDIT_ATTESTATION_ROOT_KEY_ID_PATH` | empty | Independently pinned root-key fingerprint |
| `ALERT_WEBHOOK_URL` | empty | Verified HTTPS destination; empty disables alert outbox creation |
| `ALERT_WEBHOOK_ALLOW_INSECURE_HTTP` | `false` | Development-only opt-in for plain HTTP |
| `ALERT_WEBHOOK_BEARER_TOKEN` | empty | Optional dispatcher-only bearer credential |
| `ALERT_WEBHOOK_CA_CERT_PATH` | empty | Optional private CA for the webhook |
| `ALERT_MINIMUM_SEVERITY` | `high` | Lowest severity routed (`medium` or `high`) |
| `ALERT_BATCH_SIZE` | `20` | Maximum events leased per dispatch cycle |
| `ALERT_POLL_INTERVAL_SECONDS` | `2.0` | Delay between dispatch cycles |
| `ALERT_REQUEST_TIMEOUT_SECONDS` | `5.0` | Per-request timeout |
| `ALERT_LEASE_SECONDS` | `120` | Batch lease; must exceed batch size × request timeout |
| `ALERT_RETRY_BASE_SECONDS` | `5.0` | Initial delivery retry delay |
| `ALERT_RETRY_MAX_SECONDS` | `300.0` | Maximum delivery retry delay |
| `MONITORING_HOST` | `0.0.0.0` | Monitoring listener inside the consumer container |
| `MONITORING_PORT` | `8000` | Monitoring listener port |
| `MONITORING_HOST_PORT` | `8000` | Loopback-only Compose host port |
| `BACKUP_DIRECTORY` | `./backups` | Ignored host directory for versioned recovery bundles |
| `BACKUP_ID` | empty | Explicit safe identifier for backup and restore commands |
| `RESTORE_DATABASE_NAME` | `smart_factory_restore` | Isolated database created by a recovery drill |

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
python -m pip install --require-hashes -r requirements/dev.lock
python -m pip install --require-hashes -r requirements/build.lock
python -m pip install --no-deps -e .
python -m pip check
ruff check .
ruff format --check .
mypy
python -m pip_audit
pytest --cov=smart_factory
python -m build --no-isolation
docker compose config --quiet
kubectl kustomize deploy/kubernetes/overlays/azure >/tmp/smart-factory-azure.yaml
```

The lockfiles are generated from `pyproject.toml`; see
[`requirements/README.md`](requirements/README.md) for the controlled refresh workflow.
CI regenerates them on Python 3.12 and rejects an uncommitted difference.

Tests cover the contract, configuration, application service, observability, MQTT callbacks,
valid/invalid ingestion pipelines, rule boundaries, model training/inference, pre-load
signature verification, post-training anomaly/PSI gates, atomic idempotent persistence,
durable evaluation evidence, approval-gated atomic promotion, generation rollback,
fail-closed hash-chained operator auditing,
signed portable audit checkpoints, tamper rejection, and trust-preserving key rotation,
transactional alert creation, leased retry delivery, real webhook requests, and
property-based JSON round trips. CI also creates and checksum-verifies a database/model
backup, restores it into isolated targets, compares persisted evidence, and loads the
recovered signed registry. CI checks Python 3.12 and 3.13, audits dependencies,
renders Kubernetes policy, scans the built consumer image, exercises a denied broker
topic, trains, evaluates, promotes, and reloads signed models in Docker, runs the complete
Compose ingestion path, and enforces at least 80% branch-aware coverage.

Run the services outside Docker with a reachable broker:

```bash
MQTT_HOST=localhost smart-factory-consumer
MQTT_HOST=localhost smart-factory-simulator
ALERT_WEBHOOK_URL=https://alerts.example.test/events smart-factory-alert-dispatcher
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
- [ADR 0012: post-training model evaluation gates](docs/adr/0012-post-training-model-evaluation-gates.md)
- [ADR 0013: transactional alert outbox](docs/adr/0013-transactional-alert-outbox.md)
- [ADR 0014: durable model-evaluation evidence](docs/adr/0014-durable-model-evaluation-evidence.md)
- [ADR 0015: atomic model promotion and rollback](docs/adr/0015-atomic-model-promotion-and-rollback.md)
- [ADR 0016: verifiable isolated recovery drills](docs/adr/0016-verifiable-isolated-recovery-drills.md)
- [ADR 0017: hash-chained operator audit trail](docs/adr/0017-hash-chained-operator-audit-trail.md)
- [ADR 0018: externally retained signed audit checkpoints](docs/adr/0018-signed-audit-checkpoints.md)
- [ADR 0019: dual-signed audit-attestation key rotation](docs/adr/0019-dual-signed-audit-key-rotation.md)
- [ADR 0020: reproducible build and immutable release inputs](docs/adr/0020-reproducible-build-and-release-inputs.md)
- [ADR 0021: release-only provenance and private SBOM](docs/adr/0021-release-only-provenance-and-private-sbom.md)
- [ADR 0022: durable encrypted release evidence](docs/adr/0022-durable-encrypted-release-evidence.md)
- [Operations and observability](docs/operations.md)
- [Multi-machine model operations](docs/model-operations.md)
- [Kubernetes and Azure deployment](docs/deployment-kubernetes-azure.md)
- [AI-assisted development](docs/ai-assisted-development.md)

Future versions can add retention/compression policies, registry-bound image provenance,
production backup scheduling and off-site retention, human model-approval integration,
registry archival policy, security-configuration audit events, externally administered
root-key custody, checkpoint scheduling and immutable retention, and infrastructure-as-code for managed dependencies. Local Compose
remains a development environment rather than a production deployment.
