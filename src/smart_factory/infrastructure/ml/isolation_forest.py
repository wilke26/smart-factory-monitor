"""Isolation Forest training and inference with a versioned local artifact."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Final, cast

import joblib
import sklearn
from sklearn.ensemble import IsolationForest

from smart_factory.domain.anomaly import AnomalyFinding, AnomalySeverity
from smart_factory.domain.telemetry import TelemetryReading

ARTIFACT_FORMAT_VERSION: Final = 1
FEATURE_NAMES: Final = (
    "temperature_c",
    "vibration_mm_s",
    "power_kw",
    "production_rate",
)


class MlArtifactError(RuntimeError):
    """The configured model artifact cannot be safely used for inference."""


def _features(reading: TelemetryReading) -> list[float]:
    return [
        reading.temperature_c,
        reading.vibration_mm_s,
        reading.power_kw,
        float(reading.production_rate),
    ]


@dataclass(frozen=True, slots=True)
class IsolationForestArtifact:
    """Validated metadata plus the fitted estimator."""

    estimator: IsolationForest
    model_id: str
    machine_id: str
    trained_at: str
    training_samples: int


class IsolationForestTrainer:
    """Fit a reproducible multivariate model outside the ingestion process."""

    def __init__(
        self,
        *,
        contamination: float = 0.05,
        minimum_samples: int = 100,
        random_state: int = 42,
    ) -> None:
        self._contamination = contamination
        self._minimum_samples = minimum_samples
        self._random_state = random_state

    def train(self, readings: list[TelemetryReading], output_path: Path) -> IsolationForestArtifact:
        if len(readings) < self._minimum_samples:
            raise ValueError(
                f"at least {self._minimum_samples} readings are required; got {len(readings)}"
            )
        machine_ids = {reading.machine_id for reading in readings}
        if len(machine_ids) != 1:
            raise ValueError("training readings must belong to exactly one machine")
        estimator = IsolationForest(
            contamination=self._contamination,
            n_estimators=100,
            random_state=self._random_state,
            n_jobs=1,
        )
        estimator.fit([_features(reading) for reading in readings])
        trained_at = datetime.now(UTC).isoformat()
        model_id = f"isolation-forest-{trained_at}"
        artifact = IsolationForestArtifact(
            estimator, model_id, machine_ids.pop(), trained_at, len(readings)
        )
        self._write_artifact(artifact, output_path)
        return artifact

    @staticmethod
    def _write_artifact(artifact: IsolationForestArtifact, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": ARTIFACT_FORMAT_VERSION,
            "feature_names": FEATURE_NAMES,
            "sklearn_version": sklearn.__version__,
            "model_id": artifact.model_id,
            "machine_id": artifact.machine_id,
            "trained_at": artifact.trained_at,
            "training_samples": artifact.training_samples,
            "estimator": artifact.estimator,
        }
        with NamedTemporaryFile(dir=output_path.parent, prefix=".model-", delete=False) as file:
            temporary_path = Path(file.name)
        try:
            joblib.dump(payload, temporary_path)
            os.replace(temporary_path, output_path)
        finally:
            temporary_path.unlink(missing_ok=True)


class IsolationForestAnomalyDetector:
    """Run inference from a trusted, versioned Isolation Forest artifact."""

    def __init__(self, artifact: IsolationForestArtifact) -> None:
        self._artifact = artifact

    @classmethod
    def load(cls, path: Path) -> IsolationForestAnomalyDetector:
        # joblib uses pickle semantics: only load artifacts produced by this project
        # from a trusted model volume.
        try:
            loaded = joblib.load(path)
        except Exception as error:
            raise MlArtifactError(f"could not load ML artifact {path}: {error}") from error
        try:
            return cls(cls._validate_artifact(cast(Any, loaded)))
        except MlArtifactError:
            raise
        except Exception as error:
            raise MlArtifactError(f"invalid ML artifact {path}: {error}") from error

    @staticmethod
    def _validate_artifact(loaded: Any) -> IsolationForestArtifact:
        if not isinstance(loaded, dict):
            raise MlArtifactError("ML artifact payload must be a dictionary")
        payload = cast(dict[str, Any], loaded)
        if payload.get("format_version") != ARTIFACT_FORMAT_VERSION:
            raise MlArtifactError("unsupported ML artifact format")
        if tuple(payload.get("feature_names", ())) != FEATURE_NAMES:
            raise MlArtifactError("ML artifact feature contract does not match telemetry")
        if payload.get("sklearn_version") != sklearn.__version__:
            raise MlArtifactError("ML artifact scikit-learn version does not match runtime")
        estimator = payload.get("estimator")
        if not isinstance(estimator, IsolationForest):
            raise MlArtifactError("ML artifact does not contain an IsolationForest")
        return IsolationForestArtifact(
            estimator=estimator,
            model_id=str(payload["model_id"]),
            machine_id=str(payload["machine_id"]),
            trained_at=str(payload["trained_at"]),
            training_samples=int(payload["training_samples"]),
        )

    def evaluate(self, reading: TelemetryReading) -> tuple[AnomalyFinding, ...]:
        if reading.machine_id != self._artifact.machine_id:
            return ()
        score = float(self._artifact.estimator.decision_function([_features(reading)])[0])
        if score >= 0:
            return ()
        return (
            AnomalyFinding(
                rule_id="ml-isolation-forest",
                severity=AnomalySeverity.MEDIUM,
                metric="isolation_forest_score",
                observed_value=score,
                threshold=0.0,
                comparison="<",
                message=(
                    f"multivariate score {score:.6f} is below 0 for model {self._artifact.model_id}"
                ),
            ),
        )
