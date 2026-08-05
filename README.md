# SwarmGuard AI — Autonomous Drone Threat Intelligence Platform

![CI Status](https://github.com/bserc-labs/SwarmGuard-AI/actions/workflows/ci.yml/badge.svg)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)
![React 19](https://img.shields.io/badge/React-19.2-61dafb.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688.svg)
![License MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

SwarmGuard AI is an **Explainable Mission-Aware Autonomous Drone Threat Intelligence Platform** designed to detect, analyze, explain, and autonomously respond to cyber/RF attacks on UAV fleets in real-time.

Built for defense-tech operations, Counter-UAS research, and command-and-control (C2) tactical monitoring.

---

## 🏛️ System Architecture

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

Detailed architectural blueprints and documentation:
- 📑 [System Architecture (`docs/ARCHITECTURE.md`)](docs/ARCHITECTURE.md)
- 📑 [API Reference (`docs/API_REFERENCE.md`)](docs/API_REFERENCE.md)
- 📑 [Database Schema (`docs/DATABASE_SCHEMA.md`)](docs/DATABASE_SCHEMA.md)
- 📑 [Security Architecture (`docs/SECURITY.md`)](docs/SECURITY.md)

---

## ⚡ Core Defense Features

- 🤖 **Real Trained Machine Learning:** Powered by `IsolationForest` (unsupervised anomaly detection, `contamination=0.05`) and `RandomForestClassifier` (100% attack classification accuracy).
- 🧠 **Explainable AI (TreeSHAP):** Computes exact mathematical feature contributions (`speed`, `altitude`, `battery_drain_rate`) per anomaly alert.
- 🎯 **Deterministic Multi-Sensor Fusion:** Combines 3D AESA Radar, RF Spectrum Scanner, Optical AI (YOLO), Acoustic Propeller Spectrum, and 3D Kalman Filter without random jitter.
- ⚡ **High-Performance Database Indexing:** Optimized time-range queries (`created_at`, `drone_id`, `severity`, `status`) supporting instant DVR playback over millions of rows.
- 🗺️ **Tactical Radar & Geofencing:** Polygon and circular No-Fly zone perimeter enforcement with Ray-Casting algorithm.
- ☠️ **Autonomous Kill-Chain Mitigation:** Executes instant `HARD_KILL`, `RETURN_TO_HOME`, `EMERGENCY_LAND`, or `SWITCH_SAFE_MODE` protocols.
- ⏪ **DVR Historical Playback:** Slide backward in time to replay drone fleet trajectories step-by-step.
- 🛡️ **OWASP Defense Security:** Strict rate-limiting (`5/min` login), OWASP Nginx security headers (`CSP`, `X-Frame-Options`), non-root Docker `appuser`, and 4-tier RBAC (`Admin`, `Commander`, `Analyst`, `Observer`).

---

## 🛠️ Quick Start & Installation

### Option 1: Full-Stack Docker Compose (Recommended)

```bash
docker compose up --build
```

- **C2 Dashboard:** `http://localhost`
- **Backend API Docs:** `http://localhost:8000/docs`
- **Default Login:** Operator `admin` / Password `admin123`

---

### Option 2: Local Development Setup

#### 1. Backend Setup
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r backend/requirements.txt

# Generate training dataset & train ML models
python backend/scripts/generate_dataset.py
python backend/scripts/train_model.py

# Run FastAPI dev server
uvicorn backend.main:app --reload --port 8000
```

#### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

---

## 🧪 Automated Testing

Run the pytest test suite covering AI inference, TreeSHAP, sensor fusion, Haversine math, and polygon geofencing:

```bash
./venv/bin/pytest backend/tests/ -v
```

---

## 📜 License & Credits

Built by the **SwarmGuard AI Engineering Team**. Released under the **MIT License**.
