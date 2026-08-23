
def test_insert_and_read_telemetry(db_session):
    from sqlalchemy.sql import text

    import models
    
    # Insert telemetry directly
    new_log = models.TelemetryLog(
        drone_id="test_drone_001",
        latitude=37.7749,
        longitude=-122.4194,
        altitude=100.5,
        speed=15.2,
        battery=98.0,
        packet_sequence=1
    )
    db_session.add(new_log)
    db_session.commit()
    
    # Read it back using raw SQL to verify TimescaleDB storage
    result = db_session.execute(text("SELECT drone_id, latitude FROM telemetry_logs WHERE drone_id = 'test_drone_001' ORDER BY created_at DESC LIMIT 1;")).fetchone()
    
    assert result is not None
    assert result[0] == "test_drone_001"
    assert result[1] == 37.7749
