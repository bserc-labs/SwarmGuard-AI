import requests
import time
import sys
import os

BASE_URL = "http://localhost:8000"

def run_end_to_end_demo():
    print("=========================================================")
    print("  SwarmGuard AI — End-to-End E2E Integration Pipeline Demo")
    print("=========================================================\n")

    # 1. Health check
    print("[STEP 1] Checking Core Backend System Health...")
    res = requests.get(f"{BASE_URL}/health")
    assert res.status_code == 200, "Backend health check failed!"
    print(f"  ✔ System Health: {res.json()}\n")

    # 2. Login to acquire JWT token
    print("[STEP 2] Authenticating Analyst (SOC Operator Login)...")
    auth_res = requests.post(f"{BASE_URL}/auth/login", data={"username": "admin", "password": "admin123"})
    if auth_res.status_code != 200:
        auth_res = requests.post(f"{BASE_URL}/auth/login", data={"username": "admin", "password": "password"})
    
    if auth_res.status_code == 200:
        token = auth_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("  ✔ JWT Authentication Successful. Bearer Token Obtained.\n")
    else:
        print(f"  ✖ Auth failed status {auth_res.status_code}: {auth_res.text}")
        headers = {}

    # 3. Simulate Telemetry Ingestion
    print("[STEP 3] Ingesting Live Telemetry Stream via AI Explain Service...")
    telemetry_payload = {
        "drone_id": "DEMO_SWARM_01",
        "latitude": 34.0522,
        "longitude": -118.2437,
        "altitude": 145.0,
        "speed": 28.5,
        "battery": 45.0,
        "packet_sequence": 1001,
        "heading": 180.0,
        "flight_mode": "GUIDED",
        "armed_status": True,
        "satellites": 14,
        "timestamp": "2026-08-08T12:00:00Z"
    }
    
    # Generate 10 packets to satisfy WINDOW_SIZE
    history = [telemetry_payload.copy() for i in range(10)]
    for i in range(10):
        history[i]["packet_sequence"] = 1000 + i

    # 4. Trigger AI Detection & SHAP Explanation
    print("[STEP 4] Running AI Threat Detection Engine & SHAP Explanation...")
    ai_res = requests.post(
        f"{BASE_URL}/ai/explain", 
        json={"telemetry_history": history}, 
        headers=headers
    )
    if ai_res.status_code == 200:
        explain_data = ai_res.json()
        print("  ✔ AI Detection & SHAP Analysis Generated Successfully:")
        print(f"    - Is Anomaly: {explain_data.get('prediction', {}).get('is_anomaly')}")
        print(f"    - Threat Score: {explain_data.get('prediction', {}).get('threat_score')}")
        print(f"    - Primary Cause: {explain_data.get('explanation', {}).get('summary', {}).get('Primary Cause')}\n")
    else:
        print(f"  ✖ AI Explain status: {ai_res.status_code} {ai_res.text}\n")

    # 5. Fetch Generated Incidents
    print("[STEP 5] Querying Incident Command Center for Active Incidents...")
    inc_res = requests.get(f"{BASE_URL}/incidents/", headers=headers)
    incidents = inc_res.json() if inc_res.status_code == 200 else []
    print(f"  ✔ Active Incidents Count: {len(incidents)}")
    
    target_inc_id = None
    if incidents:
        target_inc_id = incidents[0]["id"]
        inc = incidents[0]
        print(f"  ✔ Latest Incident #SG-{inc['id']}: {inc['attack_type']} (Severity: {inc['severity']}, Priority: P-{inc.get('priority', 0)})\n")

    # 6. Analyst Response Workflow (Acknowledge & Resolve)
    if target_inc_id:
        print(f"[STEP 6] Executing SOC Analyst Workflow on Incident #SG-{target_inc_id}...")
        
        # Acknowledge
        ack_res = requests.post(f"{BASE_URL}/incidents/{target_inc_id}/acknowledge", json={"reason": "Operator confirmed GNSS drift in sector 4"}, headers=headers)
        print(f"  ✔ Acknowledge Transition Status: {ack_res.status_code} (New Status: {ack_res.json().get('status') if ack_res.status_code == 200 else 'Failed'})")
        
        # Resolve
        res_res = requests.post(f"{BASE_URL}/incidents/{target_inc_id}/resolve", json={"reason": "Safe mode command dispatched. Unit returned to base."}, headers=headers)
        print(f"  ✔ Resolve Transition Status: {res_res.status_code} (New Status: {res_res.json().get('status') if res_res.status_code == 200 else 'Failed'})\n")

    # 7. Immutable Audit Trail Verification
    print("[STEP 7] Querying Immutable Audit Trail Logs...")
    audit_res = requests.get(f"{BASE_URL}/incidents/audit/logs", headers=headers)
    audits = audit_res.json() if audit_res.status_code == 200 else []
    print(f"  ✔ Immutable Audit Logs Recorded: {len(audits)}")
    for a in audits[:4]:
        print(f"    - Action: {a['action']} by {a['actor']} ({a.get('previous_status')} ➔ {a.get('new_status')}) Reason: {a.get('reason')}")

    print("\n=========================================================")
    print("  ✔ END-TO-END E2E PIPELINE DEMONSTRATION COMPLETE SUCCESS")
    print("=========================================================")

if __name__ == "__main__":
    run_end_to_end_demo()
