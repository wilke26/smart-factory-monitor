#!/usr/bin/env python3
"""Compatibility entry point for release-evidence encryption and recovery."""

from smart_factory.release_evidence_crypto import (
    decrypt_release_evidence,
    encrypt_release_evidence,
    main,
    public_key_fingerprint,
    public_key_fingerprint_from_path,
)

__all__ = [
    "decrypt_release_evidence",
    "encrypt_release_evidence",
    "main",
    "public_key_fingerprint",
    "public_key_fingerprint_from_path",
]


if __name__ == "__main__":
    main()
