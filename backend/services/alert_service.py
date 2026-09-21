import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from config import get_settings
from models import Incident, SystemSettings

logger = logging.getLogger(__name__)
settings = get_settings()

# Severity bands, ordered. Used to compare two severities without a lookup at
# every call site.
SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

# Statuses in which an incident is still the operator's live concern: every
# lifecycle state before RESOLVED (routers/incidents.py LIFECYCLE; a test pins
# the two together). Suppression and escalation consult only these. An incident
# an operator has resolved or closed is history; a detection that follows it is
# a new event and must be recorded and broadcast, not folded into a record
# nobody is watching.
#
# A row whose status is NULL is not live by this definition. The ORM always
# writes "NEW"; only a row inserted outside it could be NULL, and making that
# count would need a NOT NULL + server_default migration rather than a filter.
LIVE_INCIDENT_STATUSES: tuple[str, ...] = (
    "NEW",
    "OPEN",
    "ACKNOWLEDGED",
    "INVESTIGATING",
    "CONTAINED",
)

# Defaults, as fractions of a 0-100 threat score. These are the values the
# severity mapping used to hardcode; they are now only the fallback for an
# organization that has not set its own.
DEFAULT_CRITICAL_THRESHOLD = 0.85
DEFAULT_HIGH_THRESHOLD = 0.60

# The MEDIUM floor is not operator-configurable: SystemSettings carries only the
# critical and high thresholds, and the Settings screen exposes only those two.
# Inventing a third control here that no one can see or change would be worse
# than a documented constant.
MEDIUM_FLOOR_SCORE = 40.0


@dataclass(frozen=True)
class SeverityThresholds:
    """Score floors, on the same 0-100 scale as `threat_score`.

    SystemSettings stores fractions in [0, 1] -- which is what the Settings
    screen's number inputs enforce, min 0 / max 1 / step 0.01 -- while every
    threat score in the system is 0-100. Converting once, here, keeps that
    mismatch from being re-derived (and eventually mis-derived) at each caller.
    """

    critical: float
    high: float
    source: str  # "organization" or "default", recorded on the incident

    @classmethod
    def defaults(cls) -> "SeverityThresholds":
        return cls(
            critical=DEFAULT_CRITICAL_THRESHOLD * 100.0,
            high=DEFAULT_HIGH_THRESHOLD * 100.0,
            source="default",
        )


def resolve_thresholds(db: Session, organization_id: int | None) -> SeverityThresholds:
    """Read one organization's severity thresholds, or the defaults.

    Read-only on purpose. `settings_router.get_or_create_settings` INSERTs a row
    on a miss, which is right for a request an operator made and wrong for a
    detection running in a background thread: several packets for a new
    organization would race to create the same row.

    An organization that has never opened the Settings screen therefore gets the
    defaults without a write, and its first save creates the row through the
    normal route.
    """
    if organization_id is None:
        return SeverityThresholds.defaults()

    row = (
        db.query(SystemSettings)
        .filter(SystemSettings.organization_id == organization_id)
        .first()
    )
    if row is None:
        return SeverityThresholds.defaults()

    critical = row.critical_threshold
    high = row.high_threshold

    # A row written before validation existed, or edited directly in the
    # database, can hold values that make the bands meaningless. Fall back
    # rather than classify against a nonsensical ordering.
    if (
        critical is None
        or high is None
        or not (0.0 < high < critical <= 1.0)
    ):
        logger.warning(
            f"Organization {organization_id} has unusable severity thresholds "
            f"(high={high}, critical={critical}); using defaults."
        )
        return SeverityThresholds.defaults()

    return SeverityThresholds(
        critical=critical * 100.0, high=high * 100.0, source="organization"
    )


class AlertService:
    def __init__(self):
        # Time window to suppress duplicate alerts for the same drone
        self.suppression_window_seconds = 60

    def generate_alert_severity(
        self,
        threat_score: float,
        thresholds: SeverityThresholds | None = None,
    ) -> str:
        """Classify a 0-100 threat score into a severity band.

        `thresholds` comes from the incident's own organization. It is optional
        so that callers with no session -- and the existing tests -- still get
        the documented defaults rather than a required argument they cannot
        supply.
        """
        bands = thresholds or SeverityThresholds.defaults()

        if threat_score >= bands.critical:
            return "CRITICAL"
        if threat_score >= bands.high:
            return "HIGH"
        if threat_score >= MEDIUM_FLOOR_SCORE:
            return "MEDIUM"
        return "LOW"

    def is_alert_suppressed(
        self,
        db: Session,
        drone_id: str,
        attack_type: str,
        *,
        organization_id: int | None = None,
    ) -> bool:
        """
        Determines if an alert should be suppressed because a similar alert
        was recently generated for this drone.

        Scoped by tenant: unscoped, one organization's recent incident would
        suppress a genuine alert for another organization that happens to use
        the same drone_id.
        """
        cutoff_time = datetime.utcnow() - timedelta(seconds=self.suppression_window_seconds)

        # Deliberately NOT filtered by attack_type. A single ongoing event
        # changes its own signature as it develops: a jamming attack first
        # shows a satellite-count collapse plus an altitude drop, and a moment
        # later -- satellites already low, so no further transition -- only the
        # altitude drop remains, which classifies as FLIGHT_INSTABILITY. Keyed
        # on attack_type, suppression let that second reading through and one
        # attack became two unrelated incidents on the operator's screen.
        #
        # Within the window, one drone means one incident. `attack_type` is
        # escalated on the existing row instead (see
        # IncidentEngine._update_existing_incident).
        #
        # Only live incidents count. Before this filter a RESOLVED row inside
        # the window suppressed the next detection: an operator who resolved an
        # incident while the attack was still running got nothing written and
        # nothing broadcast for the next 60 s.
        #
        # This check is not atomic with the insert that follows it.
        # IncidentEngine serialises the two with a per-drone advisory lock
        # (_serialize_incident_writes); do not call this standalone expecting
        # it to be race-free.
        query = db.query(Incident).filter(
            Incident.drone_id == drone_id,
            Incident.status.in_(LIVE_INCIDENT_STATUSES),
            Incident.detection_time >= cutoff_time,
        )
        if organization_id is not None:
            query = query.filter(Incident.organization_id == organization_id)

        return query.first() is not None

    def process_alert(
        self,
        db: Session,
        incident_data: dict[str, Any],
        *,
        organization_id: int | None = None,
        thresholds: SeverityThresholds | None = None,
    ) -> dict[str, Any] | None:
        """
        Processes a raw detection, determines severity, checks suppression,
        and returns a structured alert object if it should be propagated.

        `thresholds` is resolved by the caller so a single detection does not
        read the settings row twice -- once here and once when escalating.
        """
        drone_id = str(incident_data.get("drone_id") or "")
        attack_type = incident_data.get("attack_type", "Unknown")
        threat_score = incident_data.get("threat_score", 0.0)

        severity = self.generate_alert_severity(threat_score, thresholds)

        if self.is_alert_suppressed(
            db, drone_id, attack_type, organization_id=organization_id
        ):
            logger.info(f"Alert suppressed for {drone_id} (Type: {attack_type}) due to suppression window.")
            return None
            
        return {
            "drone_id": drone_id,
            "attack_type": attack_type,
            "severity": severity,
            "threat_score": threat_score,
            "message": f"[{severity}] {attack_type} detected on {drone_id} (Score: {threat_score:.2f})",
            "timestamp": datetime.utcnow().isoformat()
        }

alert_service = AlertService()
