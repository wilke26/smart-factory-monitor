# Operations and observability

## Local exposure

Docker Compose publishes MQTT, PostgreSQL, and monitoring ports on `127.0.0.1` only. The
services remain reachable to each other through the internal Compose network. Mosquitto
requires distinct simulator and consumer credentials and grants least-privilege topic
ACLs. The broker transport is still plaintext and the documented development passwords
remain unsuitable for a shared environment.

v0.8 supports username/password authentication, a custom CA, and optional client
certificate authentication for external brokers. TLS uses normal hostname and trust-chain
verification; there is no insecure-skip-verify setting. Client certificate and key paths
must be provided together.

The simulator identity can write only `factory/<area>/<machine>/telemetry`. The consumer
identity can read `factory/+/+/telemetry` and `$SYS/broker/version`; it has no write grant.
The broker regenerates its password and ACL files atomically at startup from the
specialized Compose variables. A production broker must provision equivalent controls
with managed, rotated credentials and verified TLS.

## Health probes

The consumer exposes three endpoints on port 8000:

- `/healthz` returns HTTP 200 while the monitoring process is alive;
- `/readyz` returns HTTP 200 only when the database pool is ready and the MQTT subscription
  is active, otherwise HTTP 503;
- `/metrics` returns Prometheus text exposition.

The Compose healthcheck uses `/readyz`. A disconnected broker, unavailable startup
database, or runtime persistence failure therefore makes the consumer unready. The next
successful database operation restores database readiness. Permanent telemetry identity
conflicts do not mark the database unavailable because the database interaction itself
succeeded.

## Metrics

The consumer exports:

- `smart_factory_mqtt_connected` and `smart_factory_database_ready` gauges;
- `smart_factory_mqtt_messages_total{outcome=...}` for accepted, rejected, conflicted,
  and failed messages;
- processed and newly inserted telemetry counters;
- detected anomaly count;
- processing-duration sum and count.
- loaded machine-model count and aggregate scored/uncovered inference counters.

Metrics are process-local and reset on restart. They deliberately contain no machine IDs,
topics, payloads, or exception messages, keeping cardinality bounded and avoiding sensitive
telemetry in the monitoring channel.

## Delivery semantics

The consumer uses manual acknowledgement. It requests a persistent MQTT 5 session and an
explicit Receive Maximum. Valid telemetry is acknowledged only after the database
transaction; schema-invalid and permanent identity-conflict messages are acknowledged and
discarded. Unexpected application or infrastructure failures remain unacknowledged for
redelivery.

## Image vulnerability gate

Application images pin their Python base manifest by digest, apply available Debian
security updates during the build, and remove `pip` from the runtime layer. CI pins the
Trivy action by commit and fails for high or critical OS/library findings that have an
available fix. This keeps the gate actionable; operators must still review the complete
report for unfixed or deferred upstream findings and rebuild when fixes become available.

Third-party Compose services are also pinned by manifest digest. A promoted production
image should itself be stored and deployed by digest because package repositories can
change after the source-level base pin.

## Reproducible build and release inputs

CI and Docker install only the committed hash-pinned dependency sets under
`requirements/`. The builder uses `build.lock`; normal processes use `runtime.lock`; ML
tools use `ml.lock`; tests and audits use `dev.lock`. CI regenerates all four locks on
Python 3.12 and fails on drift. Every external GitHub Action is pinned to a full commit,
with its reviewed release tag retained as a comment for update visibility.

Production Kubernetes manifests must be produced with an image digest:

```bash
python deploy/kubernetes/render-release.py \
  --image registry.example/smart-factory-monitor \
  --digest "$IMAGE_DIGEST" \
  --output /tmp/smart-factory-release.yaml
kubectl apply -f /tmp/smart-factory-release.yaml
```

The renderer rejects tags and malformed digests and verifies that consumer, simulator,
and alert dispatcher all resolve to the same immutable image. The ordinary Kustomize
overlay remains useful for review and local rendering but is not the production rollout
artifact.

## Release provenance and SBOM privacy

The release jobs run only for an annotated semantic release tag such as `v0.20.0`. The tag
must exactly match `project.version` in `pyproject.toml`, its commit must be reachable from
`origin/main`, and the quality matrix plus the full Compose job must pass before evidence is
created. Ordinary `main` pushes and pull requests do not create release evidence,
attestations, or releases.

Before creating the tag, generate an RSA recipient key of at least 3072 bits in an
independently controlled environment. Keep the encrypted private key and its passphrase out
of GitHub and the repository, back them up under the release-recovery policy, and configure
only the public key as the repository Actions secret:

```bash
umask 077
RELEASE_EVIDENCE_KEY_DIRECTORY=/secure/offline/release-evidence
mkdir -p "$RELEASE_EVIDENCE_KEY_DIRECTORY"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
  -aes-256-cbc -out "$RELEASE_EVIDENCE_KEY_DIRECTORY/private.pem"
openssl pkey -in "$RELEASE_EVIDENCE_KEY_DIRECTORY/private.pem" -pubout \
  -out "$RELEASE_EVIDENCE_KEY_DIRECTORY/public.pem"
gh secret set RELEASE_EVIDENCE_RECIPIENT_PUBLIC_KEY \
  < "$RELEASE_EVIDENCE_KEY_DIRECTORY/public.pem"
```

CI assembles the locked ML runtime and validates a complete SPDX JSON SBOM inside the
ephemeral build runner. It encrypts the exact document with AES-256-GCM, wraps the random
data key with RSA-OAEP-SHA256, and authenticates the SBOM filename, release version, and
revision. The plaintext is never transferred between jobs, uploaded, attached to the
release, or sent to Sigstore. The release manifest records both plaintext and ciphertext
digests plus package count, format, scope, algorithm, recipient-key fingerprint, and
ciphertext size. Retain old private keys by fingerprint when rotating the recipient.

`release-build` has no OIDC, attestation, or publication permission. `release-attest`
receives only the signing permissions and consumes already checksummed evidence.
`release-publish` receives only `contents: write`, verifies the transfer, and creates a
GitHub Release containing the wheel, source archive, manifest, checksums, and encrypted
SBOM. The one-day workflow artifact is only an inter-job transport; the GitHub Release is
the durable repository copy. Production retention still requires an independently
administered immutable mirror because deleting the release or repository removes that copy.

GitHub artifact attestations in private repositories require GitHub Enterprise Cloud. The
workflow therefore enables the attestation step automatically only for public repositories.
For a private Enterprise Cloud repository, set the repository Actions variable
`ENABLE_GITHUB_ATTESTATIONS=true`. Leave it unset for private Free, Pro, or Team repositories;
the durable release will still be created and the unsupported attestation job will be
skipped instead of failing publication.

After downloading a release, verify the ciphertext and package checksums and, where
present, the attested package against this repository:

```bash
cd dist
sha256sum --check SHA256SUMS
gh attestation verify smart_factory_monitor-0.20.0-py3-none-any.whl \
  --repo wilke26/smart-factory-monitor
```

Recover the private SBOM only in the controlled recovery environment. Supply an encrypted
private-key password through an environment variable rather than a command-line argument,
then compare the recovered plaintext digest with `sbom.sha256` in
`release-manifest.json`:

```bash
export RELEASE_EVIDENCE_PRIVATE_KEY_PASSWORD='<from-secret-manager>'
python scripts/release_evidence_crypto.py decrypt \
  --input smart_factory_monitor-0.20.0.ml-runtime.spdx.json.enc \
  --output recovered.ml-runtime.spdx.json \
  --private-key /secure/release-evidence-private.pem \
  --private-key-password-env RELEASE_EVIDENCE_PRIVATE_KEY_PASSWORD \
  --version 0.20.0 \
  --revision '<full-release-commit-sha>'
python - <<'PY'
import hashlib, json
from pathlib import Path
manifest = json.loads(Path("release-manifest.json").read_text())
actual = hashlib.sha256(Path("recovered.ml-runtime.spdx.json").read_bytes()).hexdigest()
assert actual == manifest["sbom"]["sha256"]
PY
unset RELEASE_EVIDENCE_PRIVATE_KEY_PASSWORD
```

Private-repository verification requires Enterprise Cloud and an authenticated GitHub CLI
identity with access.
If the repository becomes public, new GitHub attestations use public Sigstore transparency
infrastructure and must be treated as permanent public release records. Creating the tag is
therefore an explicit publication decision. This package attestation does not cover a later
container build; registry-bound container provenance remains separate work.

## Model evaluation gate

The offline evaluator emits one structured `ml_model_evaluated` event per configured
machine. It includes bounded sample count, anomaly rate, per-feature PSI, maximum PSI,
pass/fail status, stable failed-gate names, and the exact artifact SHA-256. The same
immutable record is committed to
`model_evaluation_runs` before the log is emitted. The process exits unsuccessfully after
all machines are reported if any gate fails, so release automation can stop before the
explicit promotion step. The evidence table is separate from the online Prometheus
endpoint and deliberately records failed as well as successful evaluations.

```sql
SELECT machine_id, evaluated_at, model_id, artifact_sha256, passed, failed_gates
FROM model_evaluation_runs
ORDER BY evaluated_at DESC;
```

## Durable alert delivery

Alert routing is disabled until `ALERT_WEBHOOK_URL` is configured. The consumer uses the
configured minimum severity only to create an immutable outbox event in the existing
telemetry transaction. It never performs HTTP. The optional alert-dispatcher profile owns
delivery credentials and webhook connectivity:

```bash
ALERT_WEBHOOK_URL=https://alerts.example.test/events \
ALERT_WEBHOOK_BEARER_TOKEN=replace-me \
docker compose --profile alerts up -d
```

The dispatcher logs `anomaly_alert_delivered` after a successful 2xx response and
`anomaly_alert_failed` when it reschedules an attempt. Logs contain event IDs, attempt
numbers, retry delay, and exception type, but not credentials, response bodies, or full
URLs. If a lease expires and is replaced before the original worker records delivery or
retry state, that worker logs `anomaly_alert_lease_lost` and continues the rest of its
batch. The current lease owner remains responsible for the event. Operators can inspect
backlog health with:

```sql
SELECT
    COUNT(*) FILTER (WHERE delivered_at IS NULL) AS pending,
    MAX(attempt_count) FILTER (WHERE delivered_at IS NULL) AS maximum_attempts,
    MIN(created_at) FILTER (WHERE delivered_at IS NULL) AS oldest_pending
FROM anomaly_alert_outbox;
```

Delivery is at-least-once. Receivers must deduplicate the `Idempotency-Key`. HTTPS is
verified, redirects are rejected, and bearer credentials belong only to the dispatcher.
`ALERT_LEASE_SECONDS` must remain greater than `ALERT_BATCH_SIZE` multiplied by
`ALERT_REQUEST_TIMEOUT_SECONDS`. Persistent failures retry indefinitely with capped
backoff; dead-letter policy and destination-specific escalation remain deployment choices.

## Backup and isolated restore

The `recovery` Compose profile creates a private, versioned bundle containing a PostgreSQL
custom dump, the model registry, its public verification key, metadata, and SHA-256
checksums. Quiesce the consumer, simulator, dispatcher, trainer, promoter, and rollback
tool before backup so the database snapshot and filesystem registry describe one operator-
selected point. Never copy the signing private key into this bundle.

```bash
docker compose stop consumer simulator alert-dispatcher
BACKUP_ID=manual-2026-08-27 \
  docker compose --profile recovery run --rm backup-create
```

Restore rejects checksum failures, mismatched metadata, unsafe archive paths, and attempts
to use the active database name. It creates an isolated database and replaces only the
dedicated recovery volumes. The normal registry loader then authenticates and validates
the restored models. Database restoration follows the TimescaleDB lifecycle: it enables
restore mode, restores everything except foreign keys, leaves restore mode, and only then
validates the deferred foreign keys against the completed hypertables:

```bash
BACKUP_ID=manual-2026-08-27 RESTORE_DATABASE_NAME=smart_factory_restore \
  docker compose --profile recovery run --rm backup-restore
docker compose --profile recovery run --rm recovery-model-verifier
```

CI performs this drill and compares telemetry, anomaly, alert, evaluation, operator-audit,
and migration row counts. The local workflow is proof of recoverability, not a production backup service.
Production still requires encrypted off-site copies, access logging, scheduled execution,
retention and deletion rules, RPO/RTO targets, periodic drills, and provider-specific
point-in-time recovery. Private signing-key recovery remains a separate security process.

## Remaining production work

A shared or production environment still needs managed broker ACL provisioning and secret
rotation, managed backup scheduling and off-site retention, alert rules, durable metric collection, migration rollback
policy, alert dead-letter/escalation policy, TimescaleDB retention/compression, human model
approval integration, registry-generation retention, and independently managed key custody.

v0.15 provides a database-enforced append-only and hash-chained audit trail for model
promotion and rollback. It records actor, reason, correlation ID, timestamp, previous and
resulting state, outcome, and bounded failure type; `smart-factory-verify-audit` recomputes
the complete chain. Production must still authenticate the asserted actor upstream,
restrict database ownership, export or externally attest the chain, define authorization,
query access, retention, archival, and deletion policy, and add event types for key
rotation and security-relevant configuration changes.

v0.16 can export a verified chain head as a write-once JSON envelope signed by a separate
Ed25519 attestation key. The corresponding verifier has no database dependency. CI stores
the checkpoint as a workflow artifact for 30 days and rejects modified content. A
production environment must use independently administered immutable storage, define
checkpoint cadence and maximum age, and alert on missing exports.

v0.17 adds explicit audited rotation. Run it only from an authorized operator context and
use the identical chain ID used by checkpoint export:

```bash
AUDIT_ACTOR=<trusted-identity> AUDIT_REASON=<ticket-or-reason> \
AUDIT_CORRELATION_ID=<uuid> AUDIT_CHAIN_ID=smart-factory-local \
  docker compose --profile tools run --rm audit-key-rotator
```

The command creates a replacement Ed25519 pair, archives its public key, and publishes a
transition signed by both the current and replacement private keys before activating the
new key. Verify at least one checkpoint from before and after rotation. Back up the
private key under the deployment's recovery policy, but distribute only public material
to verifiers.

v0.17.1 serializes the entire audited command with a lock in the writable keyring. It also
walks the complete transition path from the configured root to the active key before
writing the `started` event or staging replacement material. A concurrent invocation
waits and then observes the newly active key; a missing, forked, or modified trust path
aborts without starting a new rotation.

The trusted root fingerprint is the long-lived trust anchor. In production, mount or
inject `AUDIT_ATTESTATION_ROOT_KEY_ID_PATH` from storage controlled independently from
the writable keyring and active keys. Retain the root, every transition, every referenced
public key, and every checkpoint for the complete evidence lifetime. Alert on forks,
missing transitions, partial rotations, checkpoint staleness, and unexpected key IDs.
