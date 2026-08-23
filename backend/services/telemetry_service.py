from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

import models
import schemas
from utils.logger import logger
from services.ws_manager import ws_manager

class TelemetryService:
    def process_telemetry(self, packet: schemas.TelemetryPacket, db: Session, *, organization_id: int | None = None) -> dict:
        """
        Validates, persists, and prepares a telemetry packet for broadcast.
        Strictly decoupled from MAVLink reception and AI pipelines (Sprint 2 focus).
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
                last_seen=datetime.utcnow(),
                organization_id=organization_id,
            )
            db.add(drone)
        else:
            drone.last_seen = datetime.utcnow()
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
            raise ValueError("Database transaction failed")

        return packet.model_dump()


telemetry_service = TelemetryService()
