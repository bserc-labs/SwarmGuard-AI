"""MAVLink ingest must not block the event loop.

`_listen_loop` is an asyncio task on the same loop that serves HTTP and
WebSockets. `_ingest_packet` used to run a psycopg2 SELECT, INSERT and COMMIT
inline on that loop for every GLOBAL_POSITION_INT -- about 10 Hz per vehicle --
so every packet stalled every client for a database round trip.

Driven with a fake message and a fake session, so no database is touched. The
fakes *record* what they saw and the assertions run afterwards on the loop side:
an assertion inside the worker thread would be swallowed by the receiver's own
`except Exception` and the test would pass vacuously.
"""

import asyncio
import threading
from typing import ClassVar

import pytest

import services.mavlink_receiver as mr
from services.mavlink_receiver import MavlinkReceiver

ORG = 1


class FakeMsg:
    """Just enough of a pymavlink message: get_type, get_srcSystem, fields."""

    def __init__(self, msg_type, src_system=7, **fields):
        self._type = msg_type
        self._src = src_system
        self.__dict__.update(fields)

    def get_type(self):
        return self._type

    def get_srcSystem(self):
        return self._src


def global_position(**overrides):
    # lat/lon in 1e7 deg, alt in mm, vx/vy in cm/s, hdg in cdeg (MAVLink units).
    fields = {
        "time_boot_ms": 5000, "lat": 129_716_000, "lon": 775_946_000,
        "relative_alt": 120_000, "vx": 300, "vy": 400, "hdg": 9000,
    }
    fields.update(overrides)
    return FakeMsg("GLOBAL_POSITION_INT", **fields)


class FakeSession:
    instances: ClassVar[list["FakeSession"]] = []

    def __init__(self):
        self.closed = False
        FakeSession.instances.append(self)

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _clean_module_state():
    """`_broadcast_tasks` is module-level and outlives each asyncio.run()."""
    mr._broadcast_tasks.clear()
    FakeSession.instances.clear()
    yield
    mr._broadcast_tasks.clear()


@pytest.fixture
def receiver(monkeypatch):
    monkeypatch.setattr(mr.settings, "MAVLINK_ORGANIZATION_ID", ORG)
    monkeypatch.setattr(mr, "SessionLocal", FakeSession)
    return MavlinkReceiver()


@pytest.fixture
def broadcasts(monkeypatch):
    seen: list[tuple] = []

    async def fake_broadcast(message, organization_id):
        seen.append((message, organization_id, threading.current_thread()))

    monkeypatch.setattr(mr.ws_manager, "broadcast", fake_broadcast)
    return seen


@pytest.fixture
def writes(monkeypatch):
    """Record each process_telemetry call; assertions happen on the loop side."""
    seen: list[dict] = []

    def fake_process(packet, db, *, organization_id=None, **kwargs):
        seen.append({
            "drone_id": packet.drone_id, "organization_id": organization_id,
            "thread": threading.current_thread(), "session_open": not db.closed,
        })
        return packet.model_dump()

    monkeypatch.setattr(mr.telemetry_service, "process_telemetry", fake_process)
    return seen


async def _drain():
    pending = [t for t in mr._broadcast_tasks if not t.done()]
    if pending:
        await asyncio.gather(*pending)


def test_the_database_write_runs_in_a_worker_thread_while_the_loop_keeps_running(
    receiver, broadcasts, monkeypatch
):
    release = threading.Event()
    seen: dict = {}

    def parked_process(packet, db, *, organization_id=None, **kwargs):
        seen["thread"] = threading.current_thread()
        release.wait(timeout=5)
        return packet.model_dump()

    monkeypatch.setattr(mr.telemetry_service, "process_telemetry", parked_process)

    async def scenario():
        loop_thread = threading.current_thread()
        ingest = asyncio.create_task(receiver._process_message(global_position()))

        # While the write is parked, the loop must still be able to run other work.
        ticks = 0
        for _ in range(50):
            await asyncio.sleep(0.01)
            ticks += 1
            if "thread" in seen:
                break
        for _ in range(5):
            await asyncio.sleep(0)
            ticks += 1

        still_writing = not ingest.done()
        release.set()
        await ingest
        await _drain()
        return loop_thread, ticks, still_writing

    loop_thread, ticks, still_writing = asyncio.run(scenario())

    assert ticks >= 5, "the event loop did not advance while the write was in flight"
    assert still_writing, "ingest finished before the database write was released"
    assert seen["thread"] is not loop_thread, "the blocking write ran on the event loop thread"
    assert len(broadcasts) == 1


def test_a_position_packet_is_persisted_then_broadcast_on_the_loop(receiver, broadcasts, writes):
    async def scenario():
        await receiver._process_message(global_position())
        await _drain()
        return threading.current_thread()

    loop_thread = asyncio.run(scenario())

    assert len(writes) == 1
    assert writes[0]["drone_id"] == "DRONE_MAV_7"
    assert writes[0]["organization_id"] == ORG
    assert writes[0]["thread"] is not loop_thread

    assert len(broadcasts) == 1
    message, organization_id, thread = broadcasts[0]
    assert organization_id == ORG
    assert thread is loop_thread, "delivery must stay on the loop, which owns the sockets"
    assert message["drone_id"] == "DRONE_MAV_7"
    assert message["latitude"] == pytest.approx(12.9716)
    assert message["longitude"] == pytest.approx(77.5946)
    assert message["altitude"] == pytest.approx(120.0)
    assert message["speed"] == pytest.approx(5.0)  # hypot(3, 4) m/s
    assert message["heading"] == pytest.approx(90.0)
    assert message["sample_time_ms"] == 5000


def test_each_packet_opens_and_closes_its_own_session(receiver, broadcasts, writes):
    """A Session is not thread-safe; work that leaves the loop must own one."""
    async def scenario():
        await receiver._process_message(global_position(time_boot_ms=1000))
        await receiver._process_message(global_position(time_boot_ms=1100))
        await _drain()

    asyncio.run(scenario())

    assert len(FakeSession.instances) == 2
    assert FakeSession.instances[0] is not FakeSession.instances[1]
    assert all(s.closed for s in FakeSession.instances)
    assert all(w["session_open"] for w in writes), "the session was closed before the write ran"


def test_a_failed_write_is_contained(receiver, broadcasts, monkeypatch):
    def failing_process(packet, db, **kwargs):
        raise ValueError("Database transaction failed")

    monkeypatch.setattr(mr.telemetry_service, "process_telemetry", failing_process)

    async def scenario():
        await receiver._process_message(global_position())  # must not raise
        await _drain()

    asyncio.run(scenario())

    assert broadcasts == [], "a packet that was never stored must not be broadcast"
    assert len(FakeSession.instances) == 1 and FakeSession.instances[0].closed


def test_only_position_messages_touch_the_database(receiver, broadcasts, writes):
    async def scenario():
        await receiver._process_message(FakeMsg("HEARTBEAT", base_mode=128, custom_mode=4))
        await receiver._process_message(FakeMsg("SYS_STATUS", battery_remaining=77))
        await receiver._process_message(FakeMsg("GPS_RAW_INT", satellites_visible=11))
        assert writes == [] and FakeSession.instances == []

        await receiver._process_message(global_position())
        await _drain()

    asyncio.run(scenario())

    assert len(writes) == 1
    message = broadcasts[0][0]
    # The state accumulated from the other message types rides on the position packet.
    assert message["battery"] == pytest.approx(77.0)
    assert message["armed_status"] is True
    assert message["flight_mode"] == "4"
    assert message["satellites"] == 11


def test_a_packet_is_dropped_when_no_organization_is_configured(receiver, broadcasts, writes, monkeypatch):
    monkeypatch.setattr(mr.settings, "MAVLINK_ORGANIZATION_ID", None)

    async def scenario():
        await receiver._process_message(global_position())
        await _drain()

    asyncio.run(scenario())

    assert writes == [] and broadcasts == [] and FakeSession.instances == []


def test_the_listen_loop_awaits_message_processing(receiver, monkeypatch):
    """If `_process_message` were called without `await`, this never completes."""
    processed: list = []

    class OneMessageConnection:
        def __init__(self):
            self.sent = False

        def recv_match(self, **kwargs):
            if self.sent:
                return None
            self.sent = True
            return global_position()

        def close(self):
            pass

    async def fake_process(msg):
        processed.append(msg.get_type())
        receiver.running = False

    receiver.mav_connection = OneMessageConnection()
    receiver.running = True
    monkeypatch.setattr(receiver, "_process_message", fake_process)

    asyncio.run(asyncio.wait_for(receiver._listen_loop(), timeout=3))

    assert processed == ["GLOBAL_POSITION_INT"]
