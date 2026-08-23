import time
import os
import sys

# Ensure backend directory is in the python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from services.incident_engine import incident_engine
from models import Incident

def run_benchmark():
    db = SessionLocal()
    
    print("--- Starting Incident Engine Benchmark ---")
    
    # 1. Warmup and generate a mock detection
    detection_payload = {
        "drone_id": "BENCHMARK_DRONE",
        "prediction": {
            "is_anomaly": True,
            "anomaly_score": 90.0,
            "threat_score": 90.0,
            "threat_level": 2
        },
        "explanation": {
            "summary": {
                "Primary Cause": "GPS Spoofing",
                "Secondary Cause": "Heading Deviation"
            },
            "metadata": {
                "explanation_confidence_percent": 95.0,
                "model_version": "v1.0"
            }
        }
    }
    
    # First creation to prime caches and DB connections
    incident_engine.process_ai_detection(db, detection_payload)
    
    # 2. Benchmark new incident throughput (varying drone_id so they don't get suppressed)
    num_incidents = 100
    print(f"\nBenchmarking {num_incidents} unique incident creations (no suppression)...")
    
    t0 = time.perf_counter()
    for i in range(num_incidents):
        payload = dict(detection_payload)
        payload["drone_id"] = f"BENCHMARK_DRONE_{i}"
        incident_engine.process_ai_detection(db, payload)
    t1 = time.perf_counter()
    
    total_time = t1 - t0
    avg_time = (total_time / num_incidents) * 1000 # in ms
    print(f"Total time for {num_incidents} creations: {total_time:.2f} s")
    print(f"Average time per creation: {avg_time:.2f} ms")
    
    # 3. Benchmark duplicate suppression throughput
    print(f"\nBenchmarking {num_incidents} suppressed incidents (same drone_id)...")
    payload = dict(detection_payload)
    payload["drone_id"] = "SUPPRESSED_DRONE"
    incident_engine.process_ai_detection(db, payload) # Create it once
    
    t0 = time.perf_counter()
    for i in range(num_incidents):
        incident_engine.process_ai_detection(db, payload)
    t1 = time.perf_counter()
    
    total_time = t1 - t0
    avg_time = (total_time / num_incidents) * 1000 # in ms
    print(f"Total time for {num_incidents} suppressed events: {total_time:.2f} s")
    print(f"Average time per suppressed event: {avg_time:.2f} ms")
    
    # Cleanup benchmark data
    db.query(Incident).filter(Incident.drone_id.like("BENCHMARK_DRONE%")).delete(synchronize_session=False)
    db.query(Incident).filter(Incident.drone_id == "SUPPRESSED_DRONE").delete(synchronize_session=False)
    db.commit()
    db.close()

if __name__ == "__main__":
    run_benchmark()
