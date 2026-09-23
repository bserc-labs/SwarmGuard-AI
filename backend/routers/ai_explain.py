from datetime import UTC, datetime

import shap
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import get_settings
from middleware.auth_middleware import require_permission
from middleware.rbac import Permissions
from services.ai_service import ai_service
from services.explanation_service import explanation_service

# See routers/ai.py — the same router-level guard applies here.
router = APIRouter(
    prefix="/ai",
    tags=["Explainable AI"],
    dependencies=[Depends(require_permission(Permissions.AI_EXPLAIN))],
)
settings = get_settings()

class TelemetryPayload(BaseModel):
    drone_id: str
    latitude: float
    longitude: float
    altitude: float
    speed: float
    heading: float
    battery: float
    flight_mode: str
    satellites: int
    packet_sequence: int
    # ISO-8601. Parsed, not passed through as text: it becomes `created_at`, the
    # column every rate feature is differenced against.
    timestamp: datetime

class ExplanationRequest(BaseModel):
    telemetry_history: list[TelemetryPayload]

@router.post("/explain")
async def explain_anomaly(request: ExplanationRequest):
    """
    Analyzes a sequence of telemetry packets, runs AI anomaly detection, 
    and generates a SHAP-based analyst explanation.
    """
    if not request.telemetry_history:
        raise HTTPException(status_code=400, detail="Telemetry history cannot be empty")
        
    if len(request.telemetry_history) < settings.WINDOW_SIZE:
        raise HTTPException(
            status_code=400, 
            detail=f"At least {settings.WINDOW_SIZE} packets are required for rolling feature computation."
        )
        
    # FeatureEngineer derives every rate feature from `created_at`, the column
    # the live pipeline reads from the database. This schema calls the same
    # thing `timestamp`, and nothing bridged the two -- so on this route every
    # time-derived feature was NaN on every call, and the endpoint returned a
    # confident attribution computed from features that did not exist.
    #
    # Normalised to aware UTC, matching the timestamptz column the live
    # pipeline feeds (migration m3b4c5d6e7f8): a payload mixing "...Z" with
    # offset-less values otherwise reaches pandas as mixed tz-aware/naive and
    # becomes a 500. An offset-less value is read as UTC, which is what this
    # API has always meant by a bare timestamp.
    history_dicts = [
        {
            **item.model_dump(),
            "created_at": (
                item.timestamp.astimezone(UTC)
                if item.timestamp.tzinfo
                else item.timestamp.replace(tzinfo=UTC)
            ),
        }
        for item in request.telemetry_history
    ]

    result = explanation_service.explain_prediction(history_dicts)

    # A window the model cannot be asked about is the caller's to fix, not a
    # server fault: too few packets, or timestamps that do not advance.
    if result.get("status") == "insufficient_data":
        raise HTTPException(status_code=400, detail=result["error"])
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
        
    return result

@router.get("/explanation/model")
async def get_explainer_status():
    """
    Returns the current status of the explainability engine.
    """
    ai_service._lazy_load_model()
    
    if not ai_service.model:
        return {
            "status": "offline",
            "reason": "Underlying AI model is not loaded."
        }
        
    try:
        explanation_service._lazy_load_engine()
        engine = explanation_service.engine
        
        return {
            "status": "online",
            "model_version": settings.MODEL_VERSION,
            "shap_version": shap.__version__,
            "explainer_type": engine.explainer_type if engine else "None",
            "supported_features": engine.feature_names if engine else [],
            "feature_mapping": engine.feature_mapping if engine else {}
        }
    except Exception as e:
        return {
            "status": "error",
            "error_details": str(e)
        }
