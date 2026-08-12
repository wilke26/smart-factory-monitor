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

For v0.3, automated checks cover the Pydantic boundary, simulator, MQTT acceptance and
rejection, application ports, parameterized/idempotent persistence, configuration,
serialization round trips, linting, formatting, static types and container builds. The
release acceptance test also verifies a real MQTT message reaches the TimescaleDB
hypertable and an invalid message does not create a row.
