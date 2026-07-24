import time
import random
import requests
import json
from datetime import datetime
import os

# Allow overriding via env var, default to 8000
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000/telemetry/ingest")

def generate_telemetry(drone_id: str, is_anomaly: bool = False):
    base_lat = 37.7749
    base_lon = -122.4194
    
    speed = random.uniform(5.0, 15.0)
    altitude = random.uniform(50.0, 150.0)
    battery = random.uniform(20.0, 100.0)
    
    if is_anomaly:
        # Generate anomalous spikes (e.g. erratic speed and altitude drop)
        speed = random.uniform(50.0, 100.0)
        altitude = random.uniform(10.0, 20.0)
        print(f"\n⚠️  Injecting ANOMALY for {drone_id} (Speed: {speed:.2f}, Alt: {altitude:.2f})")
    
    return {
        "drone_id": drone_id,
        "latitude": base_lat + random.uniform(-0.01, 0.01),
        "longitude": base_lon + random.uniform(-0.01, 0.01),
        "altitude": altitude,
        "speed": speed,
        "battery": battery,
        "packet_sequence": int(time.time()),
        "timestamp": datetime.now().isoformat()
    }

def run_replayer():
    print(f"🚀 Starting Dataset Replayer... Sending data to {API_URL}")
    print("Sending exactly 10 packets for testing...\n")
    drones = ["drone_alpha", "drone_beta", "drone_gamma"]
    
    try:
        while True:
            drone_id = random.choice(drones)
            
            # 15% chance to inject an attack/anomaly
            is_anomaly = random.random() < 0.15
            
            payload = generate_telemetry(drone_id, is_anomaly)
            
            try:
                response = requests.post(API_URL, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("threat_level", 0) > 0:
                        print(f"🚨 ALERT Triggered! Threat: {data.get('threat_level')} | Explanation: {data.get('explanation')}")
                    else:
                        print(f"✅ Packet sent OK for {drone_id}")
                else:
                    print(f"❌ Server returned {response.status_code}: {response.text}")
            except requests.exceptions.ConnectionError:
                print(f"❌ Connection Failed. Is the backend running at {API_URL}?")
                break
            
            time.sleep(2) # Continuous loop
            
            
    except KeyboardInterrupt:
        print("\n🛑 Replayer stopped.")

if __name__ == "__main__":
    run_replayer()
