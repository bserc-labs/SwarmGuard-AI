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

from datetime import UTC, datetime, timedelta

import pytest

from services.kinematic_guard import (
    NOTE_ARRIVAL_UNUSABLE,
    NOTE_REORDERED,
    TIME_BASE_ARRIVAL,
    TIME_BASE_DEVICE,
    KinematicGuard,
    kinematic_guard,
)

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
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

    def test_a_repeated_device_clock_uses_arrival(self):
        # A stalled clock gives no interval at all. (A clock that steps back a
        # little is a late packet, not a reset: see TestDeliveredOutOfOrder.)
        rows = [
            packet(LAT, arrival_s=0.0, sample_ms=1500),
            packet(LAT + NOMINAL_STEP, arrival_s=1.5, sample_ms=1500),
        ]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is False
        assert verdict.time_base == TIME_BASE_ARRIVAL
        assert verdict.interval_note == "device_clock_not_monotonic"
        assert verdict.interval_s == pytest.approx(1.5)

    def test_a_reboot_is_not_mistaken_for_a_late_packet(self):
        # A whole window from before the reboot: the new clock is ten minutes
        # behind all of it, far past any reorder.
        rows = [
            packet(LAT, arrival_s=0.0, sample_ms=599_800),
            packet(LAT, arrival_s=0.1, sample_ms=599_900),
            packet(LAT, arrival_s=0.2, sample_ms=600_000),
            packet(LAT, arrival_s=45.0, sample_ms=500),
        ]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.time_base == TIME_BASE_ARRIVAL
        assert verdict.interval_note == "device_clock_not_monotonic"
        assert verdict.interval_s == pytest.approx(44.8)

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


LOAD_SPEED = 15.0  # m/s, the load test's fleet
DEG_PER_M = 1 / 111_320  # latitude degrees per metre


def flown(seconds):
    """Latitude after `seconds` of straight flight at LOAD_SPEED."""
    return LAT + LOAD_SPEED * seconds * DEG_PER_M


def load_packet(sample_s, *, arrival_s, lat=None):
    return packet(
        flown(sample_s) if lat is None else lat,
        arrival_s=arrival_s,
        sample_ms=round(sample_s * 1000),
        speed=LOAD_SPEED,
    )


def as_before(rows):
    """What the guard did before it looked past the packet stored last: rate
    the last two stored packets, read any backwards clock as a reset, and divide
    by arrival time however close together the packets arrived."""
    old = KinematicGuard()
    old.device_clock_max_reorder_s = 0.0
    old.min_reset_gap_s = 0.0
    return old.evaluate(rows[-2:])


class TestDeliveredOutOfOrder:
    """Packets stored out of sample order, as an overloaded server stores them.

    Each case is a shape from the 2026-09-22 load test, where the guard filed
    200 false GPS_SPOOFING incidents against drones flying clean 15 m/s
    circles (reports/06-LOAD-TEST-RESULTS.md). Each fired on the old guard and
    is rated on the device clock now; a real jump in the same shape still
    fires.
    """

    def test_neighbouring_packets_swapped(self):
        # Sampled 0.0, 0.1, 0.2 s; the 0.1 s packet is stored last, 10 ms
        # after the 0.2 s one. Old: 1.5 m in 0.01 s = 150 m/s.
        rows = [
            load_packet(0.0, arrival_s=0.00),
            load_packet(0.2, arrival_s=0.01),
            load_packet(0.1, arrival_s=0.02),
        ]
        old = as_before(rows)
        assert old.triggered is True
        assert old.attack_type == "GPS_SPOOFING"
        assert old.time_base == TIME_BASE_ARRIVAL

        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is False
        assert verdict.time_base == TIME_BASE_DEVICE
        assert verdict.interval_s == pytest.approx(0.1)
        assert verdict.interval_note == NOTE_REORDERED

    def test_a_straggler_stored_just_before(self):
        # The packet stored before the newest was sampled 15 s earlier and sat
        # in a queue. Old: its 15 s device interval outran the 0.9 s arrival
        # gap by more than the 10 s bound, so 225 m / 0.9 s = 250 m/s.
        rows = [
            load_packet(18.9, arrival_s=19.0),
            load_packet(19.0, arrival_s=19.1),
            load_packet(5.0, arrival_s=30.0),
            load_packet(20.0, arrival_s=30.9),
        ]
        old = as_before(rows)
        assert old.triggered is True
        assert old.interval_note == "device_interval_exceeds_arrival"

        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is False
        assert verdict.time_base == TIME_BASE_DEVICE
        assert verdict.interval_s == pytest.approx(1.0)
        assert verdict.interval_note == NOTE_REORDERED

    def test_a_packet_late_past_the_whole_window(self):
        # Sampled a second before anything else in the window, stored last.
        # No predecessor to compare with, so it meets the sample after it.
        rows = [
            load_packet(10.0, arrival_s=0.00),
            load_packet(10.1, arrival_s=0.01),
            load_packet(9.0, arrival_s=0.02),
        ]
        assert as_before(rows).triggered is True

        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is False
        assert verdict.time_base == TIME_BASE_DEVICE
        assert verdict.interval_s == pytest.approx(1.0)
        assert verdict.interval_note == NOTE_REORDERED

    def test_the_reorder_bound_is_what_separates_late_from_reset(self):
        # 15 s behind the window, and 5 s between the two packets arriving --
        # long enough to contain a reboot. Past the 10 s bound, so a reset.
        rows = [
            load_packet(20.0, arrival_s=0.0),
            load_packet(5.0, arrival_s=5.0),
        ]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.time_base == TIME_BASE_ARRIVAL
        assert verdict.interval_note == "device_clock_not_monotonic"

        lenient = KinematicGuard()
        lenient.device_clock_max_reorder_s = 20.0
        relaxed = lenient.evaluate(rows)
        assert relaxed.time_base == TIME_BASE_DEVICE
        assert relaxed.interval_s == pytest.approx(15.0)
        assert relaxed.triggered is False

    @pytest.mark.parametrize(
        "rows",
        [
            [
                load_packet(0.0, arrival_s=0.00),
                load_packet(0.2, arrival_s=0.01),
                load_packet(0.1, arrival_s=0.02, lat=LAT + JUMP),
            ],
            [
                load_packet(10.0, arrival_s=0.00),
                load_packet(10.1, arrival_s=0.01),
                load_packet(9.0, arrival_s=0.02, lat=LAT + JUMP),
            ],
        ],
        ids=["late-with-predecessor", "late-past-the-window"],
    )
    def test_a_late_packet_carrying_a_real_jump_still_fires(self, rows):
        # 5.5 km from its real neighbour: arriving late does not launder it.
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is True
        assert verdict.attack_type == "GPS_SPOOFING"
        assert verdict.time_base == TIME_BASE_DEVICE
        assert verdict.interval_note == NOTE_REORDERED

    def test_in_order_delivery_is_unchanged(self):
        rows = [load_packet(s / 10, arrival_s=s / 10) for s in range(5)]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is False
        assert verdict.time_base == TIME_BASE_DEVICE
        assert verdict.interval_s == pytest.approx(0.1)
        assert verdict.interval_note is None

    def test_the_evidence_says_the_pair_was_reordered(self):
        rows = [
            load_packet(0.0, arrival_s=0.00),
            load_packet(0.2, arrival_s=0.01),
            load_packet(0.1, arrival_s=0.02, lat=LAT + JUMP),
        ]
        detection = kinematic_guard.evaluate(rows).to_detection("D1")
        meta = detection["explanation"]["metadata"]
        assert meta["time_base"] == "device"
        assert meta["interval_note"] == NOTE_REORDERED
        assert detection["explanation"]["summary"]["Time Base"] == "device clock"


class TestAPacketTooLateToRate:
    """A packet delivered long after it was sampled gets no verdict, not a spoof.

    Falling back to arrival time assumes the two packets arrived far enough
    apart for that spacing to mean something. A late packet arrives in the same
    breath as the packets that overtook it. Measured against this code: one
    packet in ten held back 60 s produced **40 false CRITICAL spoof alerts**
    against drones flying clean circles, every one of them rated on arrival
    time after the device clock appeared to step back.
    """

    def _overtaken(self, lat=None, arrival_gap=0.01):
        # Sampled 60 s ago, delivered now: older than everything in the window,
        # so no neighbour on the device clock either side of it.
        rows = [load_packet(60.0 + s / 10, arrival_s=s / 100) for s in range(5)]
        rows.append(load_packet(0.0, arrival_s=0.04 + arrival_gap, lat=lat))
        return rows

    def test_a_late_packet_gets_no_verdict_instead_of_a_spoof(self):
        rows = self._overtaken()
        # What this code did before: divide 900 m of real flight by 10 ms.
        credulous = KinematicGuard()
        credulous.min_reset_gap_s = 0.0
        fired = credulous.evaluate(rows)
        assert fired.triggered is True
        assert fired.attack_type == "GPS_SPOOFING"
        assert fired.time_base == TIME_BASE_ARRIVAL

        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is False
        assert verdict.time_base is None
        assert verdict.interval_s is None
        assert verdict.interval_note == NOTE_ARRIVAL_UNUSABLE

    def test_a_reset_takes_time_and_still_uses_arrival(self):
        # 45 s between the last packet before the reboot and the first after it:
        # long enough to contain a reboot, so arrival time is still the fallback.
        rows = [
            packet(LAT, arrival_s=0.0, sample_ms=599_800),
            packet(LAT, arrival_s=0.1, sample_ms=599_900),
            packet(LAT, arrival_s=0.2, sample_ms=600_000),
            packet(LAT, arrival_s=45.0, sample_ms=500),
        ]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.time_base == TIME_BASE_ARRIVAL
        assert verdict.interval_note == "device_clock_not_monotonic"
        assert verdict.interval_s == pytest.approx(44.8)

    def test_a_usable_device_clock_still_fires_however_late_the_window_is(self):
        # This does not disarm the detector. The device clock is what it rates
        # on, and being delivered late does not change what the device sampled.
        rows = [load_packet(s / 10, arrival_s=s / 100) for s in range(5)]
        rows.append(load_packet(0.5, arrival_s=0.05, lat=LAT + JUMP))
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is True
        assert verdict.attack_type == "GPS_SPOOFING"
        assert verdict.time_base == TIME_BASE_DEVICE

    def test_a_mis_scaled_clock_is_still_caught(self):
        # The other reason to disbelieve the device clock: it claims 1000 s
        # between packets that arrived 1.5 s apart. That gap is long enough to
        # be meaningful, so arrival time still stands in and the jump fires.
        rows = [
            packet(LAT, arrival_s=0.0, sample_ms=0),
            packet(LAT + JUMP, arrival_s=1.5, sample_ms=1_000_000),
        ]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is True
        assert verdict.time_base == TIME_BASE_ARRIVAL

    def test_declining_is_counted_so_a_degraded_detector_is_visible(self, monkeypatch):
        # A guard that has gone quiet under load must not look like a quiet sky.
        from services import detection_pipeline
        from utils.metrics import GUARD_DECLINED

        monkeypatch.setattr(detection_pipeline.geofence_engine, "evaluate", lambda *a, **k: None)
        before = GUARD_DECLINED.labels(NOTE_ARRIVAL_UNUSABLE)._value.get()
        detection = detection_pipeline._run_detectors(
            "D1", self._overtaken(LAT + JUMP), db=None, organization_id=1
        )
        assert detection is None, "a packet too late to rate must not produce a detection"
        assert GUARD_DECLINED.labels(NOTE_ARRIVAL_UNUSABLE)._value.get() == before + 1

    def test_the_bound_is_a_setting(self):
        # Widen what counts as long enough for a reset and the same rows are
        # rated on arrival time again.
        rows = self._overtaken(arrival_gap=2.0)
        assert kinematic_guard.evaluate(rows).time_base == TIME_BASE_ARRIVAL

        strict = KinematicGuard()
        strict.min_reset_gap_s = 5.0
        assert strict.evaluate(rows).interval_note == NOTE_ARRIVAL_UNUSABLE


class TestALateClockIsNotAReset:
    """A reset restarts the clock, so it cannot show more uptime than has passed.

    Found by the load test of 2026-09-24. Fresh traffic stopped, the backlog
    kept draining, and each drone's first late packet arrived ~4 s after the
    one before -- long enough for a reboot, by the gap alone. Its clock read a
    minute of uptime. Rated on arrival time: 590 m in 4.4 s, and 40 false
    GPS_SPOOFING incidents, one per drone.
    """

    def _drained(self, *, late_sample_s, gap_s, lat=None):
        # Fresh packets up to 120 s of flight, then one sampled `late_sample_s`
        # into the flight arriving `gap_s` after the last of them.
        rows = [load_packet(119.0 + s / 10, arrival_s=s / 10) for s in range(10)]
        rows.append(load_packet(late_sample_s, arrival_s=0.9 + gap_s, lat=lat))
        return rows

    def test_a_minute_of_uptime_four_seconds_after_the_last_packet_is_late(self):
        rows = self._drained(late_sample_s=60.0, gap_s=4.4)
        # What the guard did before: a reset, rated on arrival, a false spoof.
        credulous = KinematicGuard()
        credulous.device_clock_max_lead_s = 1e9
        assert credulous.evaluate(rows).triggered is True

        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is False
        assert verdict.time_base is None
        assert verdict.interval_note == NOTE_ARRIVAL_UNUSABLE

    def test_a_clock_that_restarted_in_the_gap_is_still_a_reset(self):
        # Two seconds of uptime, four seconds after the last packet: it could
        # have rebooted, so arrival time stands in as it always has.
        verdict = kinematic_guard.evaluate(self._drained(late_sample_s=2.0, gap_s=4.4))
        assert verdict.time_base == TIME_BASE_ARRIVAL
        assert verdict.interval_note == "device_clock_not_monotonic"

    def test_a_long_gap_can_contain_a_long_uptime(self):
        # Ninety seconds of silence can hold a reboot and 60 s of flight.
        verdict = kinematic_guard.evaluate(self._drained(late_sample_s=60.0, gap_s=90.0))
        assert verdict.time_base == TIME_BASE_ARRIVAL

    def test_the_slack_is_the_lead_setting(self):
        # 20 s of uptime is more than 4.4 s plus the default 10 s of slack...
        rows = self._drained(late_sample_s=20.0, gap_s=4.4)
        assert kinematic_guard.evaluate(rows).time_base is None
        # ...and within 4.4 s plus 20.
        lenient = KinematicGuard()
        lenient.device_clock_max_lead_s = 20.0
        assert lenient.evaluate(rows).time_base == TIME_BASE_ARRIVAL

    def test_a_stalled_clock_is_not_read_as_late(self):
        # A clock that repeats did not step back; it is broken, and arrival
        # time stands in as before rather than silencing the detector.
        rows = [
            packet(LAT, arrival_s=0.0, sample_ms=600_000),
            packet(LAT + JUMP, arrival_s=1.5, sample_ms=600_000),
        ]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.time_base == TIME_BASE_ARRIVAL
        assert verdict.triggered is True

    def test_ingest_asks_the_same_question(self):
        assert kinematic_guard.could_have_reset(2_000, 4.4) is True
        assert kinematic_guard.could_have_reset(60_000, 4.4) is False


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
