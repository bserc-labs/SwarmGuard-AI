"""The Detection screen's evidence contract.

The point of these is not that the endpoint returns 200. It is that the console
cannot quietly start claiming the ML tier is a detector: the numbers it serves
come from the recorded evaluation, and the decision to keep Tier 2 disabled is
tied to those numbers rather than to a flag someone can flip.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from config import get_settings
from models_ml.registry import model_registry
from routers.ai import _GUARD_CHECKS, get_detection_status
from services.kinematic_guard import kinematic_guard

settings = get_settings()


@pytest.fixture(scope="module")
def status():
    return get_detection_status()


@pytest.fixture(scope="module")
def tiers(status):
    return {t["tier"]: t for t in status["tiers"]}


class TestTierOne:
    def test_the_guard_is_the_authoritative_detector(self, tiers):
        guard = tiers[1]
        assert guard["deterministic"] is True
        assert guard["requires_training_data"] is False
        assert guard["raises_incidents"] is settings.GUARD_ENABLED

    def test_published_thresholds_match_the_running_guard(self, tiers):
        declared = {c["check"]: c["threshold"] for c in tiers[1]["checks"]}
        assert declared == {
            "gps_implied_speed": kinematic_guard.max_speed_mps,
            "gps_airframe_speed_mismatch": kinematic_guard.gps_speed_error_mps,
            "vertical_speed": kinematic_guard.max_climb_mps,
            "satellite_loss": float(kinematic_guard.min_satellites),
        }
        assert len(_GUARD_CHECKS) == len(declared)


class TestTierTwoStaysHonest:
    def test_the_headline_metric_is_leave_one_flight_out(self, tiers):
        assert tiers[2]["validation"]["protocol"] == "leave-one-flight-out"

    def test_the_leaky_split_is_labelled_as_contrast(self, tiers):
        contrast = tiers[2]["contrast"]
        assert contrast["protocol"] == "stratified row-level split"
        # The inflated number must never be presented as the result.
        assert contrast["f1_score"] > tiers[2]["validation"]["f1_score"]

    def test_tier_two_does_not_raise_incidents(self, tiers):
        assert tiers[2]["raises_incidents"] is False
        assert tiers[2]["disabled_reason"]

    def test_the_model_is_below_a_constant_classifier(self, tiers):
        """The decision rule, pinned.

        A classifier that always says "attack" scores F1 0.574 on this
        evaluation set and requires no model. Any measured F1 below that is not
        adding information, whatever the relative improvement over a previous
        run looks like. If a future model genuinely clears this, the assertion
        fails and someone has to make the enable/disable call deliberately.
        """
        investigations = tiers[2].get("investigations") or {}
        baseline = investigations["trivial_baselines"]["always_say_attack"]["f1_score"]
        measured = tiers[2]["validation"]["f1_score"]

        assert measured < baseline, (
            f"Tier 2 now scores F1 {measured} against a trivial baseline of "
            f"{baseline}. That is a decision point, not a passing test: review "
            "the false-positive rate and re-run diagnostics/17 before enabling."
        )

    def test_enabling_tier_two_requires_the_recorded_decision_to_agree(self, tiers):
        """The config flag and the recorded evidence must not contradict."""
        investigations = tiers[2].get("investigations") or {}
        recorded = investigations.get("decision", {}).get("tier_2_enabled")
        if recorded is not None:
            assert tiers[2]["enabled"] is recorded, (
                "AI_INCIDENTS_ENABLED disagrees with the decision recorded in "
                "investigations.json. Update the record, or turn the tier back off."
            )


class TestInvestigationRecord:
    def test_every_intervention_carries_a_verdict_and_a_reason(self, tiers):
        interventions = (tiers[2].get("investigations") or {}).get("interventions") or []
        assert interventions, "the record of what was tried must not be empty"
        for step in interventions:
            assert step["verdict"] in {"rejected", "invalid", "accepted"}
            assert step["reason"].strip(), f"{step['id']} has no stated reason"

    def test_per_flight_normalisation_was_measured_and_rejected(self, tiers):
        """The intervention the roadmap called for, with its outcome recorded."""
        interventions = (tiers[2].get("investigations") or {}).get("interventions") or []
        step = next(s for s in interventions if s["id"] == "per_flight_normalisation")

        assert step["verdict"] == "rejected"
        # It genuinely helped -- more than 3x -- which is exactly why the reason
        # for rejecting it has to be recorded rather than assumed obvious.
        assert step["lofo"]["f1_score"] > 0.2
        assert step["lofo"]["f1_score"] < 0.574

    def test_the_leaky_control_is_marked_invalid_not_rejected(self, tiers):
        interventions = (tiers[2].get("investigations") or {}).get("interventions") or []
        step = next(s for s in interventions if s["id"] == "per_flight_full_leaky")
        assert step["verdict"] == "invalid"
        assert step["lofo"]["precision"] == 1.0


def test_investigations_are_read_without_loading_the_model():
    """describe() must stay cheap enough for a status endpoint."""
    described = model_registry.describe(settings.MODEL_VERSION)
    assert described["artifact_status"] == "present"
    assert described["investigations"], "investigations.json should be present for v2"
