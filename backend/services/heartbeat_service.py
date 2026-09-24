from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

import models
from services.incident_engine import incident_engine
from utils.logger import logger
from utils.metrics import INCIDENTS

SILENCE_THRESHOLD_SECONDS = 30

ATTACK_TYPE = "SIGNAL_LOSS_JAMMING"


def _detection(drone: models.Drone, silent_for: float) -> dict[str, Any]:
    """The silence, shaped as a detection the incident engine can record.

    Same shape the kinematic guard and the geofence produce, so one path
    decides create, escalate or suppress for every detector.
    """
    reason = (
        f"Drone '{drone.drone_id}' has not reported for more than "
        f"{SILENCE_THRESHOLD_SECONDS} seconds. Possible RF jamming or loss of "
        "communication."
    )
    return {
        "drone_id": drone.drone_id,
        "prediction": {
            "is_anomaly": True,
            "anomaly_score": 0.95,
            "threat_score": 90.0,
            "threat_level": "CRITICAL",
            "severity": "CRITICAL",
        },
        "explanation": {
            "ranked_features": [
                {
                    "feature": "signal_loss_duration",
                    "shap_value": 0.95,
                    "magnitude": 0.95,
                    "observed": round(silent_for, 1),
                    "threshold": float(SILENCE_THRESHOLD_SECONDS),
                    "unit": "seconds",
                }
            ],
            "summary": {
                "Attack Type": ATTACK_TYPE,
                "Primary Cause": reason,
                "Secondary Cause": "None",
                "Supporting Indicators": "None",
                "Detector": "heartbeat",
            },
            "metadata": {
                "detector": "heartbeat",
                "model_version": "heartbeat-v1",
                "feature_engineering_version": "heartbeat-v1",
                "deterministic": True,
                "silent_for_s": round(silent_for, 1),
                "threshold_s": SILENCE_THRESHOLD_SECONDS,
            },
        },
    }


def check_drone_heartbeats(db: Session) -> list[tuple[int, dict]]:
    """
    Mark drones silent past the threshold and record an incident for each.

    Returns (organization_id, alert_payload) pairs for the caller to broadcast.
    This function does NOT broadcast itself: it runs synchronously inside
    asyncio.to_thread, and the previous implementation called asyncio.run() here
    — creating a second event loop in the worker thread and writing to sockets
    owned by the main loop. The failure was caught and logged, so the alerts this
    system generates almost certainly never reached a browser.

    The incident goes through `incident_engine`, like every other detector's.
    It used to build an `Incident` row here and commit it directly, which meant
    a silence was the one event in the system that skipped suppression, the
    per-drone advisory lock, the organization's severity thresholds and the
    recommended action — so a drone that flickered in and out filed a second
    CRITICAL incident where any other detector would have escalated the first,
    and the row an analyst opened had no recommendation in it.
    """
    now = datetime.now(UTC)
    cutoff_time = now - timedelta(seconds=SILENCE_THRESHOLD_SECONDS)

    silent_drones = (
        db.query(models.Drone)
        .filter(
            models.Drone.status.in_(["ACTIVE", "SAFE_MODE"]),
            models.Drone.last_seen < cutoff_time,
        )
        .all()
    )

    alerts: list[tuple[int, dict]] = []

    for drone in silent_drones:
        drone.status = "SILENT_POSSIBLE_JAMMING"
        logger.warning(
            f"Heartbeat alert: drone '{drone.drone_id}' silent since {drone.last_seen}"
        )

        # No orgless branch: drones.organization_id is NOT NULL, so every drone
        # has an owner to scope the incident and the broadcast to. This used to
        # write incidents with a NULL organization, which no tenant-scoped read
        # could return -- alerts that fired and reached nobody.
        silent_for = (now - drone.last_seen).total_seconds() if drone.last_seen else 0.0
        outcome = incident_engine.record_detection(
            db, _detection(drone, silent_for), organization_id=drone.organization_id
        )
        incident = outcome.incident
        if incident is None:
            # A live incident already covers this silence and this reading did
            # not make it worse.
            continue

        if outcome.created:
            INCIDENTS.labels("heartbeat", incident.severity, ATTACK_TYPE).inc()

        alerts.append(
            (
                drone.organization_id,
                {
                    "type": "incident",
                    # Same frames the detection pipeline sends, so a client keyed
                    # on the incident updates in place instead of stacking a
                    # second banner for the same silent drone.
                    "event_type": "SILENT_DRONE_ALERT" if outcome.created else "INCIDENT_ESCALATED",
                    "is_anomaly": True,
                    "drone_id": incident.drone_id,
                    "attack_type": incident.attack_type,
                    "severity": incident.severity,
                    "anomaly_score": incident.anomaly_score,
                    "threat_level": incident.threat_level,
                    "shap_top3": [
                        {"feature": f.get("feature"), "importance": abs(f.get("shap_value", 0.0))}
                        for f in (incident.shap_values or [])[:3]
                        if isinstance(f, dict)
                    ],
                    "explanation": incident.recommended_action or incident.explanation,
                    "incident_id": incident.id,
                    "threat_score": incident.threat_score,
                    "priority": incident.priority,
                    "recommended_action": incident.recommended_action,
                    "explanation_summary": incident.explanation_summary,
                    "model_version": incident.model_version,
                    "timestamp": (
                        incident.detection_time.isoformat() if incident.detection_time else now.isoformat()
                    ),
                },
            )
        )

    # The engine commits each incident it writes. This carries the status
    # changes for drones it did not write one for.
    if silent_drones:
        db.commit()

    return alerts
