# Explainable AI (XAI) Architecture

This document describes the design and flow of the SHAP-based Explainable AI layer implemented in Sprint 4.

## Overview
The XAI layer translates raw anomaly scores into transparent, human-readable explanations. It strictly adheres to the principle of decoupling: inference and explainability operate as completely independent services, allowing explanations to be generated on-demand without slowing down the critical path of the telemetry ingestion engine.

## 1. SHAP Integration (`models_ml/explainability.py`)
### Why SHAP was Selected
SHAP (SHapley Additive exPlanations) is a game-theoretic approach to explain the output of any machine learning model. It guarantees local accuracy (the sum of feature contributions equals the prediction) and consistency.

### Explainer Selection & Fallback
The `ExplainabilityEngine` implements a robust loader:
1. **TreeExplainer**: First attempts to use `shap.TreeExplainer`, which is highly optimized for Isolation Forest models.
2. **KernelExplainer**: If the specific sklearn version causes `TreeExplainer` to fail, it automatically falls back to `shap.KernelExplainer`, initializing it with a background dataset (n=100) sampled from `dataset_loader.py`.

### Computational Cost & Limitations
- **Single Explanations**: Benchmarked at ~9.45ms average using `TreeExplainer`.
- **Batch Processing**: Highly efficient, averaging ~0.02ms per record due to vectorization.
- **Limitation (KernelExplainer)**: If forced to fallback to `KernelExplainer`, latency will dramatically increase, making real-time explanations unfeasible for high-frequency telemetry.

## 2. Explanation Service (`services/explanation_service.py`)
This service acts as the translator between raw mathematics and SOC analysts.
It retrieves SHAP magnitudes, maps them to human-readable feature strings (e.g., mapping `gps_drift` to "Abnormal GPS Drift (Spoofing Indicator)"), and formats a structured template.

### Structured Templates
Every explanation is formatted identically to reduce cognitive load on the analyst:
- **Primary Cause**: The feature with the highest SHAP magnitude.
- **Secondary Cause**: The second highest feature.
- **Supporting Indicators**: Up to 3 additional contributing features.
- **Recommended Action**: Deterministically mapped from the Primary Cause (e.g., GPS drift → "Review GPS integrity", Battery drain → "Command RTL").

## 3. Explanation API (`routers/ai_explain.py`)
- `POST /ai/explain`: Re-runs inference, extracts features, calculates SHAP values, and returns the analyst template.
- `GET /ai/explanation/model`: Exposes XAI health, current `shap.__version__`, explainer type, and loaded feature mappings.

## 4. XAI Technical Debt & Future Migration
> [!WARNING]
> **Risk**: The current Explanation Service re-calculates the rolling features (via `FeatureEngineer`) when the `POST /ai/explain` endpoint is hit.
> **Impact**: If telemetry packets are updated between the inference and the explanation request, the explanation may drift slightly from the original prediction.
> **Mitigation**: Future sprints should implement a Redis caching layer for `scaled_features` keyed by `drone_id` and `timestamp`, allowing the XAI service to pull exactly the features that triggered the original anomaly.
