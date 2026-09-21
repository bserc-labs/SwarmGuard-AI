"""Which clock the kinematic guard divides by.

Every check the guard makes is a rate, and the only interval it used to have
was `created_at` -- a server-side now() at insert. That is packet *arrival*
cadence, not flight time, and with Tier 2 disabled the guard is the whole
detector. Two consequences, both pinned below as before/after pairs:

  * two nominal packets delivered in a 50 ms burst implied 540 m/s and filed a
    CRITICAL spoof against a healthy aircraft;
  * a real 5.5 km jump whose packets arrived five minutes apart was diluted to
    18 m/s and never fired.

The existing suite in test_kinematic_guard.py is deliberately left untouched:
none of its packets carry `sample_time_ms`, so all of it exercises the arrival
fallback and proves that path behaves exactly as it did.
"""

from datetime import datetime, timedelta

import pytest

from services.kinematic_guard import (
    TIME_BASE_ARRIVAL,
    TIME_BASE_DEVICE,
    KinematicGuard,
    kinematic_guard,
)

T0 = datetime(2026, 1, 1, 12, 0, 0)
LAT, LON = 34.0522, -118.2437
NOMINAL_STEP = 0.000243  # ~27 m of latitude: 1.5 s at the reported 18 m/s
JUMP = 0.05  # ~5,560 m of latitude: the simulator's spoof injection


def packet(lat, *, arrival_s, sample_ms=None, speed=18.0, alt=150.0, created=True):
    row = {
        "drone_id": "D1",
        "latitude": lat,
        "longitude": LON,
        "altitude": alt,
        "speed": speed,
        "heading": 90.0,
        "battery": 90.0,
        "flight_mode": "AUTO",
        "armed_status": True,
        "satellites": 12,
        "packet_sequence": 0,
    }
    if created:
        row["created_at"] = T0 + timedelta(seconds=arrival_s)
    if sample_ms is not None:
        row["sample_time_ms"] = sample_ms
    return row


def without_device_time(rows):
    return [{k: v for k, v in r.items() if k != "sample_time_ms"} for r in rows]


class TestTheDefect:
    """Each case fails on the old arrival-only guard and passes now."""

    def test_a_delivery_burst_is_not_a_spoof(self):
        # 27 m apart, sampled 1.5 s apart -- 18 m/s, nominal -- but the two
        # packets were *delivered* 50 ms apart.
        rows = [
            packet(LAT, arrival_s=0.0, sample_ms=0),
            packet(LAT + NOMINAL_STEP, arrival_s=0.05, sample_ms=1500),
        ]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is False
        assert verdict.time_base == TIME_BASE_DEVICE
        assert verdict.interval_s == pytest.approx(1.5)
        assert verdict.interval_note is None

        # The same telemetry rated on arrival time is the false positive:
        # 27 m / 0.05 s = 540 m/s.
        old = kinematic_guard.evaluate(without_device_time(rows))
        assert old.triggered is True
        assert old.severity == "CRITICAL"

    def test_a_real_jump_is_not_diluted_by_slow_delivery(self):
        # A 5.5 km position jump between samples 1.5 s apart, whose packets
        # arrived 300 s apart. On arrival time that is 18.5 m/s against a
        # reported 18.0 -- both speed checks silent.
        rows = [
            packet(LAT, arrival_s=0.0, sample_ms=0),
            packet(LAT + JUMP, arrival_s=300.0, sample_ms=1500),
        ]
        assert kinematic_guard.evaluate(without_device_time(rows)).triggered is False

        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is True
        assert verdict.attack_type == "GPS_SPOOFING"
        assert verdict.time_base == TIME_BASE_DEVICE
        checks = {v.check for v in verdict.violations}
        assert {"gps_implied_speed", "gps_airframe_speed_mismatch"} <= checks

    def test_a_buffered_burst_within_tolerance_trusts_the_device(self):
        # 90 m over a device interval of 5 s = 18 m/s; delivered 50 ms apart.
        rows = [
            packet(LAT, arrival_s=0.0, sample_ms=0),
            packet(LAT + 0.000809, arrival_s=0.05, sample_ms=5000),
        ]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is False
        assert verdict.time_base == TIME_BASE_DEVICE


class TestFallbackToArrival:
    @pytest.mark.parametrize(
        "prev_ms,curr_ms",
        [(None, None), (0, None), (None, 1500)],
        ids=["neither", "only-prev", "only-curr"],
    )
    def test_without_device_time_on_both_packets(self, prev_ms, curr_ms):
        rows = [
            packet(LAT, arrival_s=0.0, sample_ms=prev_ms),
            packet(LAT + JUMP, arrival_s=1.5, sample_ms=curr_ms),
        ]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is True
        assert verdict.time_base == TIME_BASE_ARRIVAL
        assert verdict.interval_note == "device_time_absent"
        assert verdict.interval_s == pytest.approx(1.5)

    @pytest.mark.parametrize(
        "prev_ms,curr_ms",
        [(600_000, 500), (2**32 - 1, 200)],
        ids=["reboot", "uint32-wrap"],
    )
    def test_a_clock_reset_never_reaches_a_division(self, prev_ms, curr_ms):
        # time_boot_ms restarts at ~0 on reboot and wraps after 49.7 days.
        rows = [
            packet(LAT, arrival_s=0.0, sample_ms=prev_ms),
            packet(LAT, arrival_s=45.0, sample_ms=curr_ms),
        ]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is False
        assert verdict.time_base == TIME_BASE_ARRIVAL
        assert verdict.interval_note == "device_clock_not_monotonic"
        assert verdict.interval_s == pytest.approx(45.0)

    @pytest.mark.parametrize(
        "prev_ms,curr_ms", [(3000, 1500), (1500, 1500)], ids=["out-of-order", "stalled"]
    )
    def test_a_backwards_or_repeated_device_clock_uses_arrival(self, prev_ms, curr_ms):
        rows = [
            packet(LAT, arrival_s=0.0, sample_ms=prev_ms),
            packet(LAT + NOMINAL_STEP, arrival_s=1.5, sample_ms=curr_ms),
        ]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is False
        assert verdict.time_base == TIME_BASE_ARRIVAL
        assert verdict.interval_note == "device_clock_not_monotonic"
        assert verdict.interval_s == pytest.approx(1.5)

    def test_a_device_interval_far_beyond_arrival_is_disbelieved(self):
        # The device claims 1000 s passed between packets that arrived 1.5 s
        # apart. Dividing the jump by 1000 s would hide it: 5.6 m/s.
        rows = [
            packet(LAT, arrival_s=0.0, sample_ms=0),
            packet(LAT + JUMP, arrival_s=1.5, sample_ms=1_000_000),
        ]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is True
        assert verdict.time_base == TIME_BASE_ARRIVAL
        assert verdict.interval_note == "device_interval_exceeds_arrival"

        # The bound is a setting like the other thresholds, and it is what
        # decides: widen it and the same rows are rated on the device clock.
        lenient = KinematicGuard()
        lenient.device_clock_max_lead_s = 2000.0
        relaxed = lenient.evaluate(rows)
        assert relaxed.time_base == TIME_BASE_DEVICE
        assert relaxed.triggered is False


class TestDeclines:
    def test_no_interval_means_no_time_base(self):
        for rows in ([], [packet(LAT, arrival_s=0.0, sample_ms=0)]):
            verdict = kinematic_guard.evaluate(rows)
            assert verdict.triggered is False
            assert verdict.time_base is None
            assert verdict.interval_s is None

    def test_no_clock_at_all_declines_and_says_so(self):
        rows = [
            packet(LAT, arrival_s=0.0, created=False),
            packet(LAT + JUMP, arrival_s=1.5, created=False),
        ]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is False
        assert verdict.time_base is None
        assert verdict.interval_note == "no_timestamps"

    def test_a_shared_arrival_timestamp_still_declines(self):
        rows = [packet(LAT, arrival_s=0.0), packet(LAT + JUMP, arrival_s=0.0)]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is False
        assert verdict.time_base == TIME_BASE_ARRIVAL

    def test_the_device_clock_rescues_a_shared_arrival_timestamp(self):
        # Same insert instant, but the device says 1.5 s passed: a rate exists.
        rows = [
            packet(LAT, arrival_s=0.0, sample_ms=0),
            packet(LAT + JUMP, arrival_s=0.0, sample_ms=1500),
        ]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is True
        assert verdict.time_base == TIME_BASE_DEVICE


class TestEvidenceRecordsTheTimeBase:
    """An analyst reading "5,560 m in 1.50 s" must know which 1.50 s that is."""

    def _spoof(self, *, device: bool):
        return [
            packet(LAT, arrival_s=0.0, sample_ms=0 if device else None),
            packet(LAT + JUMP, arrival_s=1.5, sample_ms=1500 if device else None),
        ]

    def test_device_clock(self):
        verdict = kinematic_guard.evaluate(self._spoof(device=True))
        detection = verdict.to_detection("D1")
        meta = detection["explanation"]["metadata"]
        assert meta["time_base"] == "device"
        assert meta["interval_s"] == pytest.approx(1.5, abs=1e-3)
        assert meta["interval_note"] is None
        assert detection["explanation"]["summary"]["Time Base"] == "device clock"
        implied = next(v for v in verdict.violations if v.check == "gps_implied_speed")
        assert "(device clock)" in implied.detail

    def test_arrival_time(self):
        verdict = kinematic_guard.evaluate(self._spoof(device=False))
        detection = verdict.to_detection("D1")
        assert detection["explanation"]["metadata"]["time_base"] == "arrival"
        assert detection["explanation"]["metadata"]["interval_note"] == "device_time_absent"
        assert detection["explanation"]["summary"]["Time Base"] == "server arrival time"
        implied = next(v for v in verdict.violations if v.check == "gps_implied_speed")
        assert "(server arrival time)" in implied.detail
