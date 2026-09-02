# ADR 0028: Externally pinned audit trust root

- Status: accepted
- Date: 2026-09-02

## Context

ADR 0019 defines a continuous audit-attestation trust chain whose first public-key
fingerprint is the root. The original implementation stored that fingerprint in a file
next to the archived public keys, transitions, and active-key marker. Individual key and
transition modification was detectable, but an actor able to replace that entire writable
boundary could install a self-consistent unrelated root and key history.

Production guidance said to mount the root file independently, yet the application
interface could not distinguish an independently controlled mount from a co-located file.
The intended trust separation was therefore an operational convention rather than a
fail-closed application invariant.

## Decision

1. The normal checkpoint-verification and key-rotation paths require
   `AUDIT_ATTESTATION_TRUSTED_ROOT_KEY_ID`, a 64-character lowercase SHA-256 fingerprint
   supplied independently from the keyring directory.
2. `AuditAttestationKeyring` accepts the fingerprint value, not a path it can resolve
   inside its own storage boundary. It validates the archived root public key against that
   value before trusting the root or traversing any transition.
3. A missing, malformed, or mismatched production root fails closed. Replacing a complete
   keyring cannot change the separately configured root identity.
4. Initial key generation reports the new fingerprint for an operator to review and pin.
   An existing key cannot be reinitialized without the external pin.
5. Local Compose may retain its convenient co-located marker only by explicitly setting
   `AUDIT_ATTESTATION_ALLOW_COLOCATED_ROOT=true`. This compatibility mode is not a
   production trust boundary.

## Consequences

- Control of the writable keyring alone is insufficient to establish a new trust domain.
- The production secret store or immutable deployment configuration becomes part of the
  audit-verification trust base and needs separate access control, backup, and change
  review.
- First deployment requires a bootstrap ceremony: generate the root key, capture and
  review its fingerprint, store the pin independently, and only then enable verification
  and rotation.
- A lost external pin makes retained evidence unavailable until the exact value is
  recovered. The pin must therefore be backed up for the full evidence lifetime.
- The development fallback remains intentionally weaker and emits no claim of independent
  root anchoring.

## Rejected alternatives

- Keep only the existing documentation requirement: this leaves the security boundary
  unenforceable and easy to deploy incorrectly.
- Copy the root marker to another path under the same writable volume: a whole-volume
  replacement still controls both the claim and the evidence.
- Trust the currently active key: this discards historical continuity and permits silent
  root replacement.
- Fetch the root over the network during each verification: this adds availability and
  remote-compromise dependencies to an otherwise offline verification path.
