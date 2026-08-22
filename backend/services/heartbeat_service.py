from datetime import datetime, timedelta

from sqlalchemy.orm import Session

import models
from services.incident_engine import THREAT_LEVEL_ORDINALS
from utils.logger import logger

SILENCE_THRESHOLD_SECONDS = 30


def check_drone_heartbeats(db: Session) -> list[tuple[int, dict]]:
    """
    Mark drones silent past the threshold and record an incident for each.

    Returns (organization_id, alert_payload) pairs for the caller to broadcast.
    This function does NOT broadcast itself: it runs synchronously inside
    asyncio.to_thread, and the previous implementation called asyncio.run() here
    — creating a second event loop in the worker thread and writing to sockets
    owned by the main loop. The failure was caught and logged, so the alerts this
    system generates almost certainly never reached a browser.
    """
    now = datetime.utcnow()
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

        # organization_id is carried from the drone. Without it the incident is
        # written with NULL and becomes invisible to every tenant-scoped read.
        incident = models.Incident(
            organization_id=drone.organization_id,
            drone_id=drone.drone_id,
            attack_type="SIGNAL_LOSS_JAMMING",
            anomaly_score=0.95,
            threat_score=90.0,
            # Ordinal rank, not a percentage. This wrote 90 while incidents
            # from the AI pipeline write 1-4 (see THREAT_LEVEL_ORDINALS), so
            # the two sources were not comparable on a dashboard that sorts
            # by this column.
            threat_level=THREAT_LEVEL_ORDINALS["CRITICAL"],
            severity="CRITICAL",
            shap_values=[{"feature": "signal_loss_duration", "importance": 0.95}],
            explanation=(
                f"Drone '{drone.drone_id}' has not reported for more than "
                f"{SILENCE_THRESHOLD_SECONDS} seconds. Possible RF jamming or "
                "loss of communication."
            ),
        )
        db.add(incident)

        if drone.organization_id is None:
            # Nothing to scope the broadcast to; the incident is still recorded.
            logger.warning(
                f"Drone '{drone.drone_id}' has no organization; "
                "silent-drone alert not broadcast."
            )
        else:
            alerts.append(
                (
                    drone.organization_id,
                    {
                        "event_type": "SILENT_DRONE_ALERT",
                        "is_anomaly": True,
                        "drone_id": drone.drone_id,
                        "attack_type": "SIGNAL_LOSS_JAMMING",
                        "threat_level": 90,
                        "severity": "CRITICAL",
                        "explanation": (
                            f"Drone '{drone.drone_id}' has not reported for more "
                            f"than {SILENCE_THRESHOLD_SECONDS} seconds."
                        ),
                        "timestamp": now.isoformat(),
                    },
                )
            )

        logger.warning(
            f"Heartbeat alert: drone '{drone.drone_id}' silent since {drone.last_seen}"
        )

    if silent_drones:
        db.commit()

    return alerts
