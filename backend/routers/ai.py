
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import schemas
from config import get_settings
from middleware.auth_middleware import require_permission
from middleware.rbac import Permissions
from models_ml.registry import model_registry
from services.ai_service import ai_service

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
    telemetry_history: list[schemas.TelemetryPacket]

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
        _model, _scaler, _metadata = model_registry.load_model(settings.MODEL_VERSION)
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
        _model, _scaler, metadata = model_registry.load_model(settings.MODEL_VERSION)
        return metadata
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Model metadata not found.") from None


# The checks KinematicGuard.evaluate() performs, paired with the setting that
# supplies each limit. Declared here rather than derived by introspection so the
# endpoint states the contract explicitly; test_detection_status_matches_guard
# pins it against the guard's own configuration.
_GUARD_CHECKS = [
    {
        "check": "gps_implied_speed",
        "unit": "m/s",
        "threshold": settings.GUARD_MAX_SPEED_MPS,
        "description": "Ground speed implied by successive position fixes, against the airframe envelope.",
    },
    {
        "check": "gps_airframe_speed_mismatch",
        "unit": "m/s",
        "threshold": settings.GUARD_GPS_SPEED_ERROR_MPS,
        "description": "Disagreement between GNSS-derived speed and the speed the airframe reports. The core spoofing signature.",
    },
    {
        "check": "vertical_speed",
        "unit": "m/s",
        "threshold": settings.GUARD_MAX_CLIMB_MPS,
        "description": "Climb or descent rate against the airframe envelope.",
    },
    {
        "check": "satellite_loss",
        "unit": "satellites",
        "threshold": float(settings.GUARD_MIN_SATELLITES),
        "description": "Satellite count falling below the floor, having previously held lock.",
        "lower_is_worse": True,
    },
]


@router.get("/detection/status")
def get_detection_status():
    """What is actually detecting, on what settings, with what measured performance.

    This exists because the two-tier design was invisible from the console: an
    operator could see incidents but not which tier produced them, on what
    thresholds, or why the ML tier is switched off. A detection system whose
    own configuration cannot be read is difficult to trust and impossible to
    tune.

    Behind the ai.explain permission with the rest of this router. The
    thresholds are, in effect, the evasion envelope, so they are not public.
    """
    described = model_registry.describe(settings.MODEL_VERSION)
    lofo = (described.get("evaluation") or {}).get("lofo", {}).get("pooled", {})
    ceiling = (described.get("evaluation") or {}).get("stratified_row_level_ceiling", {})
    evaluation = described.get("evaluation") or {}

    return {
        "tiers": [
            {
                "tier": 1,
                "name": "Kinematic guard",
                "detector": "kinematic_guard",
                "method": "Deterministic physical-plausibility checks",
                "enabled": settings.GUARD_ENABLED,
                # Tier 1 is the only detector permitted to raise an incident by
                # default; see detection_pipeline._run_detectors.
                "raises_incidents": settings.GUARD_ENABLED,
                "deterministic": True,
                "requires_training_data": False,
                "checks": _GUARD_CHECKS,
            },
            {
                "tier": 2,
                "name": "ML anomaly model",
                "detector": "random_forest",
                "method": "Supervised classifier over engineered telemetry features",
                "enabled": settings.AI_INCIDENTS_ENABLED,
                "raises_incidents": settings.AI_INCIDENTS_ENABLED,
                "deterministic": False,
                "requires_training_data": True,
                "model_version": settings.MODEL_VERSION,
                "artifact_status": described.get("artifact_status"),
                "feature_list": (described.get("metadata") or {}).get("feature_list", []),
                # The honest number, and the number a naive split would have
                # reported. Both are shown because the gap between them is the
                # finding, not either figure alone.
                "validation": {
                    "protocol": "leave-one-flight-out",
                    "precision": lofo.get("precision"),
                    "recall": lofo.get("recall"),
                    "f1_score": lofo.get("f1_score"),
                    "false_positive_rate": lofo.get("false_positive_rate"),
                    "n_folds": evaluation.get("lofo", {}).get("n_folds"),
                    "mean_flight_accuracy": evaluation.get("lofo", {}).get("mean_flight_accuracy"),
                },
                "contrast": {
                    "protocol": "stratified row-level split",
                    "f1_score": ceiling.get("f1_score"),
                    "caveat": evaluation.get("ceiling_caveat"),
                },
                # What was tried against the generalisation failure, and what
                # each attempt measured. Present so the console can answer "why
                # is this off" rather than only reporting that it is.
                "investigations": described.get("investigations") or {},
                "disabled_reason": (
                    None
                    if settings.AI_INCIDENTS_ENABLED
                    else (
                        "Leave-one-flight-out validation puts this model at F1 "
                        f"{lofo.get('f1_score')} with a {lofo.get('false_positive_rate')} "
                        "false-positive rate. Raising incidents at that rate would bury "
                        "genuine alerts, so the physics tier is authoritative instead."
                    )
                ),
            },
        ]
    }
