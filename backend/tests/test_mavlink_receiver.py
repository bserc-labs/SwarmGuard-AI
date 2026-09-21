"""The MAVLink receiver's translation of a wire message into an ingest packet."""

import inspect

from pymavlink.dialects.v20 import common as mavlink

import schemas
from services.mavlink_receiver import MavlinkReceiver


def _position(time_boot_ms: int = 123_456):
    return mavlink.MAVLink_global_position_int_message(
        time_boot_ms=time_boot_ms, lat=340_522_000, lon=-1_182_437_000,
        alt=150_000, relative_alt=150_000, vx=100, vy=0, vz=0, hdg=9000,
    )


def _capture(receiver: MavlinkReceiver) -> list[dict]:
    """Swap `_ingest_packet` for a recorder, sync or async to match the receiver."""
    captured: list[dict] = []

    if inspect.iscoroutinefunction(MavlinkReceiver._ingest_packet):
        async def record(packet_data: dict) -> None:
            captured.append(packet_data)
    else:
        def record(packet_data: dict) -> None:
            captured.append(packet_data)

    receiver._ingest_packet = record
    return captured


def _drive(receiver: MavlinkReceiver, msg) -> None:
    result = receiver._process_message(msg)
    if inspect.isawaitable(result):
        import asyncio

        async def _run():
            await result

        asyncio.run(_run())


def test_global_position_int_carries_the_autopilot_boot_clock():
    """time_boot_ms is the monotonic device clock the kinematic guard rates on.

    Without it every MAVLink-sourced packet fell back to server arrival time,
    which is the defect the guard's time-base fix exists to close.
    """
    receiver = MavlinkReceiver()
    captured = _capture(receiver)

    _drive(receiver, _position(time_boot_ms=123_456))

    assert len(captured) == 1
    packet_data = captured[0]
    assert packet_data["sample_time_ms"] == 123_456
    assert packet_data["drone_id"] == "DRONE_MAV_0"  # constructed messages report system 0

    # And it is a value the ingest schema accepts, including at the uint32 ceiling.
    assert schemas.TelemetryPacket(**packet_data).sample_time_ms == 123_456
    _drive(receiver, _position(time_boot_ms=2**32 - 1))
    assert schemas.TelemetryPacket(**captured[1]).sample_time_ms == 2**32 - 1
