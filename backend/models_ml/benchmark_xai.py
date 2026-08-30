import sys

sys.path.append("/Users/aryannegi/Desktop/SwarmGuard-AI-Bserc/backend")

import os
import time

import numpy as np
import pandas as pd
import psutil

from models_ml.data_generator import generate_synthetic_telemetry
from services.ai_service import ai_service
from services.explanation_service import explanation_service


def run_xai_benchmark():
    print("--- Starting SHAP XAI Benchmark ---")
    
    # 1. Warmup and Engine Loading
    t0 = time.perf_counter()
    ai_service._lazy_load_model()
    t_ai_load = time.perf_counter() - t0
    
    t0 = time.perf_counter()
    explanation_service._lazy_load_engine()
    t_engine_load = time.perf_counter() - t0
    
    engine = explanation_service.engine
    
    print(f"AI Model Load Time : {t_ai_load*1000:.2f} ms")
    print(f"SHAP Engine Init Time: {t_engine_load*1000:.2f} ms")
    print(f"Explainer Type       : {engine.explainer_type}")
    
    # 2. Generate test payloads
    df = generate_synthetic_telemetry(num_drones=1, records_per_drone=100)
    history = df.to_dict(orient="records")
    
    # 3. Single Prediction XAI Benchmark
    latencies = []
    
    print("\nRunning 50 single-explanation iterations...")
    for i in range(10, 60):
        window = history[i-5:i]
        
        t0 = time.perf_counter()
        result = explanation_service.explain_prediction(window)
        t_exp = time.perf_counter() - t0
        
        if "error" in result:
            print(f"Error in iteration {i}: {result['error']}")
            continue
            
        latencies.append(t_exp * 1000) # milliseconds
        
    latencies = np.array(latencies)
    print("\n--- XAI Latency Results (ms) ---")
    print(f"Average: {latencies.mean():.2f} ms")
    print(f"Median : {np.median(latencies):.2f} ms")
    print(f"p95    : {np.percentile(latencies, 95):.2f} ms")
    print(f"p99    : {np.percentile(latencies, 99):.2f} ms")
    
    # Check Feature Ordering Consistency
    test_window = history[90:95]
    res = explanation_service.explain_prediction(test_window)
    if "error" not in res:
        ranked = res["explanation"]["ranked_features"]
        print("\n--- Feature Ranking Verification ---")
        print(f"Top Feature: {ranked[0]['feature']} (Contribution: {ranked[0]['magnitude']:.4f})")
        print(f"Analyst Summary: \n{res['explanation']['summary']}")
        
    # Batch Explanation Throughput Check (Simulate batch of 10)
    print("\n--- Batch Explanation Latency ---")
    df_features = ai_service.engineer.transform(pd.DataFrame(history[50:80]))
    features = ai_service.scaler.transform(df_features[ai_service.engineer.get_feature_columns()].values)
    t0 = time.perf_counter()
    batch_res = engine.explain(features)
    t_batch = time.perf_counter() - t0
    print(f"Processed 30 records in {t_batch*1000:.2f} ms. Avg per record: {(t_batch*1000)/30:.2f} ms")
        
    # Memory Overhead
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    print(f"\nMemory Usage (Including XAI): {mem_info.rss / 1024 / 1024:.2f} MB")
    
if __name__ == "__main__":
    run_xai_benchmark()
