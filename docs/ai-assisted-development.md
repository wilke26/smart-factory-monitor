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
