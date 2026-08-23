import pandas as pd
import numpy as np
import random
import os

def generate_synthetic_telemetry(num_drones=5, records_per_drone=1000):
    """
    Generates a synthetic telemetry dataset for CI/CD and pipeline testing.
    Includes nominal flights and explicit anomaly injection.
    """
    np.random.seed(42)
    random.seed(42)
    
    data = []
    
    for drone_id_num in range(1, num_drones + 1):
        drone_id = f"DRONE_{drone_id_num}"
        
        # Initial states
        lat = 37.7749 + (random.uniform(-0.01, 0.01))
        lon = -122.4194 + (random.uniform(-0.01, 0.01))
        alt = 50.0
        battery = 100.0
        heading = 0.0
        
        for seq in range(1, records_per_drone + 1):
            is_anomaly = False
            
            # 5% chance of injecting an anomaly in the last half of the flight
            if seq > records_per_drone // 2 and random.random() < 0.05:
                is_anomaly = True
                
            if is_anomaly:
                anomaly_type = random.choice(["gps_spoof", "battery_drain", "kinematic"])
                if anomaly_type == "gps_spoof":
                    lat += random.uniform(-0.05, 0.05)
                    lon += random.uniform(-0.05, 0.05)
                    satellites = random.randint(0, 3)
                    speed = random.uniform(0, 5)
                elif anomaly_type == "battery_drain":
                    battery -= random.uniform(2.0, 5.0)
                    speed = random.uniform(5, 15)
                    satellites = 12
                elif anomaly_type == "kinematic":
                    speed = random.uniform(40, 60) # Impossible speed for standard quad
                    alt += random.uniform(-50, 50)
                    satellites = 12
            else:
                # Nominal random walk
                lat += random.uniform(-0.0001, 0.0001)
                lon += random.uniform(-0.0001, 0.0001)
                alt += random.uniform(-0.5, 0.5)
                alt = max(0, min(120, alt))
                speed = random.uniform(5, 15)
                battery -= 0.05
                satellites = random.randint(10, 15)
            
            heading = (heading + random.uniform(-5, 5)) % 360
            battery = max(0, battery)
            
            data.append({
                "drone_id": drone_id,
                "packet_sequence": seq,
                "latitude": lat,
                "longitude": lon,
                "altitude": alt,
                "speed": speed,
                "heading": heading,
                "battery": battery,
                "flight_mode": "AUTO",
                "armed_status": True,
                "satellites": satellites,
                "label": 1 if is_anomaly else 0 # 1 = Anomaly for dataset evaluation purposes
            })
            
    df = pd.DataFrame(data)
    
    # Save to data directory
    output_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data"))
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "telemetry_dataset_v1.csv")
    df.to_csv(output_path, index=False)
    print(f"Generated synthetic telemetry dataset with {len(df)} records at {output_path}")
    return df

if __name__ == "__main__":
    generate_synthetic_telemetry()
