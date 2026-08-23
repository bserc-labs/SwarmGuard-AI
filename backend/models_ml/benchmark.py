import sys
sys.path.append("/Users/aryannegi/Desktop/SwarmGuard-AI-Bserc/backend")

import time
import psutil
import os
import numpy as np
from services.ai_service import ai_service
from models_ml.data_generator import generate_synthetic_telemetry

def run_benchmark():
    print("--- Starting AI Benchmark ---")
    
    # 1. Loading Benchmark
    t0 = time.perf_counter()
    ai_service._lazy_load_model()
    t_load = time.perf_counter() - t0
    print(f"Model Loading Time: {t_load*1000:.2f} ms")
    
    # 2. Generate test payloads
    df = generate_synthetic_telemetry(num_drones=1, records_per_drone=100)
    history = df.to_dict(orient="records")
    
    # 3. Inference Benchmark
    latencies = []
    
    for i in range(10, 100):
        # Provide a rolling window of size 5
        window = history[i-5:i]
        
        t0 = time.perf_counter()
        result = ai_service.predict(window)
        t_inf = time.perf_counter() - t0
        latencies.append(t_inf * 1000) # milliseconds
        
    latencies = np.array(latencies)
    print("\n--- Latency Results (ms) ---")
    print(f"Average: {latencies.mean():.2f} ms")
    print(f"Median : {np.median(latencies):.2f} ms")
    print(f"p95    : {np.percentile(latencies, 95):.2f} ms")
    print(f"p99    : {np.percentile(latencies, 99):.2f} ms")
    print(f"Min    : {latencies.min():.2f} ms")
    print(f"Max    : {latencies.max():.2f} ms")
    
    # Throughput
    avg_s = latencies.mean() / 1000.0
    throughput = 1.0 / avg_s if avg_s > 0 else 0
    print(f"\nThroughput: {throughput:.0f} predictions / second")
    
    # Memory
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    print(f"\nMemory Usage: {mem_info.rss / 1024 / 1024:.2f} MB")
    
if __name__ == "__main__":
    run_benchmark()
