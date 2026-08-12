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

For v0.1, automated checks cover the Pydantic boundary, simulator ranges, deterministic
seeding, serialization round trips, linting, formatting, static types and the container
build. A real-broker smoke test is still a documented manual acceptance test.
