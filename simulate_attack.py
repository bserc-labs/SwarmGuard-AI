import requests
import time
import random
import math
from concurrent.futures import ThreadPoolExecutor

API_URL = "http://localhost:8000/telemetry/ingest"
API_KEY = "SWARMGUARD_DRONE_DEFENSE_SECRET_2026"
HEADERS = {
    "Content-Type": "application/json",
    "x-drone-api-key": API_KEY
}

# Base coordinates around a defense sector (e.g. 34.0522, -118.2437)
BASE_LAT = 34.0522
BASE_LNG = -118.2437

class DroneSimulator:
    def __init__(self, drone_id: str, offset_x: float, offset_y: float):
        self.drone_id = drone_id
        self.lat = BASE_LAT + offset_x
        self.lng = BASE_LNG + offset_y
        self.altitude = random.uniform(100.0, 300.0)
        self.speed = random.uniform(12.0, 25.0)
        self.battery = 100.0
        self.sequence = 0
        self.under_attack = False
        self.attack_type = None

    def update_position(self):
        self.sequence += 1
        self.battery = max(10.0, self.battery - 0.05)

        if self.under_attack:
            if self.attack_type == "GPS_SPOOFING":
                # Sudden massive speed burst and coordinate jump
                self.speed = 480.0
                self.lat += random.choice([-0.05, 0.05])
                self.lng += random.choice([-0.05, 0.05])
            elif self.attack_type == "SIGNAL_JAMMING":
                # Rapid altitude drop to zero
                self.altitude = max(0.0, self.altitude - 40.0)
                self.speed = 0.5
        else:
            # Normal circular patrol flight pattern
            angle = (self.sequence * 0.05) % (2 * math.pi)
            self.lat += 0.0002 * math.cos(angle)
            self.lng += 0.0002 * math.sin(angle)
            self.speed = random.uniform(15.0, 22.0)
            self.altitude = random.uniform(150.0, 200.0)

    def send_telemetry(self):
        self.update_position()
        packet = {
            "drone_id": self.drone_id,
            "latitude": round(self.lat, 6),
            "longitude": round(self.lng, 6),
            "altitude": round(self.altitude, 2),
            "speed": round(self.speed, 2),
            "battery": round(self.battery, 1),
            "packet_sequence": self.sequence
        }

        try:
            resp = requests.post(API_URL, json=packet, headers=HEADERS, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("is_anomaly"):
                    print(f"🚨 [ALERT] {self.drone_id} -> ANOMALY DETECTED! Threat Level: {data.get('threat_level')}/10 | Type: {data.get('attack_type')}")
                else:
                    print(f"🟢 [NOMINAL] {self.drone_id} -> Lat: {packet['latitude']}, Lng: {packet['longitude']}, Alt: {packet['altitude']}m, Speed: {packet['speed']}m/s")
            else:
                print(f"⚠️ [HTTP {resp.status_code}] {self.drone_id} -> {resp.text}")
        except Exception as e:
            print(f"❌ [CONNECT ERROR] {self.drone_id} -> {e}")

def run_drone_loop(drone: DroneSimulator):
    while True:
        drone.send_telemetry()
        time.sleep(1.5)

def main():
    print("==========================================================")
    print("🛸 SWARMGUARD-AI: MULTI-DRONE SWARM ATTACK SIMULATION 🛸")
    print("==========================================================")
    print("Configuring 12 Autonomous Swarm Drones...")
    
    drones = []
    for i in range(1, 13):
        drone_id = f"DRONE-ALPHA-{i:02d}"
        offset_x = random.uniform(-0.02, 0.02)
        offset_y = random.uniform(-0.02, 0.02)
        drones.append(DroneSimulator(drone_id, offset_x, offset_y))

    # Launch drone telemetry threads
    executor = ThreadPoolExecutor(max_workers=15)
    for drone in drones:
        executor.submit(run_drone_loop, drone)

    # Attack Controller Loop
    time.sleep(5)
    print("\n⚔️ ATTACK CONTROLLER ACTIVATED: Will trigger random cyber-attacks every 20s...\n")
    while True:
        time.sleep(20)
        victim = random.choice(drones)
        attack = random.choice(["GPS_SPOOFING", "SIGNAL_JAMMING"])
        print(f"\n💥 [CYBER ATTACK LAUNCHED] -> Injecting {attack} into {victim.drone_id}!\n")
        victim.under_attack = True
        victim.attack_type = attack
        
        # Attack lasts for 10 seconds before recovering
        time.sleep(10)
        print(f"\n🛡️ [COUNTERMEASURE SUCCESSFUL] -> {victim.drone_id} recovered to safe mode.\n")
        victim.under_attack = False
        victim.attack_type = None

if __name__ == "__main__":
    main()
