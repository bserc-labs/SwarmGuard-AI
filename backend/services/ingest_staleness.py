"""Refuse telemetry that arrives too late for the detector to rate.

Past about 200 packets/second per process the queue grows in front of the
application, and packets are stored tens of seconds after they were sampled
and out of order (reports/06-LOAD-TEST-RESULTS.md). The kinematic guard does
not file alerts over them: a packet whose device clock sits far behind the
drone's recent packets, and that cannot be explained by a reset, gets no
verdict (services/kinematic_guard.py, `_pair`).

No verdict is honest, but it is not free. Every such packet is stored, costs a
detection cycle, and adds one to `swarmguard_guard_declined_total` -- detection
goes quiet exactly when the system is under stress. Refusing the packet at the
door instead turns that silence into a 503 the ground station can see and back
off from, and keeps the backlog out of storage and out of the detector.

The question is the guard's own, asked before the insert rather than after.
Against each of the drone's recent deliveries (the guard's window, newest
first), the packet is stale when its device clock is

  * more than GUARD_DEVICE_CLOCK_MAX_REORDER_S behind that delivery's -- too
    far for the guard to pair it with a neighbour -- and
  * not explainable by a reset: the delivery arrived less than
    GUARD_MIN_RESET_GAP_S ago, or the packet's clock shows more uptime than
    has passed since it did (KinematicGuard.could_have_reset).

Why a restarted drone is not locked out: after a reboot or a counter wrap the
clock counts up from zero, so its uptime never exceeds the time since the last
delivery before the reset. And why a drone whose clock steps back for some
other reason is not locked out for long: the refusal holds only while the new
clock is still more than the reorder tolerance behind, which real time closes
at the rate the clock runs.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import TelemetryLog
from services.kinematic_guard import KinematicGuard


@dataclass(frozen=True)
class Staleness:
    """How far behind the drone's recent deliveries a packet's clock sits."""

    stale: bool
    behind_s: float
    tolerance_s: float


def check(
    db: Session,
    *,
    organization_id: int,
    drone_id: str,
    sample_time_ms: int | None,
    guard: KinematicGuard,
    window: int,
) -> Staleness | None:
    """None when there is nothing to compare against; otherwise the verdict.

    One indexed read of at most `window` rows, newest first, on
    ix_telemetry_logs_org_drone_created_at -- the rows the detector would read
    for this drone. Elapsed time is measured on the database's clock, the one
    that stamped created_at.
    """
    if sample_time_ms is None:
        return None
    recent = (
        select(TelemetryLog.sample_time_ms, TelemetryLog.created_at)
        .where(
            TelemetryLog.organization_id == organization_id,
            TelemetryLog.drone_id == drone_id,
        )
        .order_by(TelemetryLog.created_at.desc())
        .limit(window)
        .subquery()
    )
    rows = db.execute(
        select(
            recent.c.sample_time_ms,
            func.extract("epoch", func.now() - recent.c.created_at),
        ).where(recent.c.sample_time_ms.isnot(None))
    ).all()
    if not rows:
        return None

    tolerance_s = guard.device_clock_max_reorder_s
    behind_s = max((newer - sample_time_ms) / 1000.0 for newer, _ in rows)
    stale = any(
        (newer - sample_time_ms) / 1000.0 > tolerance_s
        and (
            float(since) < guard.min_reset_gap_s
            or not guard.could_have_reset(sample_time_ms, float(since))
        )
        for newer, since in rows
    )
    return Staleness(stale=stale, behind_s=behind_s, tolerance_s=tolerance_s)
