from sqlalchemy import text


def test_timescaledb_extension(db_session):
    """Verify that TimescaleDB extension is enabled in the database."""
    result = db_session.execute(text("SELECT extname FROM pg_extension WHERE extname = 'timescaledb';")).fetchone()
    assert result is not None, "TimescaleDB extension is not enabled"
    assert result[0] == 'timescaledb'

def test_telemetry_logs_is_hypertable(db_session):
    """Verify that telemetry_logs is partitioned as a hypertable."""
    query = text("SELECT * FROM timescaledb_information.hypertables WHERE hypertable_name = 'telemetry_logs';")
    result = db_session.execute(query).fetchone()
    assert result is not None, "telemetry_logs is not a hypertable"
