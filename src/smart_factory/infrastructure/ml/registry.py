"""Machine-aware dispatch for trusted Isolation Forest artifacts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from smart_factory.domain.anomaly import AnomalyFinding
from smart_factory.domain.telemetry import TelemetryReading
from smart_factory.infrastructure.ml.artifact_signing import (
    ArtifactSigningError,
    ArtifactVerifier,
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
        paths = (
            [directory / f"{machine_id}.joblib" for machine_id in expected_machine_ids]
            if expected_machine_ids is not None
            else sorted(directory.glob("*.joblib"))
        )
        if not paths:
            raise MlArtifactError(f"no ML artifacts found in model directory {directory}")
        missing = [path.stem for path in paths if not path.is_file()]
        if missing:
            raise MlArtifactError(f"missing ML artifact for configured machine {missing[0]}")
        try:
            verifier = ArtifactVerifier.from_public_key_file(public_key_path)
        except ArtifactSigningError as error:
            raise MlArtifactError(
                f"could not load ML artifact verification key {public_key_path}: {error}"
            ) from error
        detectors = {
            path.stem: IsolationForestAnomalyDetector.load(
                path,
                expected_machine_id=path.stem,
                verifier=verifier,
            )
            for path in paths
        }
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
