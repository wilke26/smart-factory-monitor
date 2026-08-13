from unittest.mock import Mock

import pytest

from smart_factory.application.services.anomaly_detection import CompositeAnomalyDetector


def test_requires_at_least_one_detector() -> None:
    with pytest.raises(ValueError, match="at least one"):
        CompositeAnomalyDetector(())


def test_combines_findings_in_detector_order() -> None:
    reading = Mock()
    first_finding = Mock()
    second_finding = Mock()
    first = Mock(evaluate=Mock(return_value=(first_finding,)))
    second = Mock(evaluate=Mock(return_value=(second_finding,)))

    findings = CompositeAnomalyDetector((first, second)).evaluate(reading)

    assert findings == (first_finding, second_finding)
