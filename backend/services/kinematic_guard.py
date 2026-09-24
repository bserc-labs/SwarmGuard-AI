"""Tier 1 detector: deterministic physical-plausibility checks.

Why this exists alongside the ML model:

The v2 RandomForest, trained on real PX4 flights and validated
leave-one-flight-out, scores F1 0.086 with a 0.862 false-positive rate. It does
not generalize across flights, so it cannot be the thing that decides whether
an operator sees an alert. See model_train/ and backend/models_ml/v2/
evaluation.json -- which is authoritative -- for the full numbers.

What does work is physics. A UAV cannot be in two places 5 km apart in 1.5
seconds. It cannot climb at 200 m/s. Its GPS-derived ground speed and the
speed its airframe reports cannot disagree by two orders of magnitude unless
one of them is lying -- and the airframe's own accelerometers are much harder
to spoof than its GNSS receiver. Those are the checks here.

Properties that matter for a defense system, and that a learned model on this
dataset does not currently provide:

* **Deterministic.** The same telemetry always produces the same verdict.
* **Zero false positives on physically valid flight.** A threshold set beyond
  the airframe's envelope cannot fire on a real manoeuvre.
* **Auditable.** Every alert carries the observed value, the threshold it
  crossed, and by what factor. An analyst can check the arithmetic.
* **No training data required.** Thresholds come from the airframe's spec
  sheet, not from a dataset that may not resemble the deployment environment.

This is not a replacement for anomaly detection -- it catches gross
manipulation, not subtle drift. It is the floor, not the ceiling.
"""

import math
from dataclasses import dataclass, field
from typing import Any

from config import get_settings

settings = get_settings()

EARTH_RADIUS_M = 6371000.0

# Which clock supplied the interval a rate was computed over. Recorded in the
# evidence: an analyst reading "5,533 m in 1.50 s" needs to know whether that
# 1.50 s is flight time or the gap between two database inserts.
TIME_BASE_DEVICE = "device"
TIME_BASE_ARRIVAL = "arrival"
_TIME_BASE_LABELS = {
    TIME_BASE_DEVICE: "device clock",
    TIME_BASE_ARRIVAL: "server arrival time",
}

# Interval note for a pair rated on the device clock although the newest packet
# was not stored in sample order: its partner is its nearest neighbour on the
# device clock, not the packet stored just before it. See KinematicGuard._pair.
NOTE_REORDERED = "device_clock_reordered"

# The device clock could not be used, and the packets arrived too close together
# for arrival time to stand in for it. No interval, so no verdict. See
# KinematicGuard._pair.
NOTE_ARRIVAL_UNUSABLE = "arrival_gap_too_small_to_rate"

# The notes that mean "the two clocks disagree about this pair". Missing device
# time is not one of them: there arrival time is all there has ever been, and
# the rates computed from it are the ones this detector shipped with.
_CLOCKS_DISAGREE = frozenset(
    {"device_clock_not_monotonic", "device_interval_exceeds_arrival"}
)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two fixes."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    )
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@dataclass
class Violation:
    """One failed physical check, with the arithmetic that produced it."""

    check: str
    observed: float
    threshold: float
    unit: str
    detail: str
    # True when crossing *below* the threshold is the failure -- satellite
    # count, for example. Without this the ratio runs the wrong way: a
    # collapse from 13 satellites to 4 scored 4/6 = 0.67, i.e. *less* severe
    # than not failing at all, which dragged a real jamming event down to LOW.
    lower_is_worse: bool = False

    @property
    def exceedance(self) -> float:
        """How many times past the threshold. 1.0 means exactly at it."""
        observed, threshold = abs(self.observed), abs(self.threshold)

        if self.lower_is_worse:
            # Total loss is the worst case, not a division error.
            if observed == 0:
                return float(threshold) if threshold else 1.0
            return threshold / observed

        if threshold == 0:
            return float("inf") if observed > 0 else 0.0
        return observed / threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "observed": round(self.observed, 3),
            "threshold": round(self.threshold, 3),
            "unit": self.unit,
            "exceedance_factor": round(self.exceedance, 2),
            "detail": self.detail,
        }


@dataclass
class GuardVerdict:
    triggered: bool
    attack_type: str | None = None
    severity: str | None = None
    threat_score: float = 0.0
    violations: list[Violation] = field(default_factory=list)
    # Which clock the interval came from (TIME_BASE_*), the interval itself,
    # and why the device clock was not used when it was not. All None when no
    # interval was computed at all (fewer than two packets, or no timestamps).
    time_base: str | None = None
    interval_s: float | None = None
    interval_note: str | None = None

    def to_detection(self, drone_id: str) -> dict[str, Any]:
        """Shape this as the detection dict IncidentEngine consumes.

        `shap_values` carries the violation records rather than SHAP
        attributions. They serve the same role in the UI -- ranked evidence for
        why this fired -- and unlike SHAP over a non-generalizing model, each
        number here is checkable by hand.
        """
        ranked = [
            {
                "feature": v.check,
                "shap_value": v.exceedance,
                "magnitude": v.exceedance,
                "observed": round(v.observed, 3),
                "threshold": round(v.threshold, 3),
                "unit": v.unit,
            }
            for v in self.violations
        ]
        primary = self.violations[0] if self.violations else None
        return {
            "drone_id": drone_id,
            "prediction": {
                "is_anomaly": self.triggered,
                "anomaly_score": self.threat_score,
                "threat_score": self.threat_score,
                "threat_level": self.severity,
                # Stated explicitly so the incident engine can use the band this
                # detector computed rather than re-deriving one from the score.
                #
                # The two disagree. `_severity` reads the exceedance ratio and
                # the number of independent failing checks; alert_service reads
                # only the log-scaled score against fixed cut-offs. Around 3x
                # past a limit the guard says HIGH and the score lands at 59.6,
                # which alert_service bands as MEDIUM -- so an incident was
                # filed one level below what the detector that raised it
                # concluded.
                "severity": self.severity,
            },
            "explanation": {
                "ranked_features": ranked,
                "summary": {
                    "Attack Type": self.attack_type,
                    "Primary Cause": primary.detail if primary else "",
                    "Secondary Cause": (
                        self.violations[1].detail if len(self.violations) > 1 else "None"
                    ),
                    "Supporting Indicators": ", ".join(
                        v.detail for v in self.violations[2:5]
                    ) or "None",
                    "Detector": "kinematic_guard",
                    "Time Base": _TIME_BASE_LABELS.get(self.time_base or "", "unknown"),
                },
                "metadata": {
                    "detector": "kinematic_guard",
                    "model_version": "physics-v1",
                    "feature_engineering_version": "physics-v1",
                    "deterministic": True,
                    "violations": [v.to_dict() for v in self.violations],
                    "explanation_confidence_percent": 100.0,
                    "time_base": self.time_base,
                    "interval_s": round(self.interval_s, 3) if self.interval_s is not None else None,
                    "interval_note": self.interval_note,
                },
            },
        }


class KinematicGuard:
    """Physical-plausibility checks over a telemetry window."""

    # Thresholds describe the airframe's envelope with margin, not typical
    # behaviour. They are set so that no physically achievable manoeuvre can
    # trip them -- the cost of a false positive in this system is an operator
    # grounding a healthy aircraft.
    def __init__(self) -> None:
        self.max_speed_mps = settings.GUARD_MAX_SPEED_MPS
        self.max_climb_mps = settings.GUARD_MAX_CLIMB_MPS
        self.gps_speed_error_mps = settings.GUARD_GPS_SPEED_ERROR_MPS
        self.min_satellites = settings.GUARD_MIN_SATELLITES
        self.device_clock_max_lead_s = settings.GUARD_DEVICE_CLOCK_MAX_LEAD_S
        self.device_clock_max_reorder_s = settings.GUARD_DEVICE_CLOCK_MAX_REORDER_S
        self.min_reset_gap_s = settings.GUARD_MIN_RESET_GAP_S

    def evaluate(self, history: list[dict[str, Any]]) -> GuardVerdict:
        """Check the most recent packet against its nearest neighbour in time.

        Needs two packets: every check is a rate, and a rate needs an interval.
        The interval comes from the device's own sample clock when both packets
        carry one and it is usable, otherwise from server arrival time -- see
        `_interval_seconds` for why that distinction is the whole detector, and
        `_pair` for which packet the newest one is compared with.
        """
        if len(history) < 2:
            return GuardVerdict(triggered=False)

        # In flight order: `prev` was sampled first. The newest stored packet is
        # one of the two, but not necessarily `curr`.
        prev, curr, dt, time_base, note = self._pair(history)
        if dt is None or dt <= 0:
            # Two packets sharing a timestamp make every rate infinite. Decline
            # rather than report a division artefact as an attack.
            return GuardVerdict(
                triggered=False,
                time_base=None if dt is None else time_base,
                interval_note=note,
            )
        clock = _TIME_BASE_LABELS.get(time_base or "", "unknown clock")

        violations: list[Violation] = []

        distance = haversine_m(
            prev["latitude"], prev["longitude"], curr["latitude"], curr["longitude"]
        )
        gps_speed = distance / dt
        reported_speed = curr.get("speed") or 0.0

        # 1. Implied ground speed beyond the airframe's envelope.
        if gps_speed > self.max_speed_mps:
            violations.append(
                Violation(
                    check="gps_implied_speed",
                    observed=gps_speed,
                    threshold=self.max_speed_mps,
                    unit="m/s",
                    detail=(
                        f"Position moved {distance:,.0f} m in {dt:.2f} s ({clock}), implying "
                        f"{gps_speed:,.0f} m/s — beyond the airframe's {self.max_speed_mps:.0f} m/s limit."
                    ),
                )
            )

        # 2. GNSS and airframe disagree about how fast it is going. The core
        #    spoofing signature: a forged position moves, the accelerometers
        #    do not.
        speed_error = abs(gps_speed - reported_speed)
        if speed_error > self.gps_speed_error_mps:
            violations.append(
                Violation(
                    check="gps_airframe_speed_mismatch",
                    observed=speed_error,
                    threshold=self.gps_speed_error_mps,
                    unit="m/s",
                    detail=(
                        f"GPS track implies {gps_speed:,.0f} m/s ({clock}) but the airframe reports "
                        f"{reported_speed:,.1f} m/s — a {speed_error:,.0f} m/s disagreement."
                    ),
                )
            )

        # 3. Climb or descent rate beyond the airframe's envelope.
        alt_change = (curr.get("altitude") or 0.0) - (prev.get("altitude") or 0.0)
        vertical_speed = alt_change / dt
        if abs(vertical_speed) > self.max_climb_mps:
            violations.append(
                Violation(
                    check="vertical_speed",
                    observed=vertical_speed,
                    threshold=self.max_climb_mps,
                    unit="m/s",
                    detail=(
                        f"Altitude changed {alt_change:,.1f} m in {dt:.2f} s ({clock}) "
                        f"({vertical_speed:,.1f} m/s), beyond the {self.max_climb_mps:.0f} m/s limit."
                    ),
                )
            )

        # 4. Satellite count collapse. Only counts as evidence if the fix was
        #    healthy a moment ago -- a drone that has never had lock is not
        #    under attack, it is on the ground indoors.
        prev_sats = prev.get("satellites")
        curr_sats = curr.get("satellites")
        if (
            prev_sats is not None
            and curr_sats is not None
            and prev_sats >= self.min_satellites
            and curr_sats < self.min_satellites
        ):
            violations.append(
                Violation(
                    check="satellite_loss",
                    observed=float(curr_sats),
                    threshold=float(self.min_satellites),
                    unit="satellites",
                    lower_is_worse=True,
                    detail=(
                        f"Satellite count fell from {prev_sats} to {curr_sats}, "
                        "consistent with GNSS jamming or a spoofed constellation."
                    ),
                )
            )

        if not violations:
            return GuardVerdict(
                triggered=False, time_base=time_base, interval_s=dt, interval_note=note
            )

        # Rank by how far past the threshold, so the most egregious violation
        # leads the explanation.
        violations.sort(key=lambda v: v.exceedance, reverse=True)
        return GuardVerdict(
            triggered=True,
            attack_type=self._classify(violations),
            severity=self._severity(violations),
            threat_score=self._score(violations),
            violations=violations,
            time_base=time_base,
            interval_s=dt,
            interval_note=note,
        )

    def _pair(
        self, history: list[dict[str, Any]]
    ) -> tuple[dict, dict, float | None, str | None, str | None]:
        """Which two samples to rate, in flight order, and the interval between.

        The newest stored packet is always one of the two. Its partner is its
        nearest neighbour on the device clock within the window. Normally that
        is the packet stored just before it, which is all this used to consider.

        Under load it is often not. A drone's requests queue for seconds and are
        stored out of order, so the packet stored just before may have been
        sampled *later* (the clock seems to run backwards: a reboot?) or long
        *before* (a straggler, so the device interval outruns arrival: a broken
        clock?). Both sent the pair to the arrival-time fallback, and packets
        flushed from one queue arrive milliseconds apart -- the load test of
        2026-09-22 filed 200 false GPS_SPOOFING incidents against healthy
        drones that way (reports/06-LOAD-TEST-RESULTS.md). A late packet's
        sample time is still true; it only has to meet its real neighbour.

        In order of preference:

        1. The sample just before it on the device clock, when the device
           interval to it is believable. The ordinary case, and a late packet
           whose predecessor is still in the window.
        2. The sample just after it, when that is no more than
           `device_clock_max_reorder_s` ahead: a packet delivered late past
           everything else in the window.
        3. Otherwise as before: the predecessor if there was one, else the
           packet stored just before it, through `_interval_seconds` -- which
           falls back to arrival time. A clock further behind the whole window
           than any reorder is a reboot or a counter wrap, and arrival time is
           the only interval left.

        Neither neighbour weakens the check. A forged position is as far from
        its real neighbour as from any other; only the divisor changed, and it
        is now the true flight time between the two samples.
        """
        curr = history[-1]
        stored_prev = history[-2]
        curr_ms = curr.get("sample_time_ms")
        if curr_ms is None:
            return (stored_prev, curr, *self._interval_seconds(stored_prev, curr))

        timed = [p for p in history[:-1] if p.get("sample_time_ms") is not None]
        before = [p for p in timed if p["sample_time_ms"] < curr_ms]
        after = [p for p in timed if p["sample_time_ms"] > curr_ms]

        predecessor = None
        if before:
            # reversed(): among equal sample times, the copy stored last.
            predecessor = max(reversed(before), key=lambda p: p["sample_time_ms"])
            dt, time_base, note = self._interval_seconds(predecessor, curr)
            if time_base == TIME_BASE_DEVICE:
                if predecessor is not stored_prev:
                    note = NOTE_REORDERED
                return predecessor, curr, dt, time_base, note

        if after:
            successor = min(after, key=lambda p: p["sample_time_ms"])
            step = (successor["sample_time_ms"] - curr_ms) / 1000.0
            if step <= self.device_clock_max_reorder_s:
                return curr, successor, step, TIME_BASE_DEVICE, NOTE_REORDERED

        partner = predecessor if predecessor is not None else stored_prev
        dt, time_base, note = self._interval_seconds(partner, curr)

        # Falling back to arrival time assumes the packets arrived far enough
        # apart for that spacing to mean something. When the clocks disagree
        # because one packet was simply delivered very late, they did not: it
        # arrives in the same breath as the packets that overtook it, and
        # dividing real motion by milliseconds implies hundreds of metres per
        # second. Measured: one packet in ten held back 60 s produced 40 false
        # CRITICAL spoof alerts against drones flying clean circles.
        #
        # The reason to trust arrival time here was a reset -- a reboot or a
        # counter wrap. A reset takes time. No flight controller reboots in the
        # gap between two packets delivered milliseconds apart, so below
        # GUARD_MIN_RESET_GAP_S this is a late packet, there is no interval
        # worth dividing by, and the honest answer is no verdict at all.
        if note in _CLOCKS_DISAGREE and (dt is None or dt < self.min_reset_gap_s):
            return partner, curr, None, None, NOTE_ARRIVAL_UNUSABLE

        # A reset also restarts the clock. time_boot_ms after a reboot (or a
        # uint32 wrap) counts up from ~0, so it cannot show more uptime than
        # the time since the partner arrived, plus delivery slack. A clock that
        # stepped back but still reads a minute of uptime four seconds after
        # the last delivery was not reset; its packet is late. Measured: when a
        # backlog drained after fresh traffic stopped, each drone's first late
        # packet arrived ~4 s after the last and was rated on that spacing --
        # 40 false GPS_SPOOFING incidents, one per drone (reports/06-LOAD-TEST-
        # RESULTS.md, section 7). A clock that merely repeats is left to the
        # arrival fallback as before: it is stalled, not late.
        if (
            note == "device_clock_not_monotonic"
            and dt is not None
            and partner.get("sample_time_ms") is not None
            and curr_ms < partner["sample_time_ms"]
            and not self.could_have_reset(curr_ms, dt)
        ):
            return partner, curr, None, None, NOTE_ARRIVAL_UNUSABLE
        return partner, curr, dt, time_base, note

    def could_have_reset(self, sample_time_ms: int, since_last_arrival_s: float) -> bool:
        """Whether a device clock reading this low could have restarted since the last delivery.

        Also asked by ingest (services/ingest_staleness.py), so the packet the
        guard would decline here is the packet ingest refuses.
        """
        return sample_time_ms / 1000.0 <= since_last_arrival_s + self.device_clock_max_lead_s

    def _interval_seconds(
        self, prev: dict, curr: dict
    ) -> tuple[float | None, str | None, str | None]:
        """The interval to divide by, which clock it came from, and why.

        This used to read only `created_at`, a server-side now() at insert. That
        is packet *arrival* cadence, not flight time, and with Tier 2 disabled
        this guard is the entire detector -- so every rate it checked was being
        divided by the wrong number. Two nominal packets delivered in a 50 ms
        burst implied 540 m/s and filed a CRITICAL spoof; a real jump whose
        packets happened to arrive far apart was diluted under the threshold.

        A rate needs a clock that is monotonic between two samples, not one
        that agrees with the wall. MAVLink `time_boot_ms` is exactly that, and
        `sample_time_ms` carries it. The device clock is preferred when both
        packets have one and it is usable; otherwise arrival time, as before,
        and the verdict records which so the evidence is honest about it.

        Returns (interval, time_base, note). `note` names the reason the device
        clock was not used; it is None on the device path.
        """
        arrival: float | None = None
        prev_t, curr_t = prev.get("created_at"), curr.get("created_at")
        if prev_t is not None and curr_t is not None:
            try:
                arrival = (curr_t - prev_t).total_seconds()
            except (TypeError, AttributeError):
                arrival = None

        prev_ms, curr_ms = prev.get("sample_time_ms"), curr.get("sample_time_ms")
        if prev_ms is None or curr_ms is None:
            if arrival is None:
                return None, None, "no_timestamps"
            return arrival, TIME_BASE_ARRIVAL, "device_time_absent"

        device = (curr_ms - prev_ms) / 1000.0

        # A reboot resets time_boot_ms to ~0, and a uint32 wraps after 49.7
        # days; either shows up as a backwards or repeated clock. Degrade to
        # arrival time rather than divide by a negative or zero interval.
        if device <= 0:
            return arrival, TIME_BASE_ARRIVAL, "device_clock_not_monotonic"

        # Clock-rate sanity bound, not an evasion defence: packets cannot have
        # been sampled much further apart than they were delivered plus
        # buffering. A device interval far beyond arrival means the clock is
        # broken or mis-scaled, and dividing by it would hide a real jump.
        # Buffered bursts run the other way (device > arrival by a little) and
        # are exactly the case the device clock exists for.
        if arrival is not None and device > arrival + self.device_clock_max_lead_s:
            return arrival, TIME_BASE_ARRIVAL, "device_interval_exceeds_arrival"

        return device, TIME_BASE_DEVICE, None

    @staticmethod
    def _classify(violations: list[Violation]) -> str:
        checks = {v.check for v in violations}
        # A position/speed contradiction is spoofing; satellite loss alone is
        # jamming. Both together is still spoofing -- a spoofer commonly
        # overpowers the real constellation on its way in.
        if checks & {"gps_implied_speed", "gps_airframe_speed_mismatch"}:
            return "GPS_SPOOFING"
        if "satellite_loss" in checks:
            return "SIGNAL_JAMMING"
        return "FLIGHT_INSTABILITY"

    @staticmethod
    def _severity(violations: list[Violation]) -> str:
        worst = max(v.exceedance for v in violations)
        # Exceedance is a ratio, so these bands are airframe-independent: 10x
        # past a physical limit is egregious whatever the limit is.
        if worst >= 10 or len(violations) >= 3:
            return "CRITICAL"
        if worst >= 3:
            return "HIGH"
        if worst >= 1.5:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _score(violations: list[Violation]) -> float:
        worst = max(v.exceedance for v in violations)
        # log-scaled: exceedance is unbounded above (a spoof can imply
        # 3,700 m/s), and a linear map would saturate on the first violation
        # and lose all resolution between "odd" and "impossible".
        base = min(100.0, 40.0 + 20.0 * math.log10(max(worst, 1.0) + 0.1) * 2)
        # Independent failing checks corroborate each other.
        return round(min(100.0, base + 10.0 * (len(violations) - 1)), 2)


kinematic_guard = KinematicGuard()
