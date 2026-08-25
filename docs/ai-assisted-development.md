# AI-assisted development record

This repository may be developed with AI-assisted tools. Their output is treated as an
untrusted implementation proposal rather than an authority.

Human responsibilities remain:

- translate the production use case into acceptance criteria;
- decide scope and architecture;
- review generated code and dependency choices;
- validate behavior with example-based and property-based tests;
- inspect container and CI configuration;
- reject unnecessary patterns or premature features.

For v0.4, automated checks additionally cover every rule, exact boundary behavior,
simultaneous findings, threshold validation, atomic parameterized persistence, duplicate
handling, and application failure semantics. Release acceptance verifies normal input
creates no finding, anomalous input creates the expected evidence, duplicate delivery
does not duplicate findings, and an existing v0.3 volume is migrated without data loss.

For v0.5, checks cover detector composition, minimum training data, machine isolation,
artifact compatibility, deterministic training, normal/outlier inference, bounded SQL
history, and explicit opt-in loading. Container acceptance trains an artifact from a
known database history and reloads it through the consumer image.

For v0.6, external review claims were verified against implementation and upstream
documentation before adoption. Tests cover conflicting natural identities, publish ACK
timeouts, configured model identity, persistent bounded MQTT connect properties,
monitoring state and output, and the complete Compose ingestion smoke path. CI also runs a
dependency audit. Generated review reports remain ignored build-time material.

For v0.7, tests additionally cover multi-machine configuration, exact registry activation,
missing-model fail-fast behavior, machine-aware dispatch, batch training targets, and
bounded ML coverage metrics.

For v0.8, tests cover credential/TLS configuration invariants and verify that certificate
validation is never disabled. CI renders both Kubernetes bases, while deployment acceptance
checks non-root/read-only container policy, secret references, probes, Azure Files storage,
and the existing local Compose path.

For v0.8.1, an external review claim about readiness was traced through the runtime failure
path. Regression tests verify that failed database operations make the consumer unready,
successful operations restore readiness, and permanent identity conflicts do not create a
false infrastructure outage.

For v0.9, tests prove that model bytes are authenticated before joblib is called, tampered
or missing signatures fail closed, key pairs are validated, and signing remains outside
the consumer. Compose acceptance checks both an allowed telemetry path and a denied
cross-machine publish. CI renders default-deny network policy, pins the image scanner by
commit, and rejects high or critical vulnerabilities with an available fix in the built
consumer image. Base container and third-party Compose image tags are resolved to
immutable manifest digests.

For v0.10, tests cover artifact-bound reference distributions, stable and shifted feature
windows, anomaly-rate and minimum-sample gates, strict post-training database selection,
multi-machine failure aggregation, and key requirements. Compose acceptance evaluates
fresh post-training data for both signed machine models before enabling online inference.

For v0.11, tests cover severity routing, atomic and deduplicated outbox insertion, leased
claims, lease-loss protection, capped retry scheduling, credential-safe logging, strict
HTTPS configuration, stable idempotency headers, and a real local webhook request. CI
renders the hardened dispatcher deployment and verifies that an anomalous MQTT reading
creates a durable outbox event.

For v0.11.1, review findings were traced to their reachable runtime paths before changes
were accepted. Tests now cover lease loss during both delivery completion and retry
rescheduling, continued processing of later batch entries, and actual redirect rejection.
The documented development-only HTTP path remains intentional and unchanged.
