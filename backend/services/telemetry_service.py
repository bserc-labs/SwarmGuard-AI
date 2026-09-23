from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import models
import schemas
from services.audit_service import audit_service
from utils.logger import logger


class TelemetryService:
    def process_telemetry(
        self,
        packet: schemas.TelemetryPacket,
        db: Session,
        *,
        organization_id: int | None = None,
        actor: str | None = None,
    ) -> dict:
        """
        Validates, persists, and prepares a telemetry packet for broadcast.
        Strictly decoupled from MAVLink reception and AI pipelines (Sprint 2 focus).

        `actor` enables the one audit record this path writes: a drone_id
        appearing in an organization for the first time. Routine packets are
        deliberately *not* audited -- `telemetry_logs` already is the record of
        them, and at the route's 50 req/s limit auditing each one would add
        ~4.3 M rows a day to a table with no retention policy. A new airframe
        joining the fleet is a different kind of event: low volume, and the
        thing an investigator actually wants to know.

        The audit row is staged before the commit below, so the drone and its
        audit entry land in the same transaction or neither does.
        """
        # 1. Update Drone state (scoped to organization)
        drone_query = db.query(models.Drone).filter(models.Drone.drone_id == packet.drone_id)
        if organization_id is not None:
            drone_query = drone_query.filter(models.Drone.organization_id == organization_id)
        drone = drone_query.first()

        if not drone:
            drone = models.Drone(
                drone_id=packet.drone_id,
                status="ACTIVE",
                last_seen=datetime.now(UTC),
                organization_id=organization_id,
            )
            db.add(drone)
            if actor is not None and organization_id is not None:
                audit_service.log(
                    db=db,
                    actor=actor,
                    action="DRONE_FIRST_SEEN",
                    organization_id=organization_id,
                    resource="Drone",
                    resource_id=packet.drone_id,
                    details=(
                        f"Drone '{packet.drone_id}' reported telemetry for the first "
                        f"time in organization {organization_id}."
                    ),
                )
        else:
            drone.last_seen = datetime.now(UTC)
            if drone.status != "ACTIVE":
                drone.status = "ACTIVE"
        
        # 2. Persist to TimescaleDB
        log_data = packet.model_dump()
        if organization_id is not None:
            log_data["organization_id"] = organization_id
        db_log = models.TelemetryLog(**log_data)
        db.add(db_log)
        
        try:
            db.commit()
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database insertion failed for telemetry: {e}")
            raise ValueError("Database transaction failed") from e

        return packet.model_dump()


telemetry_service = TelemetryService()
