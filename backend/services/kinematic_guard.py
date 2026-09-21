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
                },
                "metadata": {
                    "detector": "kinematic_guard",
                    "model_version": "physics-v1",
                    "feature_engineering_version": "physics-v1",
                    "deterministic": True,
                    "violations": [v.to_dict() for v in self.violations],
                    "explanation_confidence_percent": 100.0,
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

    def evaluate(self, history: list[dict[str, Any]]) -> GuardVerdict:
        """Check the most recent packet against its predecessor.

        Needs two packets: every check is a rate, and a rate needs an interval.
        """
        if len(history) < 2:
            return GuardVerdict(triggered=False)

        prev, curr = history[-2], history[-1]

        dt = self._interval_seconds(prev, curr)
        if dt is None or dt <= 0:
            # Two packets sharing a timestamp make every rate infinite. Decline
            # rather than report a division artefact as an attack.
            return GuardVerdict(triggered=False)

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
                        f"Position moved {distance:,.0f} m in {dt:.2f} s, implying "
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
                        f"GPS track implies {gps_speed:,.0f} m/s but the airframe reports "
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
                        f"Altitude changed {alt_change:,.1f} m in {dt:.2f} s "
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
            return GuardVerdict(triggered=False)

        # Rank by how far past the threshold, so the most egregious violation
        # leads the explanation.
        violations.sort(key=lambda v: v.exceedance, reverse=True)
        return GuardVerdict(
            triggered=True,
            attack_type=self._classify(violations),
            severity=self._severity(violations),
            threat_score=self._score(violations),
            violations=violations,
        )

    @staticmethod
    def _interval_seconds(prev: dict, curr: dict) -> float | None:
        prev_t, curr_t = prev.get("created_at"), curr.get("created_at")
        if prev_t is None or curr_t is None:
            return None
        try:
            return (curr_t - prev_t).total_seconds()
        except (TypeError, AttributeError):
            return None

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
