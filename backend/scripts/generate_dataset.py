import csv
import random
import os

def generate_dataset(output_path="backend/data/swarmguard_training_dataset.csv", total_rows=2500):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    headers = [
        "drone_id", "latitude", "longitude", "altitude", "speed", "battery",
        "packet_sequence", "speed_alt_ratio", "battery_drain_rate", "attack_type", "is_anomaly"
    ]

    base_lat = 34.0522
    base_lon = -118.2437

    rows = []
    
    # 1. Normal Flights (1500 rows)
    for i in range(1500):
        d_id = f"drone_{random.randint(1, 10)}"
        lat = round(base_lat + random.uniform(-0.02, 0.02), 6)
        lon = round(base_lon + random.uniform(-0.02, 0.02), 6)
        alt = round(random.uniform(50.0, 300.0), 2)
        speed = round(random.uniform(5.0, 25.0), 2)
        battery = round(random.uniform(60.0, 100.0), 2)
        pkt_seq = i + 1
        speed_alt_ratio = round(speed / (alt + 1.0), 4)
        battery_drain_rate = round(100.0 - battery, 2)
        
        rows.append([d_id, lat, lon, alt, speed, battery, pkt_seq, speed_alt_ratio, battery_drain_rate, "NORMAL", 0])

    # 2. GPS Spoofing (250 rows)
    for i in range(250):
        d_id = f"drone_{random.randint(1, 10)}"
        lat = round(base_lat + random.uniform(0.1, 0.5), 6)  # Sudden coordinate jump
        lon = round(base_lon + random.uniform(0.1, 0.5), 6)
        alt = round(random.uniform(100.0, 400.0), 2)
        speed = round(random.uniform(80.0, 160.0), 2)       # Impossible velocity
        battery = round(random.uniform(40.0, 90.0), 2)
        pkt_seq = 1500 + i + 1
        speed_alt_ratio = round(speed / (alt + 1.0), 4)
        battery_drain_rate = round(100.0 - battery, 2)
        
        rows.append([d_id, lat, lon, alt, speed, battery, pkt_seq, speed_alt_ratio, battery_drain_rate, "GPS_SPOOFING", 1])

    # 3. RF Jamming (250 rows)
    for i in range(250):
        d_id = f"drone_{random.randint(1, 10)}"
        lat = round(base_lat + random.uniform(-0.01, 0.01), 6)
        lon = round(base_lon + random.uniform(-0.01, 0.01), 6)
        alt = round(random.uniform(0.0, 15.0), 2)             # Rapid altitude loss
        speed = round(random.uniform(0.0, 2.0), 2)             # Loss of thrust
        battery = round(random.uniform(1.0, 15.0), 2)          # Severe power drop
        pkt_seq = 1750 + i + 1
        speed_alt_ratio = round(speed / (alt + 1.0), 4)
        battery_drain_rate = round(100.0 - battery, 2)
        
        rows.append([d_id, lat, lon, alt, speed, battery, pkt_seq, speed_alt_ratio, battery_drain_rate, "JAMMING", 1])

    # 4. DoS Attack (250 rows)
    for i in range(250):
        d_id = f"drone_{random.randint(1, 10)}"
        lat = round(base_lat + random.uniform(-0.02, 0.02), 6)
        lon = round(base_lon + random.uniform(-0.02, 0.02), 6)
        alt = round(random.uniform(50.0, 200.0), 2)
        speed = round(random.uniform(30.0, 60.0), 2)
        battery = round(random.uniform(20.0, 70.0), 2)
        pkt_seq = random.randint(10000, 90000)                # Disrupted sequence
        speed_alt_ratio = round(speed / (alt + 1.0), 4)
        battery_drain_rate = round(100.0 - battery, 2)
        
        rows.append([d_id, lat, lon, alt, speed, battery, pkt_seq, speed_alt_ratio, battery_drain_rate, "DOS", 1])

    # 5. Replay Attack (250 rows)
    for i in range(250):
        d_id = f"drone_{random.randint(1, 10)}"
        lat = round(base_lat + 0.005, 6)                      # Repeated static position
        lon = round(base_lon + 0.005, 6)
        alt = 100.0
        speed = 10.0
        battery = 75.0
        pkt_seq = 500                                          # Replayed packet sequence
        speed_alt_ratio = round(speed / (alt + 1.0), 4)
        battery_drain_rate = round(100.0 - battery, 2)
        
        rows.append([d_id, lat, lon, alt, speed, battery, pkt_seq, speed_alt_ratio, battery_drain_rate, "REPLAY_ATTACK", 1])

    random.shuffle(rows)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    print(f"✅ Generated {len(rows)} training records at {output_path}")

if __name__ == "__main__":
    generate_dataset()
