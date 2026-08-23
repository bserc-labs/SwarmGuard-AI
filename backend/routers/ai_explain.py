from fastapi import APIRouter, HTTPException, Depends
from typing import List
from pydantic import BaseModel
import shap

from services.explanation_service import explanation_service
from services.ai_service import ai_service
from middleware.auth_middleware import require_permission
from middleware.rbac import Permissions
from config import get_settings

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
    timestamp: str

class ExplanationRequest(BaseModel):
    telemetry_history: List[TelemetryPayload]

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
        
    # Convert Pydantic models to dicts
    history_dicts = [item.model_dump() for item in request.telemetry_history]
    
    result = explanation_service.explain_prediction(history_dicts)
    
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
