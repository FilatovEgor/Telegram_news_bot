import logging

import pytest
from sqlalchemy import create_engine, text

from app.database.observability import install_pool_observability, install_slow_query_logging


def test_slow_query_logging_records_timing_without_sql_or_parameters(caplog):
    engine = create_engine("sqlite:///:memory:")
    try:
        install_slow_query_logging(engine, threshold_ms=0)
        with caplog.at_level(logging.WARNING, logger="app.database.observability"):
            with engine.connect() as connection:
                connection.execute(
                    text("SELECT :private_value"),
                    {"private_value": "must-not-be-logged"},
                )

        assert "Slow database query" in caplog.text
        assert "operation=SELECT" in caplog.text
        assert "duration_ms=" in caplog.text
        assert "SELECT :private_value" not in caplog.text
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



def test_pool_observability_logs_overflow_transitions_without_connection_data(caplog, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pool-observability.db'}",
        pool_size=1,
        max_overflow=1,
    )
    try:
        with caplog.at_level(logging.INFO, logger="app.database.observability"):
            install_pool_observability(engine, max_overflow=1)
            base_connection = engine.connect()
            overflow_connection = engine.connect()
            overflow_connection.close()
            base_connection.close()

        assert "Database pool configured pool_size=1 max_overflow=1 max_connections=2" in caplog.text
        assert "Database pool overflow entered" in caplog.text
        assert "Database pool returned to base capacity" in caplog.text
        assert "sqlite" not in caplog.text.casefold()
    finally:
        engine.dispose()
