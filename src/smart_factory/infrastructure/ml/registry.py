"""Machine-aware dispatch for trusted Isolation Forest artifacts."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from pydantic import ValidationError

from smart_factory.application.ports.model_registry import ModelPromotionCandidate
from smart_factory.domain.anomaly import AnomalyFinding
from smart_factory.domain.model_registry import ModelRegistryEntry, ModelRegistryManifest
from smart_factory.domain.telemetry import TelemetryReading
from smart_factory.infrastructure.ml.artifact_signing import (
    ArtifactSigningError,
    ArtifactVerifier,
    artifact_bytes_sha256,
    artifact_signature_path,
)
from smart_factory.infrastructure.ml.isolation_forest import (
    IsolationForestAnomalyDetector,
    MlArtifactError,
)


class MachineModelRegistry:
    """Load one artifact per machine and route inference without cross-scoring."""

    def __init__(
        self,
        detectors: dict[str, IsolationForestAnomalyDetector],
        *,
        on_resolution: Callable[[bool], None] | None = None,
    ) -> None:
        self._detectors = dict(detectors)
        self._on_resolution = on_resolution

    @classmethod
    def load(
        cls,
        directory: Path,
        *,
        expected_machine_ids: tuple[str, ...] | None = None,
        public_key_path: Path,
        on_resolution: Callable[[bool], None] | None = None,
    ) -> MachineModelRegistry:
        manifest = _load_manifest(directory / "active.json")
        entries_by_machine = {entry.machine_id: entry for entry in manifest.entries}
        machine_ids = expected_machine_ids or tuple(sorted(entries_by_machine))
        missing = [machine_id for machine_id in machine_ids if machine_id not in entries_by_machine]
        if missing:
            raise MlArtifactError(
                f"missing promoted ML artifact for configured machine {missing[0]}"
            )
        try:
            verifier = ArtifactVerifier.from_public_key_file(public_key_path)
        except ArtifactSigningError as error:
            raise MlArtifactError(
                f"could not load ML artifact verification key {public_key_path}: {error}"
            ) from error
        detectors: dict[str, IsolationForestAnomalyDetector] = {}
        for machine_id in machine_ids:
            entry = entries_by_machine[machine_id]
            path = _version_artifact_path(directory, entry)
            if not path.is_file():
                raise MlArtifactError(
                    f"missing promoted ML artifact for configured machine {machine_id}"
                )
            detector = IsolationForestAnomalyDetector.load(
                path,
                expected_machine_id=machine_id,
                verifier=verifier,
                expected_artifact_sha256=entry.artifact_sha256,
            )
            if detector.artifact.model_id != entry.model_id:
                raise MlArtifactError(
                    f"promoted ML artifact model identity mismatch for {machine_id}"
                )
            detectors[machine_id] = detector
        return cls(detectors, on_resolution=on_resolution)

    @property
    def machine_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._detectors))

    def evaluate(self, reading: TelemetryReading) -> tuple[AnomalyFinding, ...]:
        detector = self._detectors.get(reading.machine_id)
        if detector is None:
            if self._on_resolution is not None:
                self._on_resolution(False)
            return ()
        findings = detector.evaluate(reading)
        if self._on_resolution is not None:
            self._on_resolution(True)
        return findings


class FilesystemModelRegistryPublisher:
    """Publish immutable versions, then atomically replace the active manifest."""

    def __init__(self, directory: Path, verifier: ArtifactVerifier) -> None:
        self._directory = directory
        self._verifier = verifier

    def publish(
        self,
        candidates: Sequence[ModelPromotionCandidate],
    ) -> ModelRegistryManifest:
        if not candidates:
            raise MlArtifactError("at least one model candidate is required for promotion")
        entries = tuple(
            sorted(
                (self._publish_candidate(candidate) for candidate in candidates),
                key=lambda entry: entry.machine_id,
            )
        )
        current = self._load_current_optional()
        manifest = ModelRegistryManifest(
            previous_generation_id=current.generation_id if current else None,
            entries=entries,
        )
        self._activate(manifest)
        return manifest

    def rollback(self, generation_id: UUID) -> ModelRegistryManifest:
        target = _load_manifest(self._manifest_path(generation_id))
        current = _load_manifest(self._directory / "active.json")
        for entry in target.entries:
            self._verify_version(entry)
        manifest = ModelRegistryManifest(
            previous_generation_id=current.generation_id,
            source_generation_id=target.generation_id,
            entries=target.entries,
        )
        self._activate(manifest)
        return manifest

    def _publish_candidate(self, candidate: ModelPromotionCandidate) -> ModelRegistryEntry:
        signature_path = artifact_signature_path(candidate.artifact_path)
        try:
            payload = candidate.artifact_path.read_bytes()
            signature = signature_path.read_bytes()
            if artifact_bytes_sha256(payload) != candidate.artifact_sha256:
                raise ArtifactSigningError("candidate digest changed after approval")
            self._verifier.verify(payload, signature)
        except (OSError, ArtifactSigningError) as error:
            raise MlArtifactError(
                f"candidate signature is invalid for {candidate.machine_id}"
            ) from error
        entry = ModelRegistryEntry(
            machine_id=candidate.machine_id,
            model_id=candidate.model_id,
            artifact_sha256=candidate.artifact_sha256,
        )
        artifact_path = _version_artifact_path(self._directory, entry)
        _write_once(artifact_path, payload)
        _write_once(artifact_signature_path(artifact_path), signature)
        return entry

    def _verify_version(self, entry: ModelRegistryEntry) -> None:
        artifact_path = _version_artifact_path(self._directory, entry)
        try:
            payload = artifact_path.read_bytes()
            signature = artifact_signature_path(artifact_path).read_bytes()
        except OSError as error:
            raise MlArtifactError(
                f"rollback model files are missing for {entry.machine_id}"
            ) from error
        if artifact_bytes_sha256(payload) != entry.artifact_sha256:
            raise MlArtifactError(f"rollback model digest mismatch for {entry.machine_id}")
        try:
            self._verifier.verify(payload, signature)
        except ArtifactSigningError as error:
            raise MlArtifactError(
                f"rollback model signature is invalid for {entry.machine_id}"
            ) from error

    def _activate(self, manifest: ModelRegistryManifest) -> None:
        payload = manifest.model_dump_json(indent=2).encode() + b"\n"
        _write_once(self._manifest_path(manifest.generation_id), payload)
        _write_atomically(self._directory / "active.json", payload)

    def _manifest_path(self, generation_id: UUID) -> Path:
        return self._directory / "manifests" / f"{generation_id}.json"

    def _load_current_optional(self) -> ModelRegistryManifest | None:
        active_path = self._directory / "active.json"
        return _load_manifest(active_path) if active_path.is_file() else None


def _version_artifact_path(directory: Path, entry: ModelRegistryEntry) -> Path:
    return directory / "versions" / entry.machine_id / f"{entry.artifact_sha256}.joblib"


def _load_manifest(path: Path) -> ModelRegistryManifest:
    try:
        return ModelRegistryManifest.model_validate_json(path.read_bytes())
    except OSError as error:
        raise MlArtifactError(f"model registry manifest is missing: {path}") from error
    except ValidationError as error:
        raise MlArtifactError(f"model registry manifest is invalid: {path}") from error


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise MlArtifactError(
                f"immutable model registry path already contains other data: {path}"
            )
        return
    try:
        with path.open("xb") as file:
            file.write(payload)
    except FileExistsError as error:
        if path.read_bytes() != payload:
            raise MlArtifactError(
                f"immutable model registry path already contains other data: {path}"
            ) from error


def _write_atomically(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}-", delete=False) as file:
        temporary_path = Path(file.name)
        file.write(payload)
    try:
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
