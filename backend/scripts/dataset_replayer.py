import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import logger
import time
import random
import requests
import json
from datetime import datetime
import os

import argparse

# Allow overriding via env var, default to 8000
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000/telemetry/ingest")
API_KEY = os.getenv("DRONE_API_KEY", "SWARMGUARD_DRONE_DEFENSE_SECRET_2026")
HEADERS = {
    "Content-Type": "application/json",
    "x-drone-api-key": API_KEY
}

# LA Base / Target Sector Coordinates
BASE_LAT = 34.0522
BASE_LON = -118.2437

def generate_telemetry(drone_id: str, is_anomaly: bool = False, attack_mode: str = "normal", index: int = 0):
    speed = random.uniform(8.0, 18.0)
    altitude = random.uniform(60.0, 120.0)
    battery = random.uniform(40.0, 98.0)
    lat = BASE_LAT + random.uniform(-0.005, 0.005)
    lon = BASE_LON + random.uniform(-0.005, 0.005)

    if attack_mode == "swarm_encircle":
        # Arrange drones in a tight V-shaped perimeter encirclement around BASE
        angle = (index * (360 / 6)) * (math.pi / 180)
        radius = 0.004  # ~400 meters inside restricted geofence
        lat = BASE_LAT + (radius * math.cos(angle))
        lon = BASE_LON + (radius * math.sin(angle))
        speed = 28.5  # High tactical speed
        logger.info(f"🚁 [SWARM ENCIRCLE] {drone_id} advancing in synchronized formation at ({lat:.4f}, {lon:.4f})")

    elif attack_mode == "gps_spoofing":
        if is_anomaly:
            # Sudden geographically impossible GPS jump
            lat = BASE_LAT + random.uniform(0.15, 0.35)
            lon = BASE_LON + random.uniform(0.15, 0.35)
            speed = 120.0
            logger.info(f"🚨 [GPS SPOOFING] {drone_id} telemetry jumped to ({lat:.4f}, {lon:.4f}) at {speed} m/s!")

    elif attack_mode == "jamming":
        if is_anomaly:
            battery = 5.0
            altitude = 5.0
            speed = 0.0
            logger.info(f"⚡ [RF JAMMING] {drone_id} communication signal lost/jammed!")

    elif is_anomaly:
        speed = random.uniform(50.0, 100.0)
        altitude = random.uniform(10.0, 20.0)
        logger.info(f"⚠️ Injecting ANOMALY for {drone_id} (Speed: {speed:.2f}, Alt: {altitude:.2f})")

    return {
        "drone_id": drone_id,
        "latitude": round(lat, 6),
        "longitude": round(lon, 6),
        "altitude": round(altitude, 2),
        "speed": round(speed, 2),
        "battery": round(battery, 2),
        "packet_sequence": int(time.time()),
        "timestamp": datetime.now().isoformat()
    }

import math

def run_replayer(attack_mode: str = "normal"):
    logger.info(f"🚀 Starting Dataset Replayer... Streaming to {API_URL} [Mode: {attack_mode.upper()}]")
    drones = ["drone_alpha", "drone_beta", "drone_gamma", "drone_delta", "drone_epsilon", "drone_zeta"]

    try:
        idx = 0
        while True:
            drone_id = drones[idx % len(drones)]
            is_anomaly = random.random() < 0.25 if attack_mode != "swarm_encircle" else True

            payload = generate_telemetry(drone_id, is_anomaly, attack_mode, idx % len(drones))

            try:
                response = requests.post(API_URL, json=payload, headers=HEADERS)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("threat_level", 0) > 0:
                        logger.info(f"🚨 ALERT! {drone_id} | Threat Score: {data.get('threat_level')} | {data.get('explanation')}")
                    else:
                        logger.info(f"✅ Packet sent OK for {drone_id}")
                else:
                    logger.info(f"❌ Server returned {response.status_code}: {response.text}")
            except requests.exceptions.ConnectionError:
                logger.info(f"❌ Connection Failed. Is backend running at {API_URL}?")
                break

            idx += 1
            time.sleep(1.5)

    except KeyboardInterrupt:
        logger.info("\n🛑 Replayer stopped.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SwarmGuard AI Telemetry & Attack Simulator")
    parser.add_argument("--attack", choices=["normal", "swarm_encircle", "gps_spoofing", "jamming"], default="normal", help="Simulation scenario")
    args = parser.parse_args()
    run_replayer(attack_mode=args.attack)
