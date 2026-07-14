from fastapi import FastAPI
from database import engine, Base
from routers import auth

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="SwarmGuard AI API")

# Include routers
app.include_router(auth.router)

@app.get("/")
def read_root():
    return {"message": "Welcome to SwarmGuard AI API"}

@app.get("/health")
def health_check():
    return {"status": "ok"}
