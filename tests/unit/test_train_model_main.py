from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest

from smart_factory.config import MlSettings
from smart_factory.train_model_main import run


@patch("smart_factory.train_model_main.IsolationForestTrainer")
@patch("smart_factory.train_model_main.PsycopgTelemetryRepository")
def test_trains_from_bounded_history_and_closes_repository(
    repository_type: Mock, trainer_type: Mock
) -> None:
    ml_settings = MlSettings(
        enabled=False,
        model_directory="/models",
        machine_ids=("press-01", "press-02"),
        contamination=0.03,
        minimum_training_samples=50,
        training_limit=500,
    )
    readings = [Mock()] * 50
    repository_type.return_value.load_recent_readings.return_value = readings
    trainer_type.return_value.train.side_effect = [
        Mock(model_id="model-1", machine_id="press-01", training_samples=1),
        Mock(model_id="model-2", machine_id="press-02", training_samples=1),
    ]

    settings = Mock(
        database_url="postgresql://database/smart_factory",
        database_pool_min_size=1,
        database_pool_max_size=4,
        database_connect_timeout_seconds=10,
    )

    run(settings, ml_settings)

    repository_type.return_value.open.assert_called_once_with(timeout=10)
    assert repository_type.return_value.load_recent_readings.call_args_list == [
        call("press-01", 500),
        call("press-02", 500),
    ]
    trainer_type.assert_called_once_with(contamination=0.03, minimum_samples=50)
    assert trainer_type.return_value.train.call_args_list == [
        call(readings, Path("/models/press-01.joblib")),
        call(readings, Path("/models/press-02.joblib")),
    ]
    repository_type.return_value.close.assert_called_once()


@patch("smart_factory.train_model_main.IsolationForestTrainer")
@patch("smart_factory.train_model_main.PsycopgTelemetryRepository")
def test_does_not_replace_any_model_when_one_machine_lacks_history(
    repository_type: Mock, trainer_type: Mock
) -> None:
    ml_settings = MlSettings(
        enabled=False,
        model_directory="/models",
        machine_ids=("press-01", "press-02"),
        contamination=0.03,
        minimum_training_samples=50,
        training_limit=500,
    )
    repository_type.return_value.load_recent_readings.side_effect = [
        [Mock()] * 50,
        [Mock()] * 49,
    ]
    settings = Mock(
        database_url="postgresql://database/smart_factory",
        database_pool_min_size=1,
        database_pool_max_size=4,
        database_connect_timeout_seconds=10,
    )

    with pytest.raises(ValueError, match="press-02; got 49"):
        run(settings, ml_settings)

    trainer_type.return_value.train.assert_not_called()
    repository_type.return_value.close.assert_called_once()
