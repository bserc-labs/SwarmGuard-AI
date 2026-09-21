"""Swarm attack simulator -- drives the live demo against a running backend.

Two things this has to get right that the previous version did not:

1. `/telemetry/ingest` is behind `require_permission(TELEMETRY_INGEST)`, so
   every packet needs an operator bearer token. The old script sent none and
   took a 401 on every single request.
2. The device API key is a real secret now. `config.py` rejects any value in
   KNOWN_PUBLIC_SECRETS, and the string this script used to hardcode
   ("SWARMGUARD_DRONE_DEFENSE_SECRET_2026") is on that list -- so it could not
   have matched a running server's key even if auth had passed. It is read
   from the environment instead.

Usage:
    export SWARMGUARD_USER=admin
    export SWARMGUARD_PASSWORD=...
    export DRONE_API_KEY=...            # must match the backend's
    python simulate_attack.py
"""

import math
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

BASE_URL = os.environ.get("SWARMGUARD_API", "http://localhost:8000")
API_URL = f"{BASE_URL}/telemetry/ingest"
LOGIN_URL = f"{BASE_URL}/auth/login"

USERNAME = os.environ.get("SWARMGUARD_USER", "admin")
PASSWORD = os.environ.get("SWARMGUARD_PASSWORD")
API_KEY = os.environ.get("DRONE_API_KEY")

# Base coordinates around a defense sector (e.g. 34.0522, -118.2437)
BASE_LAT = 34.0522
BASE_LNG = -118.2437

# Metres per degree of latitude, and the interval between packets. Used to keep
# reported speed consistent with actual GPS motion.
DEG_LAT_METERS = 111_320.0
TICK_SECONDS = 1.5

# Populated by authenticate(); every worker thread reads it.
HEADERS: dict[str, str] = {}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def authenticate() -> dict[str, str]:
    """Exchange operator credentials for a bearer token.

    Exits rather than continuing on failure: without a token every packet
    would 401, which previously looked like a working simulator printing
    warnings rather than a broken one.
    """
    if not PASSWORD:
        sys.exit("SWARMGUARD_PASSWORD is not set. Export the operator password first.")
    if not API_KEY:
        sys.exit("DRONE_API_KEY is not set. Export the same value the backend runs with.")

    try:
        # The login route is an OAuth2 password form, not a JSON body.
        resp = requests.post(
            LOGIN_URL,
            data={"username": USERNAME, "password": PASSWORD},
            timeout=10,
        )
    except requests.RequestException as e:
        sys.exit(f"Could not reach {LOGIN_URL}: {e}")

    if resp.status_code != 200:
        sys.exit(f"Login failed for '{USERNAME}' [HTTP {resp.status_code}]: {resp.text}")

    token = resp.json().get("access_token")
    if not token:
        sys.exit(f"Login succeeded but returned no access_token: {resp.text}")

    print(f"✅ Authenticated as '{USERNAME}'")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "x-drone-api-key": API_KEY,
    }


class DroneSimulator:
    def __init__(self, drone_id: str, offset_x: float, offset_y: float):
        self.drone_id = drone_id
        self.lat = BASE_LAT + offset_x
        self.lng = BASE_LNG + offset_y
        self.altitude = random.uniform(100.0, 300.0)
        self.speed = random.uniform(12.0, 25.0)
        self.battery = 100.0
        self.heading = random.uniform(0.0, 360.0)
        self.satellites = random.randint(10, 15)
        self.sequence = 0
        self.under_attack = False
        self.attack_type = None
        # The simulated autopilot's boot clock: monotonic, never wall time,
        # exactly like MAVLink time_boot_ms.
        self.boot_monotonic = time.monotonic()

    def update_position(self):
        self.sequence += 1
        self.battery = max(10.0, self.battery - 0.05)

        if self.under_attack:
            if self.attack_type == "GPS_SPOOFING":
                # A spoofer forges the *position*, not the airframe's inertial
                # sensors. So the reported speed stays plausible -- the
                # accelerometers still see a drone flying at 15 m/s -- while
                # the position teleports. That contradiction between GNSS and
                # airframe is the actual signature, and it is exactly what
                # KinematicGuard's gps_airframe_speed_mismatch check measures.
                self.lat += random.choice([-0.05, 0.05])
                self.lng += random.choice([-0.05, 0.05])
                self.speed = max(0.0, 15.0 + random.uniform(-1.0, 1.0))
                self.satellites = random.randint(0, 3)
                self.heading = (self.heading + random.uniform(-90, 90)) % 360
            elif self.attack_type == "SIGNAL_JAMMING":
                # Rapid altitude drop to zero
                self.altitude = max(0.0, self.altitude - 40.0)
                self.speed = 0.5
                self.satellites = random.randint(0, 4)
        else:
            # Normal circular patrol flight pattern.
            #
            # Altitude and speed *drift* rather than being re-drawn each tick.
            # Re-randomising altitude across a 50 m band every 1.5 s implies a
            # 33 m/s climb rate, which is beyond what a multirotor can do --
            # the kinematic guard would (correctly) flag this "nominal" flight
            # as anomalous. A simulator has to respect the same physics the
            # detector checks, or the demo is a stream of false alarms.
            angle = (self.sequence * 0.05) % (2 * math.pi)
            step_deg = 0.0002
            self.lat += step_deg * math.cos(angle)
            self.lng += step_deg * math.sin(angle)

            # Report the speed the aircraft is actually flying, plus a little
            # sensor noise. On a healthy aircraft GNSS-derived speed and
            # airframe-reported speed agree; the whole spoofing signature is
            # that they stop agreeing, so the nominal case has to show them
            # agreeing or the contrast means nothing.
            true_ground_speed = (step_deg * DEG_LAT_METERS) / TICK_SECONDS
            self.speed = max(0.0, true_ground_speed + random.uniform(-1.0, 1.0))
            self.altitude = _clamp(self.altitude + random.uniform(-3.0, 3.0), 120.0, 220.0)
            self.heading = (self.heading + random.uniform(-5, 5)) % 360
            self.satellites = random.randint(10, 15)

    def send_telemetry(self):
        self.update_position()
        packet = {
            "drone_id": self.drone_id,
            "latitude": round(self.lat, 6),
            "longitude": round(self.lng, 6),
            "altitude": round(self.altitude, 2),
            "speed": round(self.speed, 2),
            "heading": round(self.heading, 2),
            "battery": round(self.battery, 1),
            "flight_mode": "AUTO",
            "armed_status": True,
            "satellites": self.satellites,
            "packet_sequence": self.sequence,
            "sample_time_ms": int((time.monotonic() - self.boot_monotonic) * 1000),
        }

        try:
            resp = requests.post(API_URL, json=packet, headers=HEADERS, timeout=3)
            if resp.status_code == 200:
                state = "⚔️  UNDER ATTACK" if self.under_attack else "🟢 NOMINAL"
                print(
                    f"{state} {self.drone_id} -> "
                    f"Lat: {packet['latitude']}, Lng: {packet['longitude']}, "
                    f"Alt: {packet['altitude']}m, Speed: {packet['speed']}m/s, "
                    f"Sats: {packet['satellites']}"
                )
            elif resp.status_code == 401:
                print(f"🔒 [401] {self.drone_id} -> token rejected or expired.")
            elif resp.status_code == 403:
                print(f"🔒 [403] {self.drone_id} -> DRONE_API_KEY does not match the backend.")
            else:
                print(f"⚠️ [HTTP {resp.status_code}] {self.drone_id} -> {resp.text}")
        except Exception as e:
            print(f"❌ [CONNECT ERROR] {self.drone_id} -> {e}")


def run_drone_loop(drone: DroneSimulator):
    while True:
        drone.send_telemetry()
        time.sleep(TICK_SECONDS)


def main():
    global HEADERS

    print("==========================================================")
    print("🛸 SWARMGUARD-AI: MULTI-DRONE SWARM ATTACK SIMULATION 🛸")
    print("==========================================================")

    HEADERS = authenticate()

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
