# ADR 0029: Verified audit-key rotation preconditions

- Status: accepted
- Date: 2026-09-02

## Context

ADR 0028 makes the original audit-attestation root fingerprint an independently supplied
trust anchor. The keyring already authenticates each dual-signed transition from that root,
but an operator had no single read-only command that proved the complete stored chain was
linear, ended at the configured active key, and contained no orphaned public keys. A rotation
also accepted whichever active key existed after acquiring its serialization lock. Two
independently approved commands could therefore produce two sequential rotations even when
the second operator had approved only the original state.

Changing the externally pinned root is not an ordinary key rotation. It establishes a new
trust domain and remains an explicit migration requiring separate policy and custody.

## Decision

1. `smart-factory-verify-audit-keyring` validates the independently supplied root, every
   archived public-key identity and transition signature, the expected chain identity, a
   single root-to-tip path, the active terminal key, canonical transition filenames, and the
   absence of unreferenced archived keys.
2. Successful verification emits the ordered key and transition identities plus a
   deterministic SHA-256 snapshot of the exact public evidence. It requires no database,
   network, or private-key access and supports machine-readable JSON.
3. Every rotation requires `AUDIT_ATTESTATION_EXPECTED_ACTIVE_KEY_ID`. The service compares
   it with the verified active key while holding the exclusive rotation lock and aborts
   before writing a `started` audit event if they differ.
4. Operators must obtain the expected active key from a reviewed verification result and
   bind that value to the change approval. Reusing a stale approval fails closed.
5. Local Compose demonstrates the same sequence through a read-only verifier service. CI
   proves the root remains unchanged, the active key advances, and exactly one transition is
   added.

## Consequences

- Concurrent or intervening rotations cannot silently consume a stale approval.
- Orphan keys, disconnected histories, non-terminal active markers, malformed filenames,
  forks, cycles, wrong-chain transitions, and invalid signatures are operationally visible.
- The snapshot digest can be retained with a ticket or independent monitoring record, but it
  is not itself a new trust root or a substitute for authenticated storage.
- A failed precondition deliberately creates no operator-audit event because no privileged
  state change has started. The invoking control plane must record the rejected request.
- Root migration, private-key custody, authorization, approval quorum, and immutable off-site
  retention remain deployment responsibilities.

## Rejected alternatives

- Rotate whichever key is current after waiting for the lock: this turns one stale approval
  into authorization for an unreviewed second transition.
- Read only `active-key-id`: this does not authenticate the key through the pinned root or
  detect malformed surrounding evidence.
- Automatically replace the external root pin: the writable system must never be able to
  redefine its own trust anchor.
