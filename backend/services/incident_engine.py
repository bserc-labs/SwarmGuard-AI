import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import Incident
from services.alert_service import (
    LIVE_INCIDENT_STATUSES,
    SEVERITY_RANK,
    alert_service,
    resolve_thresholds,
)
from services.priority_service import priority_service
from services.recommendation_service import recommendation_service

logger = logging.getLogger(__name__)

# Ordinal encoding for the Integer `threat_level` column. The inference layer
# speaks in band names, the schema stores a rank, and the dashboard sorts on it.
THREAT_LEVEL_ORDINALS = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _threat_level_ordinal(threat_level: Any) -> int:
    """Coerce a threat level to the Integer rank the column expects.

    Accepts the band name the inference service emits, an int that is already
    a rank, or None/UNKNOWN from a failed inference (which maps to 0).
    """
    if isinstance(threat_level, int):
        return threat_level
    if isinstance(threat_level, str):
        return THREAT_LEVEL_ORDINALS.get(threat_level.upper(), 0)
    return 0


def _serialize_incident_writes(db: Session, organization_id: int, drone_id: str) -> None:
    """Serialise check-then-insert per (organization, drone) for this transaction.

    Suppression is a SELECT followed by an INSERT, and detection runs one
    thread per ingested packet (detection_pipeline.run_detection), so two
    cycles for the same drone could both miss and both insert: one attack, two
    incidents on the operator's screen. A transaction-scoped advisory lock makes
    the second wait for the first to commit; under READ COMMITTED its
    suppression SELECT then sees the committed row.

    Released at commit or rollback, never explicitly. Keyed on
    (organization_id, hashtext(drone_id)) so tenants never share a key; a hash
    collision inside one tenant only serialises two unrelated drones. Nothing
    else in the codebase takes advisory locks; if that changes, keep this
    (int, int) convention or use the bigint form with a distinct prefix.

    A partial unique index was considered and rejected: the intended key is a
    60 s window per drone (commit 1d17747), not "one live incident per drone",
    and an index cannot express a sliding window.

    PostgreSQL only. The SQLite-backed unit suites run on one connection and
    have no concurrency to protect.
    """
    if db.get_bind().dialect.name != "postgresql":
        return
    db.execute(
        text("SELECT pg_advisory_xact_lock(:org, hashtext(:drone))"),
        {"org": organization_id, "drone": drone_id},
    ).scalar()


@dataclass(frozen=True)
class DetectionOutcome:
    """What a detection did to the incident table.

    `incident` is the row that was created or escalated, or None when the
    detection changed nothing an operator can see -- a repeat inside the
    suppression window that did not worsen the live incident.
    """

    incident: Incident | None
    created: bool

    @property
    def escalated(self) -> bool:
        """An existing incident got worse. Derived, so it cannot contradict `created`."""
        return self.incident is not None and not self.created


class IncidentEngine:
    """
    Orchestrates the conversion of AI anomaly detections into fully qualified Incidents.
    Delegates alerting, prioritization, and recommendations to decoupled sub-services.
    """
    
    @staticmethod
    def _merge_severity(detector_severity: Any, policy_severity: str) -> str:
        """The more serious of the detector's judgement and the org's policy.

        An unrecognised detector value is ignored rather than trusted, so a
        detector cannot invent a band the rest of the system does not rank.
        """
        if not isinstance(detector_severity, str):
            return policy_severity
        detector = detector_severity.upper()
        if detector not in SEVERITY_RANK:
            return policy_severity
        return detector if SEVERITY_RANK[detector] >= SEVERITY_RANK.get(policy_severity, 0) else policy_severity

    def process_ai_detection(
        self,
        db: Session,
        detection: dict[str, Any],
        mission_id: str | None = None,
        *,
        organization_id: int | None = None,
    ) -> Incident | None:
        """The newly created incident, or None. See `record_detection`.

        Kept for callers that only care whether a new row exists. It cannot
        report an escalation -- that returned None too, which is exactly how an
        incident climbing from MEDIUM to CRITICAL inside the suppression window
        never reached the operator's screen. The live pipeline uses
        `record_detection`.
        """
        outcome = self.record_detection(
            db, detection, mission_id, organization_id=organization_id
        )
        return outcome.incident if outcome.created else None

    def record_detection(
        self,
        db: Session,
        detection: dict[str, Any],
        mission_id: str | None = None,
        *,
        organization_id: int | None = None,
    ) -> DetectionOutcome:
        """
        Takes raw output from the Explainable AI layer and determines if a new
        Incident should be created or an existing one updated.

        `organization_id` is required for tenant isolation: without it the
        suppression check and repeat count read across every tenant's
        incidents, and the created row is invisible to the org that owns the
        drone. It is keyword-only so an existing positional caller cannot pass
        a mission_id into it by accident.
        """
        if organization_id is None:
            # Previously this wrote an incident with organization_id NULL, which
            # no tenant-scoped read could ever return -- a detection that fired,
            # was stored, and reached nobody. The column is NOT NULL as of
            # migration d4e5f6a7b8c9, so this would now surface as an
            # IntegrityError from the driver; raising here names the actual
            # mistake instead.
            raise ValueError(
                "organization_id is required to record an incident. A detection "
                "with no owning organization is invisible to every tenant."
            )

        drone_id = str(detection.get("drone_id") or "")
        # Extract inference outputs
        prediction = detection.get("prediction", {})
        explanation = detection.get("explanation", {})

        is_anomaly = prediction.get("is_anomaly", False)

        if not is_anomaly:
            # Nothing to do for normal telemetry, and no lock taken for it.
            return DetectionOutcome(incident=None, created=False)

        anomaly_score = prediction.get("anomaly_score", 0.0)
        # Using threat_level logic for basic mapping or passing threat_score
        # For simplicity we assume threat_score is same as anomaly_score internally for now if missing
        threat_score = prediction.get("threat_score", anomaly_score)

        # Short, filterable label ("GPS_SPOOFING") derived from the dominant
        # SHAP feature family. Falls back to the prose primary cause only when
        # the explanation layer could not classify it.
        summary = explanation.get("summary", {})
        attack_type = summary.get("Attack Type") or summary.get("Primary Cause", "Unknown Anomaly")

        incident_data = {
            "drone_id": drone_id,
            "attack_type": attack_type,
            "threat_score": threat_score
        }

        # Severity thresholds belong to the organization that owns the drone.
        # Resolved once and reused, so creation and escalation cannot classify
        # the same event against two different policies.
        thresholds = resolve_thresholds(db, organization_id)

        # From the suppression check to the commit is one critical section per
        # (organization, drone). See _serialize_incident_writes.
        _serialize_incident_writes(db, organization_id, drone_id)

        # 1. Alerting & Suppression
        alert = alert_service.process_alert(
            db, incident_data, organization_id=organization_id, thresholds=thresholds
        )
        if not alert:
            # Suppressed: fold this reading into the live incident. If that made
            # it worse -- a higher severity band, or a new label -- the caller
            # gets the row back so the change can be broadcast. It used to be
            # dropped here: the database escalated and the dashboard did not.
            escalated = self._update_existing_incident(
                db, drone_id, attack_type, threat_score,
                organization_id=organization_id,
                thresholds=thresholds,
                evidence=explanation,
            )
            return DetectionOutcome(incident=escalated, created=False)

        # Two severities, and the more serious one wins.
        #
        # `alert["severity"]` is policy: the organization's configured bands
        # applied to the threat score. `prediction["severity"]` is the
        # detector's own judgement, and it knows things the score does not --
        # the kinematic guard grades on how far past a physical limit a reading
        # was and how many independent checks failed, and a geofence breach
        # inherits the severity the operator declared on the zone itself.
        #
        # Taking the maximum means physics and operator policy act as a floor
        # that configuration cannot lower, while an organization that tightens
        # its thresholds does raise severity for every tier. Raising thresholds
        # cannot push a detector-declared severity down, which is the intended
        # asymmetry: configuration should not be able to silence a violated
        # no-fly zone.
        detector_severity = prediction.get("severity")
        severity = self._merge_severity(detector_severity, alert["severity"])

        # 2. Priority Calculation
        # Count repeat incidents for this drone
        repeat_query = db.query(Incident).filter(
            Incident.drone_id == drone_id,
            Incident.status.in_(["NEW", "OPEN"])
        )
        if organization_id is not None:
            repeat_query = repeat_query.filter(Incident.organization_id == organization_id)
        repeat_count = repeat_query.count()
        
        priority = priority_service.calculate_priority(
            threat_score=threat_score,
            anomaly_score=anomaly_score,
            repeat_incidents_count=repeat_count,
            mission_criticality=None # Will use default
        )
        
        # 3. Recommendations
        recommendation = recommendation_service.generate_recommendation(attack_type, summary)
        
        # 4. JSON Explanation format exactly as requested by user
        metadata = explanation.get("metadata", {})
        structured_json = {
            "primary_cause": summary.get("Primary Cause", ""),
            "secondary_cause": summary.get("Secondary Cause", ""),
            "supporting_indicators": summary.get("Supporting Indicators", "").split(", "),
            "recommended_action": recommendation,
            "model_version": metadata.get("model_version", "v1.0"),
            "explanation_strength": metadata.get("explanation_confidence_percent", 0.0),
            # Which policy produced the stored severity, so an analyst can tell
            # a detector-declared band from a configured one.
            "severity_source": (
                "detector" if severity == detector_severity else thresholds.source
            ),
        }
        
        # 5. Create Incident
        new_incident = Incident(
            drone_id=drone_id,
            organization_id=organization_id,
            mission_id=mission_id,
            attack_type=attack_type,
            threat_score=threat_score,
            anomaly_score=anomaly_score,
            # The inference service reports threat_level as a band name; the
            # column is an Integer. Passing the string straight through raised
            # a DataError on insert.
            threat_level=_threat_level_ordinal(prediction.get("threat_level")),
            severity=severity,
            priority=priority,
            shap_values=explanation.get("ranked_features", []),
            explanation=str(summary), # Deprecated flat string, keeping for schema compat
            explanation_summary=structured_json,
            recommended_action=recommendation,
            model_version=structured_json["model_version"],
            feature_version=metadata.get("feature_engineering_version", "v1.0"),
            status="NEW"
        )
        
        db.add(new_incident)
        db.commit()
        db.refresh(new_incident)
        
        logger.info(f"Generated new Incident #{new_incident.id} for Drone {drone_id} (Severity: {severity}, Priority: {priority})")
        return DetectionOutcome(incident=new_incident, created=True)

    def _update_existing_incident(
        self,
        db: Session,
        drone_id: str,
        attack_type: str,
        threat_score: float,
        *,
        organization_id: int | None = None,
        thresholds=None,
        evidence: dict[str, Any] | None = None,
    ) -> Incident | None:
        """
        Updates the threat score and updated_at timestamp of an ongoing incident
        to prevent duplicate spam while keeping the active incident fresh.

        Returns the incident when this reading escalated it -- its severity band
        rose or its label changed -- and None otherwise, so the caller can
        broadcast exactly the changes an operator needs to see.

        Known limitation: this picks the newest *live* incident for the drone
        with no time window, so a heartbeat-raised SIGNAL_LOSS_JAMMING incident
        (heartbeat_service creates those outside this engine) can be the row a
        later spoofing detection escalates and relabels. Now that escalations
        are broadcast, that relabel is operator-visible.

        `evidence` is the suppressed detection's explanation block. When the
        escalation also changes the incident's label, the attribution is
        replaced alongside it so the two cannot describe different events.

        Only an incident that is still live gets re-graded, and only when the
        new reading is worse. Incidents already resolved or closed are never
        touched, so changing an organization's thresholds does not rewrite
        history -- it changes how the next detection is classified.
        """
        if thresholds is None:
            thresholds = resolve_thresholds(db, organization_id)
        # Matches on drone, not attack_type, to mirror the suppression rule:
        # one ongoing event per drone, whose classification may change as the
        # attack's signature develops.
        query = db.query(Incident).filter(
            Incident.drone_id == drone_id,
            Incident.status.in_(LIVE_INCIDENT_STATUSES),
        )
        if organization_id is not None:
            query = query.filter(Incident.organization_id == organization_id)
        incident = query.order_by(Incident.created_at.desc()).first()

        if incident is None:
            return None

        previous_severity = incident.severity
        previous_attack_type = incident.attack_type

        if incident:
            # Escalate threat score if the new one is higher
            if threat_score > incident.threat_score:
                incident.threat_score = threat_score
                # The label follows the worst reading seen so far. A jamming
                # event that decays into a bare altitude violation should stay
                # filed as jamming, not be relabelled by its own aftermath.
                if attack_type and attack_type != incident.attack_type:
                    incident.attack_type = attack_type
                    # Relabelling without re-evidencing leaves a record whose
                    # attack_type and attribution disagree -- an incident headed
                    # GPS_SPOOFING while its stored evidence is a geofence
                    # breach, because the first detector to fire wrote the
                    # evidence and a later one overwrote only the label. That
                    # was invisible while one detector could raise incidents and
                    # became reachable as soon as a second could.
                    if evidence is not None:
                        incident.shap_values = evidence.get("ranked_features") or []
                        summary = evidence.get("summary") or {}
                        if summary:
                            incident.explanation = str(summary)
                # Re-evaluate severity against this organization's bands, and
                # never downgrade: the incident already reached the higher
                # severity, and an ongoing event getting quieter on paper while
                # it is still open would misrepresent it.
                incident.severity = self._merge_severity(
                    incident.severity,
                    alert_service.generate_alert_severity(threat_score, thresholds),
                )
                # Re-evaluate priority
                incident.priority = priority_service.calculate_priority(incident.threat_score, incident.anomaly_score, 1)

            incident.updated_at = datetime.utcnow()

        # Decided before the commit: SessionLocal expires attributes on commit,
        # so reading them afterwards would cost a reload per comparison.
        escalated = (
            SEVERITY_RANK.get(incident.severity or "", 0)
            > SEVERITY_RANK.get(previous_severity or "", 0)
            or incident.attack_type != previous_attack_type
        )
        db.commit()  # also releases the per-drone advisory lock

        if not escalated:
            return None
        db.refresh(incident)
        logger.info(
            f"Escalated Incident #{incident.id} for Drone {drone_id}: "
            f"{previous_severity} {previous_attack_type} -> "
            f"{incident.severity} {incident.attack_type}"
        )
        return incident


incident_engine = IncidentEngine()
