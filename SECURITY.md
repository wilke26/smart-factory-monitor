# Security Policy

## Reporting a Vulnerability

Please report security vulnerabilities using GitHub's private
vulnerability reporting: open the **Security and quality** tab of this
repository, select **Advisories** under **Reporting**, and choose
**Report a vulnerability**. This creates a private advisory visible
only to the maintainer and avoids public disclosure before a fix is
available.

Please do not open a public issue for security-sensitive reports.

## Scope

This project is a demonstration and portfolio pipeline. The local
Docker Compose environment is explicitly a development setup, not a
production deployment (see README). Several production-hardening
gaps are already known and intentionally documented as future work
in the README (for example, authenticated `AUDIT_ACTOR` derivation)
— you do not need to report those specifically.

Genuine vulnerabilities in the implementation are very welcome,
including but not limited to:

- MQTT/database input handling
- ML artifact signature verification and deserialization
- The operator audit trail and key-rotation logic
- The release build, signing, and verification chain

## Supported Versions

Only the latest released version receives security fixes.

## Response

This is an individually maintained project. There is no formal SLA,
but reports are taken seriously and acknowledged as soon as
possible.
