"""Isolation Forest training and inference with a versioned local artifact."""

from __future__ import annotations

import os
from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from itertools import pairwise
from math import isclose, isfinite, log
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Final, cast

import joblib
import sklearn
from sklearn.ensemble import IsolationForest

from smart_factory.domain.anomaly import AnomalyFinding, AnomalySeverity
from smart_factory.domain.telemetry import TelemetryReading
from smart_factory.infrastructure.ml.artifact_signing import (
    ArtifactSigner,
    ArtifactSigningError,
    ArtifactVerifier,
    artifact_signature_path,
)

ARTIFACT_FORMAT_VERSION: Final = 2
FEATURE_NAMES: Final = (
    "temperature_c",
    "vibration_mm_s",
    "power_kw",
    "production_rate",
)


class MlArtifactError(RuntimeError):
    """The configured model artifact cannot be safely used for inference."""


class ModelEvaluationError(RuntimeError):
    """One or more offline model-quality gates failed."""


def _features(reading: TelemetryReading) -> list[float]:
    return [
        reading.temperature_c,
        reading.vibration_mm_s,
        reading.power_kw,
        float(reading.production_rate),
    ]


@dataclass(frozen=True, slots=True)
class FeatureReferenceDistribution:
    """Training proportions for deterministic, artifact-bound PSI bins."""

    bin_edges: tuple[float, ...]
    proportions: tuple[float, ...]


def _percentile(sorted_values: list[float], fraction: float) -> float:
    position = fraction * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    remainder = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * remainder


def _distribution(
    values: list[float],
    *,
    bin_edges: tuple[float, ...] | None = None,
) -> FeatureReferenceDistribution:
    if not values:
        raise ValueError("feature distribution requires at least one value")
    edges = bin_edges
    if edges is None:
        sorted_values = sorted(values)
        if sorted_values[0] == sorted_values[-1]:
            center = sorted_values[0]
            tolerance = max(abs(center) * 1e-9, 1e-9)
            edges = (center - tolerance, center + tolerance)
        else:
            edges = tuple(
                sorted({_percentile(sorted_values, quantile / 10) for quantile in range(1, 10)})
            )
    counts = [0] * (len(edges) + 1)
    for value in values:
        counts[bisect_right(edges, value)] += 1
    return FeatureReferenceDistribution(
        bin_edges=edges,
        proportions=tuple(count / len(values) for count in counts),
    )


def _reference_distributions(
    readings: list[TelemetryReading],
) -> tuple[tuple[str, FeatureReferenceDistribution], ...]:
    feature_rows = [_features(reading) for reading in readings]
    return tuple(
        (
            feature_name,
            _distribution([row[index] for row in feature_rows]),
        )
        for index, feature_name in enumerate(FEATURE_NAMES)
    )


@dataclass(frozen=True, slots=True)
class IsolationForestArtifact:
    """Validated metadata plus the fitted estimator."""

    estimator: IsolationForest
    model_id: str
    machine_id: str
    trained_at: str
    training_window_end: str
    training_samples: int
    reference_distributions: tuple[tuple[str, FeatureReferenceDistribution], ...]

    @property
    def trained_at_datetime(self) -> datetime:
        return datetime.fromisoformat(self.trained_at)

    @property
    def training_window_end_datetime(self) -> datetime:
        return datetime.fromisoformat(self.training_window_end)


@dataclass(frozen=True, slots=True)
class ModelEvaluationReport:
    """Bounded offline quality evidence for one machine-specific artifact."""

    model_id: str
    machine_id: str
    sample_count: int
    anomaly_rate: float
    feature_psi: tuple[tuple[str, float], ...]
    passed: bool
    failed_gates: tuple[str, ...]

    @property
    def maximum_feature_psi(self) -> float:
        return max((value for _, value in self.feature_psi), default=0.0)


class IsolationForestTrainer:
    """Fit a reproducible multivariate model outside the ingestion process."""

    def __init__(
        self,
        *,
        contamination: float = 0.05,
        minimum_samples: int = 100,
        random_state: int = 42,
        signer: ArtifactSigner,
    ) -> None:
        self._contamination = contamination
        self._minimum_samples = minimum_samples
        self._random_state = random_state
        self._signer = signer

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
            estimator=estimator,
            model_id=model_id,
            machine_id=machine_ids.pop(),
            trained_at=trained_at,
            training_window_end=max(reading.timestamp for reading in readings).isoformat(),
            training_samples=len(readings),
            reference_distributions=_reference_distributions(readings),
        )
        self._write_artifact(artifact, output_path)
        return artifact

    def _write_artifact(self, artifact: IsolationForestArtifact, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": ARTIFACT_FORMAT_VERSION,
            "feature_names": FEATURE_NAMES,
            "sklearn_version": sklearn.__version__,
            "model_id": artifact.model_id,
            "machine_id": artifact.machine_id,
            "trained_at": artifact.trained_at,
            "training_window_end": artifact.training_window_end,
            "training_samples": artifact.training_samples,
            "reference_distributions": {
                name: {
                    "bin_edges": distribution.bin_edges,
                    "proportions": distribution.proportions,
                }
                for name, distribution in artifact.reference_distributions
            },
            "estimator": artifact.estimator,
        }
        signature_path = artifact_signature_path(output_path)
        with NamedTemporaryFile(dir=output_path.parent, prefix=".model-", delete=False) as file:
            temporary_path = Path(file.name)
        with NamedTemporaryFile(
            dir=output_path.parent,
            prefix=".signature-",
            delete=False,
        ) as signature_file:
            temporary_signature_path = Path(signature_file.name)
        try:
            joblib.dump(payload, temporary_path)
            signature = self._signer.sign(temporary_path.read_bytes())
            temporary_signature_path.write_bytes(signature)
            os.chmod(temporary_path, 0o644)
            os.chmod(temporary_signature_path, 0o644)
            os.replace(temporary_signature_path, signature_path)
            os.replace(temporary_path, output_path)
        finally:
            temporary_path.unlink(missing_ok=True)
            temporary_signature_path.unlink(missing_ok=True)


class IsolationForestAnomalyDetector:
    """Run inference from a trusted, versioned Isolation Forest artifact."""

    def __init__(self, artifact: IsolationForestArtifact) -> None:
        self._artifact = artifact

    @property
    def artifact(self) -> IsolationForestArtifact:
        return self._artifact

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        expected_machine_id: str,
        verifier: ArtifactVerifier,
    ) -> IsolationForestAnomalyDetector:
        try:
            serialized = path.read_bytes()
            signature = artifact_signature_path(path).read_bytes()
            verifier.verify(serialized, signature)
        except (OSError, ArtifactSigningError) as error:
            raise MlArtifactError(f"could not verify ML artifact {path}: {error}") from error
        try:
            loaded = joblib.load(BytesIO(serialized))
        except Exception as error:
            raise MlArtifactError(f"could not load ML artifact {path}: {error}") from error
        try:
            artifact = cls._validate_artifact(cast(Any, loaded))
            if artifact.machine_id != expected_machine_id:
                raise MlArtifactError(
                    "ML artifact machine does not match configured machine: "
                    f"expected {expected_machine_id}, got {artifact.machine_id}"
                )
            return cls(artifact)
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
        trained_at = datetime.fromisoformat(str(payload["trained_at"]))
        if trained_at.tzinfo is None or trained_at.utcoffset() is None:
            raise MlArtifactError("ML artifact training timestamp must include a UTC offset")
        training_window_end = datetime.fromisoformat(str(payload["training_window_end"]))
        if training_window_end.tzinfo is None or training_window_end.utcoffset() is None:
            raise MlArtifactError("ML artifact training-window timestamp must include a UTC offset")
        reference_payload = payload.get("reference_distributions")
        if not isinstance(reference_payload, dict) or set(reference_payload) != set(FEATURE_NAMES):
            raise MlArtifactError("ML artifact reference distribution contract is invalid")
        reference_distributions = tuple(
            (
                feature_name,
                IsolationForestAnomalyDetector._validate_reference_distribution(
                    reference_payload[feature_name]
                ),
            )
            for feature_name in FEATURE_NAMES
        )
        return IsolationForestArtifact(
            estimator=estimator,
            model_id=str(payload["model_id"]),
            machine_id=str(payload["machine_id"]),
            trained_at=trained_at.isoformat(),
            training_window_end=training_window_end.isoformat(),
            training_samples=int(payload["training_samples"]),
            reference_distributions=reference_distributions,
        )

    @staticmethod
    def _validate_reference_distribution(loaded: Any) -> FeatureReferenceDistribution:
        if not isinstance(loaded, dict):
            raise MlArtifactError("ML artifact feature reference must be a dictionary")
        edges = tuple(float(value) for value in loaded.get("bin_edges", ()))
        proportions = tuple(float(value) for value in loaded.get("proportions", ()))
        if (
            len(proportions) != len(edges) + 1
            or not all(isfinite(value) for value in (*edges, *proportions))
            or any(left >= right for left, right in pairwise(edges))
            or any(value < 0 for value in proportions)
            or not isclose(sum(proportions), 1.0, abs_tol=1e-9)
        ):
            raise MlArtifactError("ML artifact feature reference values are invalid")
        return FeatureReferenceDistribution(edges, proportions)

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


class IsolationForestModelEvaluator:
    """Evaluate post-training data against explicit anomaly-rate and PSI gates."""

    def __init__(
        self,
        artifact: IsolationForestArtifact,
        *,
        minimum_samples: int,
        maximum_anomaly_rate: float,
        maximum_feature_psi: float,
    ) -> None:
        self._artifact = artifact
        self._minimum_samples = minimum_samples
        self._maximum_anomaly_rate = maximum_anomaly_rate
        self._maximum_feature_psi = maximum_feature_psi

    def evaluate(self, readings: list[TelemetryReading]) -> ModelEvaluationReport:
        if any(reading.machine_id != self._artifact.machine_id for reading in readings):
            raise ValueError("evaluation readings must belong to the artifact machine")
        feature_rows = [_features(reading) for reading in readings]
        predictions = (
            self._artifact.estimator.predict(feature_rows).tolist() if feature_rows else []
        )
        anomaly_rate = (
            sum(prediction == -1 for prediction in predictions) / len(predictions)
            if predictions
            else 0.0
        )
        feature_psi = tuple(
            (
                feature_name,
                self._population_stability_index(
                    reference,
                    [row[index] for row in feature_rows],
                ),
            )
            for index, (feature_name, reference) in enumerate(
                self._artifact.reference_distributions
            )
        )
        failed_gates: list[str] = []
        if len(readings) < self._minimum_samples:
            failed_gates.append("minimum_samples")
        if anomaly_rate > self._maximum_anomaly_rate:
            failed_gates.append("maximum_anomaly_rate")
        if any(value > self._maximum_feature_psi for _, value in feature_psi):
            failed_gates.append("maximum_feature_psi")
        return ModelEvaluationReport(
            model_id=self._artifact.model_id,
            machine_id=self._artifact.machine_id,
            sample_count=len(readings),
            anomaly_rate=anomaly_rate,
            feature_psi=feature_psi,
            passed=not failed_gates,
            failed_gates=tuple(failed_gates),
        )

    @staticmethod
    def _population_stability_index(
        reference: FeatureReferenceDistribution,
        values: list[float],
    ) -> float:
        if not values:
            return 0.0
        observed = _distribution(values, bin_edges=reference.bin_edges)
        epsilon = 1e-6
        return sum(
            (max(actual, epsilon) - max(expected, epsilon))
            * log(max(actual, epsilon) / max(expected, epsilon))
            for expected, actual in zip(
                reference.proportions,
                observed.proportions,
                strict=True,
            )
        )
