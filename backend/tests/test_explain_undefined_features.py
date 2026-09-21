"""The ML tier must refuse to score or explain a feature vector that does not exist.

Rate and delta features are NaN until there is something to difference against.
sklearn >= 1.4 and SHAP both accept NaN silently as a "missing value" and answer
anyway, so an undefined window used to come back as a confident verdict with a
ranked attribution -- an analyst shown "GPS_SPOOFING, 79%" computed from GPS
features that were never defined.

Two gaps compounded. `ai_service.predict` reported the undefined vector as
status "warmup" with no "error" key; `explain_prediction` only checked for
"error", recomputed the same NaN row, and handed it to SHAP. And on
/ai/explain the request field is `timestamp` while the feature engineer reads
`created_at`, so on that route *every* time-derived feature was NaN on *every*
call, not only during warm-up.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient

from main import app
from middleware.auth_middleware import TenantContext, get_tenant_context
from models_ml.preprocess import undefined_features
from services.ai_service import ai_service
from services.explanation_service import explanation_service

T0 = datetime(2026, 1, 1, 12, 0, 0)


def window(n: int = 10, step_s: float = 1.5, with_created_at: bool = True) -> list[dict]:
    rows = []
    lat = 34.0522
    for i in range(n):
        lat += 0.0002
        row = {
            "drone_id": "D1", "latitude": lat, "longitude": -118.2437, "altitude": 150.0 + i,
            "speed": 18.0, "heading": (10.0 + i) % 360, "battery": 90.0 - i * 0.05,
            "flight_mode": "AUTO", "armed_status": True, "satellites": 12, "packet_sequence": i,
        }
        if with_created_at:
            row["created_at"] = T0 + timedelta(seconds=step_s * i)
        rows.append(row)
    return rows


@pytest.fixture(scope="module", autouse=True)
def loaded_model():
    ai_service._lazy_load_model()
    if not ai_service.model or not ai_service.scaler:
        pytest.skip("no model artefacts loaded; nothing to guard")


class TestTheHelper:
    def test_it_names_the_undefined_columns(self):
        assert undefined_features(["a", "b", "c"], np.array([[1.0, np.nan, 3.0]])) == ["b"]
        assert undefined_features(["a", "b"], np.array([1.0, 2.0])) == []
        assert undefined_features(["a", "b"], [[None, 2.0]]) == ["a"]

    def test_a_length_mismatch_is_loud(self):
        with pytest.raises(ValueError):
            undefined_features(["a", "b"], np.array([[1.0]]))


class TestExplainRefusesAnUndefinedWindow:
    def test_a_two_packet_window(self):
        result = explanation_service.explain_prediction(window(n=2))
        assert result.get("status") == "insufficient_data"
        assert "error" in result, "detection_pipeline and the router both key on `error`"
        assert result["nan_features"], "the undefined columns must be named"
        assert "prediction" not in result and "explanation" not in result

    def test_a_window_with_no_timestamps_at_all(self):
        result = explanation_service.explain_prediction(window(n=10, with_created_at=False))
        assert result.get("status") == "insufficient_data"
        assert "prediction" not in result and "explanation" not in result

    def test_a_defined_window_is_still_explained(self):
        """The contract for valid input is unchanged."""
        result = explanation_service.explain_prediction(window(n=10))
        assert "error" not in result, result
        assert {"prediction", "explanation"} <= set(result)

    def test_predict_names_what_is_missing(self):
        result = ai_service.predict(window(n=2))
        assert result["status"] == "warmup"
        assert result["is_anomaly"] is False
        assert result["nan_features"]


class TestTheModelBoundary:
    """No caller, however it got there, may receive a verdict over NaN."""

    def test_score_refuses_nan(self):
        n = len(ai_service.engineer.get_feature_columns())
        with pytest.raises(ValueError, match="NaN"):
            ai_service._score(np.full((1, n), np.nan))

    def test_the_shap_engine_refuses_nan(self):
        explanation_service._lazy_load_engine()
        engine = explanation_service.engine
        result = engine.explain(np.full((1, len(engine.feature_names)), np.nan))
        assert "error" in result
        assert "explanations" not in result


class TestTheRoute:
    @pytest.fixture
    def client(self):
        previous = app.dependency_overrides.get(get_tenant_context)
        app.dependency_overrides[get_tenant_context] = lambda: TenantContext(
            user_id=1, username="pytest.analyst", organization_id=1, role="analyst"
        )
        try:
            yield TestClient(app)
        finally:
            if previous is None:
                app.dependency_overrides.pop(get_tenant_context, None)
            else:
                app.dependency_overrides[get_tenant_context] = previous

    def payload(self, n: int = 10, step_s: float = 1.5, stamp=None) -> dict:
        stamp = stamp or (lambda i: (T0 + timedelta(seconds=step_s * i)).isoformat())
        history = []
        for i, row in enumerate(window(n=n, with_created_at=False)):
            row.pop("armed_status")
            history.append({**row, "timestamp": stamp(i)})
        return {"telemetry_history": history}

    def test_a_valid_window_is_explained(self, client):
        """`timestamp` now reaches the feature engineer as `created_at`.

        Before the alias this request could not succeed honestly: every
        time-derived feature was NaN, and the 200 it returned was the defect.
        """
        res = client.post("/ai/explain", json=self.payload())
        assert res.status_code == 200, res.text
        assert {"prediction", "explanation"} <= set(res.json())

    def test_timestamps_that_do_not_advance_are_a_client_error(self, client):
        res = client.post("/ai/explain", json=self.payload(step_s=0.0))
        assert res.status_code == 400, res.text
        assert "Insufficient data" in res.json()["detail"]

    def test_mixed_aware_and_naive_timestamps_are_not_a_500(self, client):
        def stamp(i):
            moment = T0 + timedelta(seconds=1.5 * i)
            return moment.replace(tzinfo=UTC).isoformat() if i % 2 else moment.isoformat()

        res = client.post("/ai/explain", json=self.payload(stamp=stamp))
        assert res.status_code == 200, res.text

    def test_a_timestamp_that_is_not_a_date_is_rejected_at_the_door(self, client):
        res = client.post("/ai/explain", json=self.payload(stamp=lambda i: "yesterday-ish"))
        assert res.status_code == 422
