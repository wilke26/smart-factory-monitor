import json
import logging

from smart_factory.logging import JsonFormatter, configure_logging


def test_json_formatter_includes_structured_fields() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "accepted", (), None)
    record.machine_id = "press-01"

    document = json.loads(JsonFormatter().format(record))

    assert document["event"] == "accepted"
    assert document["machine_id"] == "press-01"


def test_configure_logging_replaces_root_handler() -> None:
    configure_logging("DEBUG")

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
