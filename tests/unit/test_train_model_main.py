from unittest.mock import Mock, patch

from smart_factory.config import MlSettings
from smart_factory.train_model_main import run


@patch("smart_factory.train_model_main.IsolationForestTrainer")
@patch("smart_factory.train_model_main.PsycopgTelemetryRepository")
def test_trains_from_bounded_history_and_closes_repository(
    repository_type: Mock, trainer_type: Mock
) -> None:
    ml_settings = MlSettings(
        enabled=False,
        model_path="/models/model.joblib",
        machine_id="press-01",
        contamination=0.03,
        minimum_training_samples=50,
        training_limit=500,
    )
    readings = [Mock()]
    repository_type.return_value.load_recent_readings.return_value = readings
    trainer_type.return_value.train.return_value = Mock(model_id="model-1", training_samples=1)

    settings = Mock(
        database_url="postgresql://database/smart_factory",
        database_pool_min_size=1,
        database_pool_max_size=4,
        database_connect_timeout_seconds=10,
    )

    run(settings, ml_settings)

    repository_type.return_value.open.assert_called_once_with(timeout=10)
    repository_type.return_value.load_recent_readings.assert_called_once_with("press-01", 500)
    trainer_type.assert_called_once_with(contamination=0.03, minimum_samples=50)
    repository_type.return_value.close.assert_called_once()
