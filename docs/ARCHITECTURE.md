# SwarmGuard AI — System Architecture

**Document Version:** 2.0  
**Classification:** Defense-Tech C2 Architecture Specification  
**Status:** Approved

---

## Executive Overview

SwarmGuard AI is a real-time, defense-grade Counter-UAS (Unmanned Aerial System) Command & Control (C2) platform. It fuses multi-sensor telemetry (3D AESA Radar, RF Spectrum Analyzer, Optical AI YOLO, Acoustic Array, 3D Kalman Filter), detects airborne cyber threats via trained Machine Learning models (IsolationForest & RandomForest), provides Explainable AI (TreeSHAP) reasoning, and executes autonomous kill-chain mitigation protocols against rogue drone swarms.

---

## 1. High-Level Data Flow Diagram

```mermaid
graph TD
    A[🛸 Drone Telemetry Source] -->|JSON Stream every 1.5s| B[FastAPI /telemetry/ingest]
    B -->|Device Security Check| C{Valid API Key?}
    C -->|No| D[🔴 403 Forbidden]
    C -->|Yes| E[3D Kalman Trajectory Filter]
    E --> F[5-Sensor Fusion Engine]
    F --> G[StandardScaler Normalization]
    G --> H[IsolationForest Anomaly Detector]
    H -->|Anomaly Detected?| I[RandomForest Attack Classifier]
    H -->|Normal Flight| J[🟢 Green / Safe Status]
    I --> K[TreeSHAP XAI Feature Explainer]
    K --> L[Piecewise/Sigmoid Threat Score Engine]
    L --> M[Geofence Perimeter Engine]
    M --> N[Autonomous Kill-Chain Engine]
    N -->|Inside Restricted Zone + Critical| O[☠️ Auto HARD_KILL / RTH]
    N --> P[Immutable Audit Trail Logging]
    O --> Q[WebSocket Broadcast to Clients]
    P --> Q
    Q --> R[React 19 Glassmorphic C2 Dashboard]
```

---

## 2. Component Architecture

```mermaid
graph LR
    subgraph Client Layer
        UI[React 19 SPA]
        MAP[React-Leaflet Radar]
        CHARTS[Recharts + TreeSHAP]
        DVR[DVR Timeline Scrubber]
    end

    subgraph API & Gateway Layer
        NGINX[Nginx Reverse Proxy & OWASP Headers]
        LIMITER[slowapi Rate Limiter]
        AUTH[JWT + 4-Tier RBAC]
    end

    subgraph Intelligence & Processing Layer
        FASTAPI[FastAPI Service]
        KALMAN[3D Kalman Filter]
        FUSION[Multi-Sensor Fusion Engine]
        ML[Trained ML .joblib Models]
        SHAP[TreeSHAP Explainer]
        GEOFENCE[Ray-Casting Geofence Engine]
        KILLCHAIN[Autonomous Kill-Chain Rules Engine]
    end

    subgraph Data & Storage Layer
        DB[(PostgreSQL / SQLite)]
        REDIS[(Redis Pub/Sub)]
    end

    UI <--> NGINX
    NGINX --> LIMITER
    LIMITER --> AUTH
    AUTH --> FASTAPI
    FASTAPI --> KALMAN
    FASTAPI --> FUSION
    FASTAPI --> ML
    FASTAPI --> SHAP
    FASTAPI --> GEOFENCE
    FASTAPI --> KILLCHAIN
    FASTAPI --> DB
    FASTAPI <--> REDIS
```

---

## 3. Core Processing Pipeline

### 3.1 Telemetry Ingestion & Filtering
1. **Device Authentication:** Incoming packets are validated via `x-drone-api-key` headers against configured defense secrets.
2. **Pydantic Validation:** Coordinates (`latitude`: -90° to 90°, `longitude`: -180° to 180°), altitude ($0 - 50,000$m), speed ($0 - 500$m/s), and battery ($0 - 100\%$) are strictly bounded.

### 3.2 3D Kalman State Estimation
- State Vector: $X = [\text{lat}, \text{lon}, \text{alt}, v_{\text{lat}}, v_{\text{lon}}, v_{\text{alt}}]^T$
- Constant velocity motion model detects sudden spatial position jumps ($> 150$m deviation) or uncommanded altitude crashes.

### 3.3 Real Machine Learning Inference
- **IsolationForest:** Trained with `n_estimators=200` and `contamination=0.05` to compute decision scores for unsupervised anomaly detection.
- **RandomForestClassifier:** Classifies anomalous flight behavior into specific threat vectors (`GPS_SPOOFING`, `JAMMING`, `DOS`, `REPLAY_ATTACK`).

### 3.4 TreeSHAP Explainability
- Calculates exact mathematical contribution of each telemetry feature to the threat score, answering *why* a drone was flagged.

### 3.5 Autonomous Kill-Chain Response
- Evaluates threat severity, geofence breaches, and signal loss ($> 30$ seconds).
- Executes autonomous mitigation (`HARD_KILL`, `RETURN_TO_HOME`, `EMERGENCY_LAND`, `SWITCH_SAFE_MODE`) and logs actions to an immutable `AuditLog` table.
