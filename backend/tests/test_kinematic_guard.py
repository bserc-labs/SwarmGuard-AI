"""Tests for the Tier 1 deterministic detector.

The property that matters most is the negative one: a physically valid flight
must never trip the guard. A false positive here grounds a healthy aircraft,
which is why the thresholds sit beyond the airframe's envelope rather than at
typical behaviour.
"""

import math
from datetime import datetime, timedelta

import pytest

from services.kinematic_guard import KinematicGuard, haversine_m, kinematic_guard

T0 = datetime(2026, 1, 1, 12, 0, 0)


def packet(seq, lat, lon, alt=150.0, speed=18.0, sats=12, dt=1.5):
    return {
        "drone_id": "D1",
        "latitude": lat,
        "longitude": lon,
        "altitude": alt,
        "speed": speed,
        "heading": 90.0,
        "battery": 90.0,
        "flight_mode": "AUTO",
        "armed_status": True,
        "satellites": sats,
        "packet_sequence": seq,
        "created_at": T0 + timedelta(seconds=dt * seq),
    }


def nominal(n=6):
    """A steady patrol: ~18 m/s, matching the reported speed."""
    rows = []
    lat = 34.0522
    for i in range(n):
        # 1.5 s at ~18 m/s ≈ 27 m ≈ 0.000243 degrees of latitude
        rows.append(packet(i, lat, -118.2437, alt=150.0 + i * 0.5))
        lat += 0.000243
    return rows


class TestHaversine:
    def test_one_degree_latitude(self):
        assert 110_000 < haversine_m(0, 0, 1, 0) < 112_000

    def test_zero_distance(self):
        assert haversine_m(34.0, -118.0, 34.0, -118.0) == pytest.approx(0.0, abs=1e-6)


class TestNoFalsePositives:
    """Valid flight must stay silent. This is the whole point of Tier 1."""

    def test_nominal_flight_does_not_trigger(self):
        assert kinematic_guard.evaluate(nominal()).triggered is False

    def test_steep_but_legal_climb_does_not_trigger(self):
        # 20 m/s climb, under the 25 m/s limit.
        rows = [packet(0, 34.0522, -118.2437, alt=100.0),
                packet(1, 34.0522, -118.2437, alt=130.0)]
        assert kinematic_guard.evaluate(rows).triggered is False

    def test_fast_but_legal_cruise_does_not_trigger(self):
        # ~50 m/s over 1.5 s = 75 m, with the airframe reporting the same.
        rows = [packet(0, 34.0522, -118.2437, speed=50.0),
                packet(1, 34.052874, -118.2437, speed=50.0)]
        assert kinematic_guard.evaluate(rows).triggered is False

    def test_single_packet_declines(self):
        assert kinematic_guard.evaluate([packet(0, 34.0522, -118.2437)]).triggered is False

    def test_empty_history_declines(self):
        assert kinematic_guard.evaluate([]).triggered is False

    def test_zero_interval_declines(self):
        # Two packets sharing a timestamp make every rate infinite. That is a
        # division artefact, not an attack.
        a = packet(0, 34.0522, -118.2437)
        b = packet(1, 34.10, -118.2437)
        b["created_at"] = a["created_at"]
        assert kinematic_guard.evaluate([a, b]).triggered is False


class TestSpoofDetection:
    def _spoofed(self):
        rows = nominal(4)
        last = rows[-1]
        # The simulator's injection: ~0.05 degrees latitude in one step.
        rows.append(packet(4, last["latitude"] + 0.05, last["longitude"]))
        return rows

    def test_position_jump_triggers(self):
        assert kinematic_guard.evaluate(self._spoofed()).triggered is True

    def test_classified_as_spoofing(self):
        assert kinematic_guard.evaluate(self._spoofed()).attack_type == "GPS_SPOOFING"

    def test_severity_is_critical(self):
        assert kinematic_guard.evaluate(self._spoofed()).severity == "CRITICAL"

    def test_reports_both_speed_violations(self):
        checks = {v.check for v in kinematic_guard.evaluate(self._spoofed()).violations}
        # The position jump is both beyond the airframe's limit and in
        # disagreement with the speed the airframe reports.
        assert "gps_implied_speed" in checks
        assert "gps_airframe_speed_mismatch" in checks

    def test_violation_arithmetic_is_checkable(self):
        v = kinematic_guard.evaluate(self._spoofed()).violations[0]
        # An analyst must be able to verify the number by hand: the structured
        # fields carry observed vs threshold, and the prose restates the
        # observed magnitude so the alert stands on its own in a log line.
        assert v.observed > v.threshold
        assert v.exceedance > 1.0
        assert v.unit == "m/s"
        assert f"{v.observed:,.0f}" in v.detail
        assert v.to_dict()["threshold"] == pytest.approx(v.threshold)

    def test_score_scales_with_severity(self):
        mild = nominal(3)
        mild.append(packet(3, mild[-1]["latitude"] + 0.002, mild[-1]["longitude"]))
        severe = self._spoofed()
        assert (
            kinematic_guard.evaluate(severe).threat_score
            >= kinematic_guard.evaluate(mild).threat_score
        )


class TestJammingDetection:
    def test_satellite_collapse_triggers(self):
        rows = [packet(0, 34.0522, -118.2437, sats=12),
                packet(1, 34.052443, -118.2437, sats=2)]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is True
        assert verdict.attack_type == "SIGNAL_JAMMING"

    def test_never_had_lock_does_not_trigger(self):
        # A drone that never had a fix is on the ground indoors, not jammed.
        rows = [packet(0, 34.0522, -118.2437, sats=2),
                packet(1, 34.052443, -118.2437, sats=1)]
        assert kinematic_guard.evaluate(rows).triggered is False

    def test_satellite_severity_runs_the_right_way(self):
        # For satellites, crossing *below* the threshold is the failure. The
        # exceedance ratio previously ran the wrong way (4/6 = 0.67), scoring a
        # real collapse as less severe than no failure at all.
        rows = [packet(0, 34.0522, -118.2437, sats=12),
                packet(1, 34.052443, -118.2437, sats=4)]
        v = kinematic_guard.evaluate(rows).violations[0]
        assert v.exceedance > 1.0

    def test_worse_collapse_scores_higher(self):
        def sat_exceedance(n):
            rows = [packet(0, 34.0522, -118.2437, sats=12),
                    packet(1, 34.052443, -118.2437, sats=n)]
            return kinematic_guard.evaluate(rows).violations[0].exceedance

        assert sat_exceedance(1) > sat_exceedance(4)

    def test_total_loss_is_finite(self):
        # Zero satellites must not produce a division error.
        rows = [packet(0, 34.0522, -118.2437, sats=12),
                packet(1, 34.052443, -118.2437, sats=0)]
        v = kinematic_guard.evaluate(rows).violations[0]
        assert math.isfinite(v.exceedance)
        assert v.exceedance > 1.0


class TestVerticalSpeed:
    def test_impossible_descent_triggers(self):
        rows = [packet(0, 34.0522, -118.2437, alt=200.0),
                packet(1, 34.052243, -118.2437, alt=0.0)]
        verdict = kinematic_guard.evaluate(rows)
        assert verdict.triggered is True
        assert any(v.check == "vertical_speed" for v in verdict.violations)


class TestDetectionShape:
    """The output must slot into IncidentEngine without special-casing."""

    def _verdict(self):
        rows = nominal(4)
        rows.append(packet(4, rows[-1]["latitude"] + 0.05, rows[-1]["longitude"]))
        return kinematic_guard.evaluate(rows)

    def test_has_prediction_and_explanation(self):
        d = self._verdict().to_detection("D1")
        assert d["drone_id"] == "D1"
        assert d["prediction"]["is_anomaly"] is True
        assert "ranked_features" in d["explanation"]
        assert "summary" in d["explanation"]

    def test_summary_carries_attack_type(self):
        d = self._verdict().to_detection("D1")
        assert d["explanation"]["summary"]["Attack Type"] == "GPS_SPOOFING"

    def test_ranked_features_have_magnitude(self):
        # IncidentEngine and the SHAP UI both sort on `magnitude`.
        for f in self._verdict().to_detection("D1")["explanation"]["ranked_features"]:
            assert "magnitude" in f and f["magnitude"] > 0

    def test_metadata_marks_it_deterministic(self):
        meta = self._verdict().to_detection("D1")["explanation"]["metadata"]
        assert meta["deterministic"] is True
        assert meta["detector"] == "kinematic_guard"
        assert meta["violations"]

    def test_violations_ranked_by_exceedance(self):
        violations = self._verdict().violations
        factors = [v.exceedance for v in violations]
        assert factors == sorted(factors, reverse=True)


class TestThresholdsAreConfigurable:
    def test_raising_limit_suppresses_detection(self):
        rows = [packet(0, 34.0522, -118.2437, speed=100.0),
                packet(1, 34.053549, -118.2437, speed=100.0)]
        assert kinematic_guard.evaluate(rows).triggered is True

        # A fixed-wing airframe with a higher envelope should not alert.
        guard = KinematicGuard()
        guard.max_speed_mps = 200.0
        guard.gps_speed_error_mps = 200.0
        assert guard.evaluate(rows).triggered is False
