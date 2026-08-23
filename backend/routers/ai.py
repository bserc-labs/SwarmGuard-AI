from typing import List
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import schemas
from config import get_settings
from services.ai_service import ai_service
from middleware.auth_middleware import require_permission
from middleware.rbac import Permissions
from models_ml.registry import model_registry

settings = get_settings()

# Authentication is declared at the router so a new endpoint cannot be added
# without it. These routes were previously public: they exposed inference plus
# the model's metadata, metrics, feature list, and SHAP feature mapping — a
# blueprint for evading the detector.
router = APIRouter(
    prefix="/ai",
    tags=["ai"],
    dependencies=[Depends(require_permission(Permissions.AI_EXPLAIN))],
)

class PredictRequest(BaseModel):
    # Pass history of packets so feature engineer can compute rolling windows
    telemetry_history: List[schemas.TelemetryPacket]

@router.post("/predict")
def predict_anomaly(request: PredictRequest):
    """
    Runs anomaly detection inference on a telemetry history window.
    The response maps anomaly score to threat level.
    """
    if not request.telemetry_history:
        raise HTTPException(status_code=400, detail="Telemetry history cannot be empty.")
        
    # Convert Pydantic objects to dicts for pandas DataFrame
    history_dicts = [pkt.model_dump() for pkt in request.telemetry_history]
    
    result = ai_service.predict(history_dicts)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
        
    return result

@router.get("/model/status")
def get_model_status():
    """Returns the status of the currently loaded model."""
    try:
        model, scaler, metadata = model_registry.load_model(settings.MODEL_VERSION)
        return {
            "status": "loaded",
            "model_version": settings.MODEL_VERSION
        }
    except FileNotFoundError:
        return {
            "status": "missing",
            "model_version": settings.MODEL_VERSION
        }

@router.get("/model/info")
def get_model_info():
    """Returns metadata and evaluation metrics for the active model."""
    try:
        model, scaler, metadata = model_registry.load_model(settings.MODEL_VERSION)
        return metadata
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Model metadata not found.")
