"""Cryptographically continuous trust store for audit-attestation keys."""

from __future__ import annotations

import json
import os
import re
from base64 import b64decode, b64encode
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC
from fcntl import LOCK_EX, LOCK_UN, flock
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import get_ident
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from smart_factory.domain.audit_keyring import (
    AuditKeyringVerification,
    AuditKeyRotationResult,
    AuditKeyTransition,
    SignedAuditKeyTransition,
)
from smart_factory.infrastructure.audit.checkpoint import (
    AuditCheckpointError,
    public_key_id,
)
from smart_factory.infrastructure.ml.artifact_signing import (
    ArtifactSigner,
    ArtifactSigningError,
    ArtifactVerifier,
)

KEY_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_TRANSITIONS = 1_000
MAX_TRANSITION_BYTES = 65_536


def canonical_transition_payload(transition: AuditKeyTransition) -> bytes:
    document = {
        "chain_id": transition.chain_id,
        "created_at": transition.created_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "new_key_id": transition.new_key_id,
        "previous_key_id": transition.previous_key_id,
        "schema_version": transition.schema_version,
        "transition_id": str(transition.transition_id),
    }
    return json.dumps(document, separators=(",", ":"), sort_keys=True).encode()


class AuditAttestationKeyring:
    def __init__(self, directory: Path, trusted_root_key_id: str) -> None:
        if not KEY_ID_PATTERN.fullmatch(trusted_root_key_id):
            raise AuditCheckpointError("trusted root audit key ID is invalid")
        self._directory = directory
        self._keys_directory = directory / "keys"
        self._transitions_directory = directory / "transitions"
        self._active_key_id_path = directory / "active-key-id"
        self._rotation_lock_path = directory / ".rotation.lock"
        self._trusted_root_key_id = trusted_root_key_id

    def initialize(
        self,
        public_key_path: Path,
        *,
        expected_chain_id: str | None = None,
    ) -> str:
        key_id = public_key_id(public_key_path)
        if (
            key_id != self._trusted_root_key_id
            and not self.key_path(self._trusted_root_key_id).is_file()
        ):
            raise AuditCheckpointError("initial audit key does not match trusted root")
        if key_id != self._trusted_root_key_id and expected_chain_id is None:
            raise AuditCheckpointError("audit chain ID is required to initialize a rotated key")
        self._keys_directory.mkdir(parents=True, exist_ok=True)
        self._transitions_directory.mkdir(parents=True, exist_ok=True)
        self._write_once(self.key_path(key_id), public_key_path.read_bytes(), 0o644)
        if key_id != self._trusted_root_key_id:
            assert expected_chain_id is not None
            self.resolve_trusted_key(key_id, expected_chain_id=expected_chain_id)
        self._replace(self._active_key_id_path, f"{key_id}\n".encode(), 0o644)
        return key_id

    def active_key_id(self) -> str:
        return self._read_key_id(self._active_key_id_path, "active audit key ID")

    def trusted_root_key_id(self) -> str:
        return self._trusted_root_key_id

    @classmethod
    def initialize_development_root_marker(cls, path: Path, key_id: str) -> str:
        """Create or read the explicitly weaker co-located development root."""
        if not KEY_ID_PATTERN.fullmatch(key_id):
            raise AuditCheckpointError("trusted root audit key ID is invalid")
        if path.exists():
            return cls._read_key_id(path, "trusted root audit key ID")
        cls._write_once(path, f"{key_id}\n".encode(), 0o644)
        return cls._read_key_id(path, "trusted root audit key ID")

    @contextmanager
    def exclusive_rotation(self) -> Iterator[None]:
        self._directory.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self._rotation_lock_path,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC,
            0o600,
        )
        try:
            flock(descriptor, LOCK_EX)
            try:
                yield
            finally:
                flock(descriptor, LOCK_UN)
        finally:
            os.close(descriptor)

    def key_path(self, key_id: str) -> Path:
        if not KEY_ID_PATTERN.fullmatch(key_id):
            raise AuditCheckpointError("invalid audit attestation key ID")
        return self._keys_directory / f"{key_id}.pem"

    def resolve_trusted_key(self, target_key_id: str, *, expected_chain_id: str) -> Path:
        root_key_id = self.trusted_root_key_id()
        self._validate_key_file(root_key_id)
        if target_key_id == root_key_id:
            return self.key_path(root_key_id)

        transitions = self._load_verified_transitions(expected_chain_id=expected_chain_id)
        current = root_key_id
        visited = {current}
        while current in transitions:
            current = transitions[current].transition.new_key_id
            if current in visited:
                raise AuditCheckpointError("audit attestation keyring contains a cycle")
            visited.add(current)
            if current == target_key_id:
                return self.key_path(current)
        raise AuditCheckpointError("checkpoint key is not trusted by the configured root")

    def verify_integrity(self, *, expected_chain_id: str) -> AuditKeyringVerification:
        """Verify and summarize the complete, linear root-to-active trust chain."""
        root_key_id = self.trusted_root_key_id()
        self._validate_key_file(root_key_id)
        active_key_id = self.active_key_id()
        transitions = self._load_verified_transitions(expected_chain_id=expected_chain_id)

        current = root_key_id
        key_ids = [current]
        transition_ids: list[UUID] = []
        consumed_previous_ids: set[str] = set()
        while current in transitions:
            envelope = transitions[current]
            consumed_previous_ids.add(current)
            transition_ids.append(envelope.transition.transition_id)
            current = envelope.transition.new_key_id
            if current in key_ids:
                raise AuditCheckpointError("audit attestation keyring contains a cycle")
            key_ids.append(current)

        if current != active_key_id:
            raise AuditCheckpointError("active audit key is not the terminal trusted key")
        if len(consumed_previous_ids) != len(transitions):
            raise AuditCheckpointError("audit attestation keyring contains a disconnected chain")

        archived_key_ids: set[str] = set()
        for path in sorted(self._keys_directory.iterdir()):
            key_id = path.stem
            if (
                path.is_symlink()
                or not path.is_file()
                or path.suffix != ".pem"
                or not KEY_ID_PATTERN.fullmatch(key_id)
            ):
                raise AuditCheckpointError("audit keyring contains an invalid key entry")
            self._validate_key_file(key_id)
            archived_key_ids.add(key_id)
        if archived_key_ids != set(key_ids):
            raise AuditCheckpointError("audit keyring contains unexpected archived keys")

        snapshot_records = [
            {
                "name": f"keys/{key_id}.pem",
                "sha256": sha256(self.key_path(key_id).read_bytes()).hexdigest(),
            }
            for key_id in key_ids
        ]
        for previous_key_id in consumed_previous_ids:
            transition = transitions[previous_key_id].transition
            path = self._transitions_directory / (
                f"{transition.previous_key_id}-{transition.new_key_id}.json"
            )
            snapshot_records.append(
                {
                    "name": f"transitions/{path.name}",
                    "sha256": sha256(path.read_bytes()).hexdigest(),
                }
            )
        snapshot = {
            "active_key_id": active_key_id,
            "chain_id": expected_chain_id,
            "records": sorted(snapshot_records, key=lambda record: record["name"]),
            "schema_version": 1,
            "trusted_root_key_id": root_key_id,
        }
        snapshot_sha256 = sha256(
            json.dumps(snapshot, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        return AuditKeyringVerification(
            chain_id=expected_chain_id,
            trusted_root_key_id=root_key_id,
            active_key_id=active_key_id,
            key_ids=tuple(key_ids),
            transition_ids=tuple(transition_ids),
            snapshot_sha256=snapshot_sha256,
        )

    def publish_transition(
        self,
        envelope: SignedAuditKeyTransition,
        *,
        new_public_key: bytes,
    ) -> None:
        transition = envelope.transition
        if public_key_id_from_bytes(new_public_key) != transition.new_key_id:
            raise AuditCheckpointError("new audit key does not match transition identity")
        if transition.previous_key_id != self.active_key_id():
            raise AuditCheckpointError("audit key transition does not start at active key")
        self._keys_directory.mkdir(parents=True, exist_ok=True)
        self._transitions_directory.mkdir(parents=True, exist_ok=True)
        self._write_once(self.key_path(transition.new_key_id), new_public_key, 0o644)
        self._verify_transition(envelope, expected_chain_id=transition.chain_id)
        transition_path = self._transitions_directory / (
            f"{transition.previous_key_id}-{transition.new_key_id}.json"
        )
        self._write_once(
            transition_path,
            (envelope.model_dump_json(indent=2) + "\n").encode(),
            0o644,
        )

    def activate(self, key_id: str) -> None:
        self._validate_key_file(key_id)
        self._replace(self._active_key_id_path, f"{key_id}\n".encode(), 0o644)

    def _load_verified_transitions(
        self, *, expected_chain_id: str
    ) -> dict[str, SignedAuditKeyTransition]:
        paths = sorted(self._transitions_directory.iterdir())
        if len(paths) > MAX_TRANSITIONS:
            raise AuditCheckpointError("audit attestation keyring exceeds transition limit")
        transitions: dict[str, SignedAuditKeyTransition] = {}
        for path in paths:
            try:
                if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                    raise AuditCheckpointError("audit keyring contains an invalid transition entry")
                if path.stat().st_size > MAX_TRANSITION_BYTES:
                    raise AuditCheckpointError("audit key transition exceeds size limit")
                envelope = SignedAuditKeyTransition.model_validate_json(path.read_bytes())
            except AuditCheckpointError:
                raise
            except (OSError, ValidationError) as error:
                raise AuditCheckpointError("could not load audit key transition") from error
            previous = envelope.transition.previous_key_id
            expected_name = f"{previous}-{envelope.transition.new_key_id}.json"
            if path.name != expected_name:
                raise AuditCheckpointError("audit key transition filename is invalid")
            if previous in transitions:
                raise AuditCheckpointError("audit attestation keyring contains a fork")
            self._verify_transition(envelope, expected_chain_id=expected_chain_id)
            transitions[previous] = envelope
        return transitions

    def _verify_transition(
        self,
        envelope: SignedAuditKeyTransition,
        *,
        expected_chain_id: str,
    ) -> None:
        transition = envelope.transition
        if transition.chain_id != expected_chain_id:
            raise AuditCheckpointError("audit key transition belongs to an unexpected chain")
        previous_path = self._validate_key_file(transition.previous_key_id)
        new_path = self._validate_key_file(transition.new_key_id)
        payload = canonical_transition_payload(transition)
        try:
            ArtifactVerifier.from_public_key_file(previous_path).verify(
                payload, b64decode(envelope.previous_signature, validate=True)
            )
            ArtifactVerifier.from_public_key_file(new_path).verify(
                payload, b64decode(envelope.new_signature, validate=True)
            )
        except ArtifactSigningError as error:
            raise AuditCheckpointError("audit key transition signature is invalid") from error

    def _validate_key_file(self, key_id: str) -> Path:
        path = self.key_path(key_id)
        if public_key_id(path) != key_id:
            raise AuditCheckpointError("audit keyring public key identity is invalid")
        return path

    @staticmethod
    def _read_key_id(path: Path, label: str) -> str:
        try:
            value = path.read_text().strip()
        except OSError as error:
            raise AuditCheckpointError(f"could not load {label}") from error
        if not KEY_ID_PATTERN.fullmatch(value):
            raise AuditCheckpointError(f"{label} is invalid")
        return value

    @staticmethod
    def _write_once(path: Path, payload: bytes, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        except FileExistsError as error:
            if path.read_bytes() != payload:
                raise AuditCheckpointError(
                    "immutable audit keyring evidence already differs"
                ) from error
            return
        with os.fdopen(descriptor, "wb") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())

    @staticmethod
    def _replace(path: Path, payload: bytes, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}-", delete=False) as file:
            temporary_path = Path(file.name)
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        try:
            os.chmod(temporary_path, mode)
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)


class FilesystemAuditAttestationKeyRotator:
    def __init__(
        self,
        *,
        chain_id: str,
        private_key_path: Path,
        public_key_path: Path,
        keyring: AuditAttestationKeyring,
    ) -> None:
        self._chain_id = chain_id
        self._private_key_path = private_key_path
        self._public_key_path = public_key_path
        self._keyring = keyring
        self._rotation_owner: int | None = None

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        with self._keyring.exclusive_rotation():
            self._rotation_owner = get_ident()
            try:
                yield
            finally:
                self._rotation_owner = None

    def current_key_id(self) -> str:
        verification = self._keyring.verify_integrity(expected_chain_id=self._chain_id)
        active = verification.active_key_id
        if public_key_id(self._public_key_path) != active:
            raise AuditCheckpointError("active audit key does not match public key")
        trusted_key_path = self._keyring.resolve_trusted_key(
            active,
            expected_chain_id=self._chain_id,
        )
        if trusted_key_path.read_bytes() != self._public_key_path.read_bytes():
            raise AuditCheckpointError("active audit key does not match trusted keyring")
        return active

    def rotate(self) -> AuditKeyRotationResult:
        if self._rotation_owner != get_ident():
            raise AuditCheckpointError("audit key rotation requires exclusive lock")
        previous_key_id = self.current_key_id()
        previous_signer = ArtifactSigner.from_private_key_file(self._private_key_path)
        replacement = Ed25519PrivateKey.generate()
        replacement_signer = ArtifactSigner(replacement)
        private_bytes = replacement.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_bytes = replacement.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        new_key_id = public_key_id_from_bytes(public_bytes)
        transition = AuditKeyTransition(
            chain_id=self._chain_id,
            previous_key_id=previous_key_id,
            new_key_id=new_key_id,
        )
        payload = canonical_transition_payload(transition)
        envelope = SignedAuditKeyTransition(
            transition=transition,
            previous_signature=b64encode(previous_signer.sign(payload)).decode("ascii"),
            new_signature=b64encode(replacement_signer.sign(payload)).decode("ascii"),
        )
        pending_private_key_path = self._private_key_path.parent / f".pending-{new_key_id}.pem"
        self._keyring._write_once(pending_private_key_path, private_bytes, 0o600)
        self._keyring.publish_transition(envelope, new_public_key=public_bytes)
        self._keyring._replace(self._public_key_path, public_bytes, 0o644)
        self._keyring.activate(new_key_id)
        os.replace(pending_private_key_path, self._private_key_path)
        return AuditKeyRotationResult(
            transition_id=transition.transition_id,
            previous_key_id=previous_key_id,
            new_key_id=new_key_id,
        )


def public_key_id_from_bytes(payload: bytes) -> str:
    with NamedTemporaryFile() as file:
        file.write(payload)
        file.flush()
        return public_key_id(Path(file.name))
