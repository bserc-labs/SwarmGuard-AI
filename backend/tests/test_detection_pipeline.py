"""Tests for the ingest -> inference -> incident wiring.

These cover the pure logic in the detection path. The DB-backed end of the
pipeline is exercised by the existing integration tests; what is asserted here
is the set of things that were silently wrong before: a threat level that could
not be stored, SHAP output that was fabricated, an attack label nothing matched,
and GPS features that had no live implementation at all.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from experimental.threat_service import threat_service
from models_ml.preprocess import FeatureEngineer, angle_difference, haversine_vectorized
from services.explanation_service import explanation_service
from services.incident_engine import _threat_level_ordinal
from services.recommendation_service import recommendation_service

V2_FEATURES = [
    "altitude",
    "yaw",
    "speed_change",
    "yaw_change",
    "time_delta",
    "vertical_speed",
    "gps_acceleration",
    "gps_speed_error_abs",
    "gps_speed_error_ratio",
]


def _window(spoof_at: int | None = None, n: int = 10) -> pd.DataFrame:
    """A nominal telemetry window, optionally with one spoofed position fix.

    The spoof holds reported speed constant while the position jumps, which is
    the signature the gps_speed_error_* features exist to catch.
    """
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    lat, lon = 34.0522, -118.2437
    rows = []
    for i in range(n):
        lat += 0.05 if i == spoof_at else 0.0002
        rows.append(
            dict(
                drone_id="D1",
                latitude=lat,
                longitude=lon,
                altitude=150.0 + i,
                speed=18.0,
                heading=(10.0 + i) % 360,
                battery=90.0 - i * 0.05,
                flight_mode="AUTO",
                armed_status=True,
                satellites=12,
                packet_sequence=i,
                created_at=t0 + timedelta(seconds=1.5 * i),
            )
        )
    return pd.DataFrame(rows)


class TestThreatLevelOrdinal:
    """The column is an Integer; the inference layer emits a band name."""

    @pytest.mark.parametrize(
        "band,expected",
        [("LOW", 1), ("MEDIUM", 2), ("HIGH", 3), ("CRITICAL", 4), ("critical", 4)],
    )
    def test_band_names_map_to_ranks(self, band, expected):
        assert _threat_level_ordinal(band) == expected

    def test_unknown_and_none_are_zero(self):
        # A failed inference reports UNKNOWN. It must not blow up the insert.
        assert _threat_level_ordinal("UNKNOWN") == 0
        assert _threat_level_ordinal(None) == 0

    def test_int_passes_through(self):
        assert _threat_level_ordinal(3) == 3

    def test_result_is_always_storable(self):
        # The regression: passing the raw string into an Integer column.
        for value in ["HIGH", "UNKNOWN", None, 2]:
            assert isinstance(_threat_level_ordinal(value), int)


class TestFeatureEngineering:
    def test_haversine_matches_known_distance(self):
        # One degree of latitude is ~111 km.
        d = haversine_vectorized(0.0, 0.0, 1.0, 0.0)
        assert 110_000 < float(d) < 112_000

    def test_angle_difference_wraps(self):
        # 359 -> 1 is +2 degrees, not -358.
        s = pd.Series([359.0, 1.0])
        assert float(angle_difference(s).iloc[1]) == pytest.approx(2.0)

    def test_v2_features_are_all_produced(self):
        eng = FeatureEngineer(feature_columns=V2_FEATURES)
        out = eng.transform(_window())
        for col in V2_FEATURES:
            assert col in out.columns

    def test_spoofed_fix_spikes_gps_error(self):
        eng = FeatureEngineer(feature_columns=V2_FEATURES)
        nominal = eng.transform(_window())["gps_speed_error_abs"]
        spoofed = eng.transform(_window(spoof_at=8))["gps_speed_error_abs"]

        # The spoofed row's GPS-derived speed diverges from reported speed by
        # orders of magnitude; the nominal window stays small.
        assert spoofed.iloc[8] > nominal.iloc[8] * 100

    def test_v1_features_still_produced(self):
        # The v1 family must keep working so MODEL_VERSION=v1 is still servable.
        v1 = ["speed_variance", "gps_drift", "altitude_deviation", "battery_discharge_rate"]
        out = FeatureEngineer(feature_columns=v1).transform(_window())
        for col in v1:
            assert col in out.columns

    def test_feature_columns_override_config(self):
        eng = FeatureEngineer(feature_columns=["altitude", "yaw"])
        assert eng.get_feature_columns() == ["altitude", "yaw"]


class TestShapHonesty:
    """The previous implementation returned a hardcoded triple on any failure."""

    def test_empty_history_returns_empty_not_placeholders(self):
        assert threat_service.compute_real_shap([]) == []
        assert threat_service.compute_real_shap(None) == []

    def test_no_fabricated_constants(self):
        # The old fallback: speed=0.48, altitude=0.32, battery_drain_rate=0.20.
        result = threat_service.compute_real_shap([])
        assert {"feature": "speed", "importance": 0.48} not in result

    def test_generate_alert_without_history_has_empty_attribution(self):
        alert = threat_service.generate_alert(
            is_anomaly=True, anomaly_score=0.9, attack_type="GPS_SPOOFING"
        )
        assert alert["shap_top3"] == []


class TestAttackClassification:
    def _feature(self, name, magnitude):
        return {"feature": name, "magnitude": magnitude}

    def test_gps_features_classify_as_spoofing(self):
        ranked = [
            self._feature("gps_speed_error_abs", 0.5),
            self._feature("gps_acceleration", 0.3),
            self._feature("altitude", 0.1),
        ]
        assert explanation_service._classify_attack_type(ranked) == "GPS_SPOOFING"

    def test_votes_across_top_three_not_just_first(self):
        # Two GPS features outweigh a single marginally-larger unrelated one.
        ranked = [
            self._feature("vertical_speed", 0.34),
            self._feature("gps_speed_error_abs", 0.33),
            self._feature("gps_acceleration", 0.33),
        ]
        assert explanation_service._classify_attack_type(ranked) == "GPS_SPOOFING"

    def test_unmapped_features_are_unclassified(self):
        assert explanation_service._classify_attack_type(
            [self._feature("mystery_column", 1.0)]
        ) == "UNCLASSIFIED_ANOMALY"


class TestRecommendations:
    def test_short_labels_resolve(self):
        # The old rules were keyed on prose and never matched an attack_type.
        for label in ["GPS_SPOOFING", "SIGNAL_JAMMING", "POWER_ANOMALY"]:
            rec = recommendation_service.generate_recommendation(label)
            assert rec != "Investigate telemetry logs manually."

    def test_title_cased_summary_key_is_read(self):
        # _generate_analyst_summary emits "Primary Cause", not "primary_cause".
        rec = recommendation_service.generate_recommendation(
            "SOMETHING_NEW", {"Primary Cause": "Abnormal GPS Drift"}
        )
        assert rec == "Verify GNSS integrity"

    def test_unknown_falls_back(self):
        assert (
            recommendation_service.generate_recommendation("NOPE", {})
            == "Investigate telemetry logs manually."
        )
