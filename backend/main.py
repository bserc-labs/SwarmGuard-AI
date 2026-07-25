from fastapi import FastAPI
from database import engine, Base
from routers import auth
from routers import protected
from routers import telemetry
from routers import incidents
from routers import dashboard
from routers import websocket

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="SwarmGuard AI API")

# Include routers
app.include_router(auth.router)
app.include_router(protected.router)
app.include_router(telemetry.router)
app.include_router(incidents.router)
app.include_router(dashboard.router)
app.include_router(websocket.router)

@app.get("/")
def read_root():
    return {"message": "Welcome to SwarmGuard AI API"}

@app.get("/health")
def health_check():
    return {"status": "ok"}


