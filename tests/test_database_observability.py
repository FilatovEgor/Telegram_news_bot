import logging

import pytest
from sqlalchemy import create_engine, text

from app.database.observability import install_slow_query_logging


def test_slow_query_logging_records_timing_without_sql_or_parameters(caplog):
    engine = create_engine("sqlite:///:memory:")
    try:
        install_slow_query_logging(engine, threshold_ms=0)
        with caplog.at_level(logging.WARNING, logger="app.database.observability"):
            with engine.connect() as connection:
                connection.execute(text("SELECT :private_value"), {"private_value": "must-not-be-logged"})

        assert "Slow database query" in caplog.text
        assert "operation=SELECT" in caplog.text
        assert "duration_ms=" in caplog.text
        assert "SELECT" not in caplog.text.split("Slow database query", 1)[-1].split("operation=", 1)[0]
        assert "must-not-be-logged" not in caplog.text
    finally:
        engine.dispose()


def test_slow_query_threshold_cannot_be_negative():
    engine = create_engine("sqlite:///:memory:")
    try:
        with pytest.raises(ValueError, match="must not be negative"):
            install_slow_query_logging(engine, threshold_ms=-1)
    finally:
        engine.dispose()
