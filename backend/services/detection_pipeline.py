"""Live detection pipeline: telemetry ingest -> inference -> incident.

This is the integration that turns the AI layer from an endpoint someone can
call into something that actually runs on the live feed. Previously
`telemetry_service` persisted a packet and stopped there, and
`incident_engine.process_ai_detection` had no callers anywhere in the
codebase, so no incident was ever raised from real telemetry.

Ordering matters here. The detection needs the packet it was triggered by to
already be committed, because it reads its window back out of the database
rather than being handed the packet -- rolling features (drift, deltas,
variance) are only defined against the preceding packets. So this runs after
the ingest transaction commits, not inside it.

Threading matters too. Inference is synchronous, CPU-bound sklearn work and a
blocking DB read; the broadcast is async and owns the event loop's sockets.
The two are split accordingly -- `asyncio.to_thread` for the work, the loop
itself for delivery. This mirrors the heartbeat monitor in main.py.
"""

import asyncio

from sqlalchemy.orm import Session

import models
from config import get_settings
from database import SessionLocal
from services.explanation_service import explanation_service
from services.geofence_service import geofence_engine
from services.incident_engine import incident_engine
from services.kinematic_guard import kinematic_guard
from services.ws_manager import ws_manager
from utils.logger import logger

settings = get_settings()

# Two packets is the floor for any rate at all, which is what the kinematic
# guard needs. The ML tier wants settings.WINDOW_SIZE for its rolling
# statistics and declines on its own below that -- explain_prediction returns
# status "insufficient_data" for any window whose feature vector is undefined --
# so gating the whole pipeline at the larger number would delay physics checks
# that are already valid.
MIN_HISTORY_PACKETS = 2

# Upper bound on the window handed to the feature engineer. Enough context for
# a WINDOW_SIZE rolling window with room to spare, small enough that ingest at
# 50/s does not turn into a full table scan per packet.
MAX_HISTORY_PACKETS = 50


def _load_history(db: Session, drone_id: str, organization_id: int) -> list[dict]:
    """Read this drone's recent telemetry, oldest first, scoped to its tenant.

    Returned oldest-first because every rolling feature (diff, rolling var)
    assumes forward chronological order; the query itself is descending so the
    LIMIT takes the newest rows rather than the first ones ever recorded.
    """
    rows = (
        db.query(models.TelemetryLog)
        .filter(
            models.TelemetryLog.organization_id == organization_id,
            models.TelemetryLog.drone_id == drone_id,
        )
        # `id` breaks ties: created_at is a server default, so packets ingested
        # in the same instant share a timestamp and would otherwise come back
        # in arbitrary order -- which scrambles every diff-based feature.
        #
        # Ordered by arrival, not by sample_time_ms, even when every row has
        # one: a reboot resets time_boot_ms to ~0, so a window spanning one
        # would sort the post-reboot packets *before* the pre-reboot ones and
        # the guard would keep re-evaluating an old pair for up to
        # MAX_HISTORY_PACKETS packets. The guard handles a non-monotonic
        # device interval itself (kinematic_guard._interval_seconds).
        .order_by(
            models.TelemetryLog.created_at.desc(),
            models.TelemetryLog.id.desc(),
        )
        .limit(MAX_HISTORY_PACKETS)
        .all()
    )

    return [
        {
            "drone_id": row.drone_id,
            "latitude": row.latitude,
            "longitude": row.longitude,
            "altitude": row.altitude,
            "speed": row.speed,
            "heading": row.heading,
            "battery": row.battery,
            "flight_mode": row.flight_mode,
            "armed_status": row.armed_status,
            "satellites": row.satellites,
            "packet_sequence": row.packet_sequence,
            "sample_time_ms": row.sample_time_ms,
            "created_at": row.created_at,
        }
        for row in reversed(rows)
    ]


def _run_detectors(
    drone_id: str, history: list[dict], db: Session, organization_id: int
) -> dict | None:
    """Two-tier detection. Returns a detection dict, or None if nothing fired.

    **Tier 1 — kinematic guard (authoritative).** Deterministic physical
    plausibility. If it fires, that is the incident: the evidence is arithmetic
    an analyst can re-check, and it cannot false-positive on a manoeuvre the
    airframe is physically capable of.

    **Tier 2 — ML anomaly model (advisory, off by default).** Runs only when
    AI_INCIDENTS_ENABLED is set. Under leave-one-flight-out validation the v2
    model scores F1 0.086 at a 0.862 false-positive rate, so by default it does
    not get to raise anything -- roughly six of every seven of its alerts would
    be noise, and an operator who learns to ignore the dashboard is worse off
    than one who has none. backend/models_ml/v2/evaluation.json is the
    authoritative source for those numbers.

    The ordering is deliberate: physics first. When both would fire, the
    explanation an operator sees should be the one with checkable numbers
    behind it.
    """
    if settings.GUARD_ENABLED:
        verdict = kinematic_guard.evaluate(history)
        if verdict.triggered:
            logger.info(
                f"Kinematic guard fired for {drone_id}: {verdict.attack_type} "
                f"({verdict.severity}, {len(verdict.violations)} violation(s))"
            )
            return verdict.to_detection(drone_id)

    # **Tier 1b -- geofence breach.** Deterministic, like the guard, but it
    # answers a different question: not "is this telemetry lying" but "is the
    # aircraft where it is not permitted to be".
    #
    # It runs only when the guard stayed silent, and that ordering is the point.
    # A geofence verdict is only as good as the position it is handed, so when
    # the guard has just judged the reported position physically impossible,
    # evaluating a restricted zone against that same position would raise an
    # incident about a location the aircraft is probably not at. Spoofing is
    # already the incident in that case.
    latest = history[-1]
    lat, lon = latest.get("latitude"), latest.get("longitude")
    breach = (
        geofence_engine.evaluate(db, drone_id, lat, lon, organization_id=organization_id)
        if lat is not None and lon is not None
        else None
    )
    if breach is not None:
        zones = breach["explanation"]["metadata"]["zones"]
        logger.info(
            f"Geofence breach for {drone_id} in org {organization_id}: "
            f"{', '.join(z['name'] for z in zones)}"
        )
        return breach

    if not settings.AI_INCIDENTS_ENABLED:
        return None

    result = explanation_service.explain_prediction(history)
    if result.get("status") == "insufficient_data":
        # Routine, not a fault: a drone that has just come online does not yet
        # have a window the rate features are defined over.
        logger.info(f"ML detection declined for {drone_id}: window not yet defined.")
        return None
    if "error" in result:
        logger.warning(f"ML detection skipped for {drone_id}: {result['error']}")
        return None

    if not result.get("prediction", {}).get("is_anomaly"):
        return None

    return {"drone_id": drone_id, **result}


def _detect_sync(drone_id: str, organization_id: int) -> dict | None:
    """Run one detection cycle. Returns a broadcast payload, or None.

    Owns its own session: the request-scoped session is already closed by the
    time a background task runs.
    """
    db = SessionLocal()
    try:
        history = _load_history(db, drone_id, organization_id)
        if len(history) < MIN_HISTORY_PACKETS:
            # Normal for a drone that just came online, not an error.
            return None

        detection = _run_detectors(drone_id, history, db, organization_id)
        if detection is None:
            return None

        outcome = incident_engine.record_detection(
            db, detection, organization_id=organization_id
        )
        incident = outcome.incident
        if incident is None:
            # A repeat of a live incident that this reading did not worsen.
            return None

        # Field names follow the frontend's DetectionResult interface
        # (frontend/src/services/api.ts) so the existing alert path renders
        # this without a client change -- notably `shap_top3`, not
        # `shap_values`, and a numeric `threat_level`.
        ranked = incident.shap_values or []
        return {
            "type": "incident",
            # An escalation inside the suppression window used to update the
            # row and tell nobody: the dashboard kept showing the lower
            # severity. It is now broadcast as the same frame with the same
            # incident_id, so a client keyed on the incident updates in place.
            # Only event_type differs.
            "event_type": "AI_DETECTION" if outcome.created else "INCIDENT_ESCALATED",
            "is_anomaly": True,
            "drone_id": incident.drone_id,
            "attack_type": incident.attack_type,
            "severity": incident.severity,
            "anomaly_score": incident.anomaly_score,
            "threat_level": incident.threat_level,
            "shap_top3": [
                {
                    "feature": f.get("feature"),
                    "importance": abs(f.get("shap_value", 0.0)),
                }
                for f in ranked[:3]
                if isinstance(f, dict)
            ],
            "explanation": incident.recommended_action or incident.explanation,
            "timestamp": (
                incident.detection_time.isoformat()
                if incident.detection_time
                else None
            ),
            # Incident-specific extras, ignored by the alert banner but used by
            # the incident views.
            "incident_id": incident.id,
            "threat_score": incident.threat_score,
            "priority": incident.priority,
            "recommended_action": incident.recommended_action,
            "explanation_summary": incident.explanation_summary,
            "model_version": incident.model_version,
        }
    finally:
        db.close()


async def run_detection(drone_id: str, organization_id: int) -> None:
    """Background entry point invoked per ingested packet.

    Never raises into the caller: a detection failure must not turn a
    successful ingest into a 500, and must not kill the background task
    runner for subsequent packets.
    """
    try:
        payload = await asyncio.to_thread(_detect_sync, drone_id, organization_id)
    except Exception as e:
        logger.error(f"Detection pipeline failed for {drone_id}: {e}", exc_info=True)
        return

    if payload is None:
        return

    try:
        await ws_manager.broadcast(payload, organization_id)
        logger.info(
            f"Incident #{payload['incident_id']} broadcast to org {organization_id} "
            f"({payload['severity']} {payload['attack_type']} on {drone_id})"
        )
    except Exception as e:
        logger.error(f"Incident broadcast failed for {drone_id}: {e}")
