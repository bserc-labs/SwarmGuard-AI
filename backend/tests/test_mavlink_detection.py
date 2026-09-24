"""Telemetry that arrives over MAVLink is scored, not just stored.

The receiver validated a packet, wrote it and broadcast it, and stopped there.
Nothing called the detection pipeline, so a deployment ingesting over MAVLink
had a kinematic guard, a geofence and an incident engine that no packet ever
reached: the dashboard could only ever show a clean sky.
"""

import asyncio
import uuid

import pytest

import models
from services import mavlink_receiver as receiver_module
from services.mavlink_receiver import mavlink_receiver


@pytest.fixture
def organization(db_session):
    suffix = uuid.uuid4().hex[:8]
    org = models.Organization(name=f"pytest mavlink {suffix}", slug=f"pytest-mav-{suffix}")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    yield org

    db_session.rollback()
    for table in (models.Incident, models.TelemetryLog, models.Drone):
        db_session.query(table).filter(table.organization_id == org.id).delete(
            synchronize_session=False
        )
    db_session.query(models.Organization).filter(models.Organization.id == org.id).delete(
        synchronize_session=False
    )
    db_session.commit()


def _packet(drone_id: str, *, lat: float, sample_ms: int, sequence: int) -> dict:
    return {
        "drone_id": drone_id,
        "latitude": lat,
        "longitude": -118.2437,
        "altitude": 120.0,
        "speed": 18.0,
        "heading": 90.0,
        "battery": 90.0,
        "flight_mode": "AUTO",
        "armed_status": True,
        "satellites": 12,
        "packet_sequence": sequence,
        "sample_time_ms": sample_ms,
    }


async def _drain(coro):
    """Run an ingest and let the tasks it fired finish."""
    await coro
    pending = list(receiver_module._detection_tasks) + list(receiver_module._broadcast_tasks)
    if pending:
        await asyncio.wait(pending, timeout=30)


class TestMavlinkReachesTheDetector:
    def test_every_packet_starts_a_detection_cycle(self, monkeypatch, organization):
        monkeypatch.setattr(receiver_module.settings, "MAVLINK_ORGANIZATION_ID", organization.id)
        monkeypatch.setattr(
            receiver_module.mavlink_receiver, "_persist_packet", staticmethod(lambda p, o: {})
        )
        monkeypatch.setattr(receiver_module.ws_manager, "broadcast", _noop)
        asked: list[tuple[str, int]] = []

        async def record(drone_id, organization_id):
            asked.append((drone_id, organization_id))

        monkeypatch.setattr(receiver_module, "run_detection", record)
        drone_id = f"mav-{uuid.uuid4().hex[:6]}"

        asyncio.run(
            _drain(mavlink_receiver._ingest_packet(_packet(drone_id, lat=34.05, sample_ms=0, sequence=1)))
        )

        assert asked == [(drone_id, organization.id)]

    def test_a_spoofed_track_over_mavlink_files_an_incident(
        self, monkeypatch, organization, db_session
    ):
        monkeypatch.setattr(receiver_module.settings, "MAVLINK_ORGANIZATION_ID", organization.id)
        monkeypatch.setattr(receiver_module.ws_manager, "broadcast", _noop)
        drone_id = f"mav-{uuid.uuid4().hex[:6]}"

        async def scenario():
            # 5.5 km apart, sampled 1.5 s apart: 3,700 m/s, which no airframe does.
            await _drain(mavlink_receiver._ingest_packet(
                _packet(drone_id, lat=34.0522, sample_ms=0, sequence=1)
            ))
            await _drain(mavlink_receiver._ingest_packet(
                _packet(drone_id, lat=34.1022, sample_ms=1500, sequence=2)
            ))

        asyncio.run(scenario())

        incidents = (
            db_session.query(models.Incident)
            .filter(
                models.Incident.organization_id == organization.id,
                models.Incident.drone_id == drone_id,
            )
            .all()
        )
        assert len(incidents) == 1, "a spoof over MAVLink must reach the incident engine"
        assert incidents[0].attack_type == "GPS_SPOOFING"

    def test_a_packet_with_no_organization_configured_is_dropped(self, monkeypatch):
        monkeypatch.setattr(receiver_module.settings, "MAVLINK_ORGANIZATION_ID", None)
        asked: list = []
        monkeypatch.setattr(
            receiver_module, "run_detection", lambda *a: asked.append(a) or _done()
        )

        asyncio.run(mavlink_receiver._ingest_packet(_packet("mav-x", lat=34.05, sample_ms=0, sequence=1)))

        assert asked == [], "no organization means no write, so nothing to detect on"


async def _noop(*args, **kwargs):
    return None


async def _done():
    return None
