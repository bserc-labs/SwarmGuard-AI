# SwarmGuard AI - Sentinel Dashboard

SwarmGuard AI is a real-time, AI-driven drone swarm threat detection and visualization platform built for the BSERC Def-Space Internship. It uses an Isolation Forest machine learning model to ingest drone telemetry, detect anomalies in real-time, and broadcast the alerts to a React-based command dashboard via WebSockets.

## Project Structure
- `backend/`: FastAPI application, SQLite database, ML models, and dataset replayers.
- `frontend/`: React + Vite dashboard built with Tailwind CSS and TanStack Router.
- `models_ml/`: Contains the pre-trained Isolation Forest model and scalers.

## Tech Stack
- **Frontend**: React 18, Vite, Tailwind CSS, TanStack Router, Recharts, React Query
- **Backend**: Python 3.11, FastAPI, SQLAlchemy (SQLite), WebSockets
- **AI/ML**: Scikit-Learn (Isolation Forest), SHAP (Explainable AI)

## Local Setup & Installation

### 1. Environment Variables
Create a `.env` file in the root `backend/` directory with the following variables:
```env
DATABASE_URL=sqlite:///./swarmguard.db
SECRET_KEY=your_super_secret_key_change_in_production
ALGORITHM=HS256
TOKEN_EXPIRE=1440
```

### 2. Run the Full Stack via Docker (v2.0)
You can spin up the entire application (Frontend, Backend, and Database) using our multi-stage Docker Compose setup:
```bash
docker compose up --build
```
Once it's running:
- **Frontend Dashboard**: `http://localhost` (or `http://localhost:80`)
- **Backend API Docs**: `http://localhost:8000/docs`

Log in to the dashboard using:
- **Operator ID**: `admin`
- **Passkey**: `admin`

### 3. Local Development (Without Docker)
If you are developing the frontend locally without Docker:
```bash
cd frontend
npm install
npm run dev
```
*(The React server will run on `http://localhost:5173`)*

### 4. Running the AI Simulator (Data Injection)
To simulate live drone telemetry and trigger the AI threat detection:
```bash
cd backend
python scripts/dataset_replayer.py
```
This will start streaming packets to the backend, which will instantly appear on your frontend dashboard!

## Features
- **Real-Time Telemetry Feed**: Live data table of drone GPS, altitude, speed, and battery.
- **AI Threat Explainability (SHAP)**: Bar charts explaining *exactly* which metrics caused the AI to flag an anomaly.
- **WebSocket Alerts**: Global flashing red banners the instant an attack is injected.
- **Fleet Grid**: Live operational view of all connected swarm drones.
- **Strict Role-Based Access Control (RBAC)**: Secure JWT authentication.
