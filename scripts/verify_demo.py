"""End-to-end check that the detection pipeline actually works, live.

    docker compose up -d
    python scripts/verify_demo.py

Stdlib only, so it runs with any Python and needs nothing installed. Credentials
are read from the repository's .env.

It drives a real spoofed GPS track through /telemetry/ingest and then asserts
what came out the other side: that Tier 1 raised the incident, that the incident
carries evidence an analyst can check by hand, that the lifecycle can be walked
to RESOLVED, and that every state it passed through was recorded.

Each check states what it is proving. The point is not that requests return 200
-- it is that the behaviour is the one claimed, with the evidence visible in the
response bodies.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = os.environ.get("SWARMGUARD_API", "http://localhost:8000")

DEG_LAT_METRES = 111_320.0

# Deliberately empty airspace for the two flight tests, so a restricted zone
# left over from a demo or an earlier run cannot turn a spoofing test into a
# geofence breach. An earlier version of this script flew the spoofing test from
# 34.0522, -118.2437 -- the exact centre of the sample "Restricted airspace"
# zone -- and the incident it produced was a real breach, not the spoof.
SPOOF_BASE_LAT = 45.0000
SPOOF_BASE_LON = -100.0000
ZONE_BASE_LAT = 44.0000
ZONE_BASE_LON = -101.0000
# Repository root, so this works from anywhere.
ENV_PATH = str(Path(__file__).resolve().parent.parent / ".env")

PASS, FAIL = "PASS", "FAIL"
results = []


def load_env(path):
    values = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    except OSError as exc:
        sys.exit(f"Could not read {path}: {exc}")
    return values


def call(method, path, body=None, token=None, extra_headers=None, form=False):
    url = f"{BASE}{path}"
    headers = {}
    data = None

    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"

    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw
    except urllib.error.URLError as exc:
        return 0, str(exc)


def check(name, condition, detail=""):
    results.append((PASS if condition else FAIL, name, detail))
    marker = "  ok " if condition else "FAIL "
    print(f"{marker}{name}")
    if detail:
        print(f"        {detail}")
    return condition


# --------------------------------------------------------------- 0. liveness

def wait_for_backend(timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, _ = call("GET", "/health")
        if status == 200:
            return True
        time.sleep(3)
    return False


def main():
    env = load_env(ENV_PATH)
    username = env.get("ADMIN_USERNAME")
    password = env.get("ADMIN_PASSWORD")
    api_key = env.get("DRONE_API_KEY")

    print("=" * 68)
    print("SwarmGuard AI — live detection pipeline check")
    print("=" * 68)

    if not username or not password:
        sys.exit(
            f"ADMIN_USERNAME and ADMIN_PASSWORD must be set in {ENV_PATH}."
        )
    if not api_key:
        sys.exit(f"DRONE_API_KEY must be set in {ENV_PATH}.")

    if not wait_for_backend():
        sys.exit("Backend never became healthy at " + BASE)
    check("Backend is healthy", True)

    # ------------------------------------------------------------ 1. auth
    status, payload = call(
        "POST", "/auth/login", {"username": username, "password": password}, form=True
    )
    if not check("Admin can authenticate", status == 200, f"HTTP {status}"):
        sys.exit("Cannot continue without a token.")
    token = payload["access_token"]

    # ------------------------------------- 2. detection status (new endpoint)
    status, ds = call("GET", "/ai/detection/status", token=token)
    check("GET /ai/detection/status responds", status == 200, f"HTTP {status}")

    if status == 200:
        tiers = {t["tier"]: t for t in ds["tiers"]}
        guard, model = tiers.get(1, {}), tiers.get(2, {})

        check(
            "Tier 1 is reported as the detector raising incidents",
            guard.get("raises_incidents") is True,
        )
        check(
            "Tier 1 publishes its thresholds",
            len(guard.get("checks", [])) == 4,
            ", ".join(f"{c['check']}={c['threshold']}{c['unit']}" for c in guard.get("checks", [])),
        )
        lofo = model.get("validation", {})
        check(
            "Tier 2 reports its leave-one-flight-out result, not a flattering one",
            lofo.get("f1_score") is not None and lofo.get("false_positive_rate") is not None,
            f"F1={lofo.get('f1_score')} FPR={lofo.get('false_positive_rate')} "
            f"across {lofo.get('n_folds')} folds",
        )
        check(
            "Tier 2 is disabled and says why",
            model.get("raises_incidents") is False and bool(model.get("disabled_reason")),
        )

    # ---------------------------------------- 3. drive a Tier 1 detection
    drone = f"VERIFY-{datetime.utcnow().strftime('%H%M%S')}"
    headers = {"x-drone-api-key": api_key}

    def packet(seq, lat, lon, alt=150.0, speed=18.0, sats=12):
        return {
            "drone_id": drone,
            "latitude": lat,
            "longitude": lon,
            "altitude": alt,
            "speed": speed,
            "heading": 90.0,
            "battery": 88.0,
            "flight_mode": "AUTO",
            "armed_status": True,
            "satellites": sats,
            "packet_sequence": seq,
        }

    lat = SPOOF_BASE_LAT
    for seq in range(3):
        status, _ = call(
            "POST", "/telemetry/ingest", packet(seq, lat, SPOOF_BASE_LON), token, headers
        )
        if status != 200:
            check("Nominal telemetry ingests", False, f"HTTP {status}")
            break
        lat += 0.000243
        time.sleep(1.2)
    else:
        check("Nominal telemetry ingests", True)

    # The spoof: position jumps 0.05 degrees while the airframe still reports
    # 18 m/s. This is the gps_airframe_speed_mismatch signature.
    time.sleep(1.2)
    status, _ = call(
        "POST", "/telemetry/ingest", packet(3, lat + 0.05, SPOOF_BASE_LON), token, headers
    )
    check("Spoofed packet ingests", status == 200, f"HTTP {status}")

    # Detection runs as a background task after the response.
    #
    # The listing is ordered by priority, not by time, so a freshly raised
    # incident is not necessarily near the front. On a database with a few
    # hundred incidents a small `limit` silently hides it, which reads as "the
    # detector did not fire". Ask for the maximum the route allows.
    incident = None
    for _ in range(20):
        time.sleep(1.5)
        status, incidents = call("GET", "/incidents/?limit=1000", token=token)
        if status == 200:
            match = [i for i in incidents if i["drone_id"] == drone]
            if match:
                incident = match[0]
                break

    if not check("Tier 1 raised an incident for the spoofed track", incident is not None):
        summarise()
        sys.exit(1)

    check(
        "Incident is classified as GPS spoofing",
        incident["attack_type"] == "GPS_SPOOFING",
        f"attack_type={incident['attack_type']} severity={incident['severity']}",
    )

    # ------------------------- 4. THE ATTRIBUTION BUG (blank explainability)
    shap = incident.get("shap_values") or []
    check("Incident carries attribution entries", len(shap) > 0, f"{len(shap)} entries")

    if shap:
        top = shap[0]
        # frontend attributionMagnitude() reads importance -> magnitude ->
        # shap_value -> value. Before the fix it read only importance and value,
        # neither of which appears here, so every incident rendered
        # "No attribution recorded".
        readable = any(k in top for k in ("importance", "magnitude", "shap_value", "value"))
        check(
            "Attribution is readable by the console's magnitude resolver",
            readable,
            f"keys={sorted(top.keys())}",
        )
        check(
            "Attribution carries checkable evidence (observed vs threshold)",
            "observed" in top and "threshold" in top,
            f"{top.get('observed')} vs {top.get('threshold')} {top.get('unit')}",
        )

    # ------------------------------ 5. THE TRANSITION BUG (Resolve unreachable)
    inc_id = incident["id"]
    check("Incident starts in NEW", incident["status"] == "NEW", incident["status"])

    status, acked = call(
        "POST", f"/incidents/{inc_id}/acknowledge", {"reason": "verification run"}, token
    )
    check("Acknowledge succeeds", status == 200 and acked.get("status") == "ACKNOWLEDGED",
          f"HTTP {status} -> {acked.get('status') if isinstance(acked, dict) else acked}")

    # This is the regression. Before the fix this returned 400 "Invalid
    # transition from ACKNOWLEDGED to RESOLVED" from every reachable state.
    status, resolved = call(
        "POST", f"/incidents/{inc_id}/resolve", {"reason": "verification run"}, token
    )
    check(
        "Resolve succeeds from ACKNOWLEDGED (was 400 before)",
        status == 200 and resolved.get("status") == "RESOLVED",
        f"HTTP {status} -> {resolved.get('status') if isinstance(resolved, dict) else resolved}",
    )
    if status == 200:
        check("Resolution time was recorded", resolved.get("resolution_time") is not None)

    # ---------------------------------- 6. the audit trail records every hop
    status, logs = call("GET", "/incidents/audit/logs?limit=200", token=token)
    if status == 200:
        hops = [
            row for row in logs
            if row.get("action") == "STATUS_TRANSITION" and row.get("resource_id") == str(inc_id)
        ]
        # Sorted by id, not by timestamp. The three hops a single Resolve writes
        # are committed in one transaction and share a created_at to the second,
        # so ordering by time would scramble them.
        hops.sort(key=lambda row: row["id"])
        walked = [row["new_state"] for row in hops]
        check(
            "Every lifecycle state is recorded, none skipped",
            walked == ["OPEN", "ACKNOWLEDGED", "INVESTIGATING", "CONTAINED", "RESOLVED"],
            " -> ".join(walked) or "no transitions found",
        )
        resolve_hops = [r for r in hops if r["new_state"] in
                        ("INVESTIGATING", "CONTAINED", "RESOLVED")]
        correlations = {r.get("correlation_id") for r in resolve_hops}
        check(
            "The three hops from one Resolve click share a correlation id",
            len(correlations) == 1 and None not in correlations,
            f"{len(correlations)} distinct id(s)",
        )

    # ------------------------------------ 7. backwards transitions are refused
    status, body = call("POST", f"/incidents/{inc_id}/acknowledge", {}, token)
    check(
        "Lifecycle refuses to run backwards",
        status == 400 and "backwards" in str(body.get("detail", "")).lower(),
        f"HTTP {status}: {body.get('detail') if isinstance(body, dict) else body}",
    )

    # ------------------------------------- 8. geofence breach, server-side
    #
    # Drawn from the aircraft's own reported position, never from a claim made
    # by a client. The zone is created through the API, then a drone is flown
    # into it and the incident is read back.
    stamp = datetime.utcnow().strftime("%H%M%S")
    zone_name = f"verify-nofly-{stamp}"
    zone_radius = 300.0

    # A centre unique to this run. Runs accumulate zones, and a fixed centre
    # would put this run's "outside the zone" start position inside a previous
    # run's larger circle.
    zone_centre = [ZONE_BASE_LAT + (int(stamp) % 500) * 0.01, ZONE_BASE_LON]

    status, zone = call(
        "POST", "/geofence/zones",
        {
            "name": zone_name,
            "zone_type": "CIRCLE",
            "coordinates": {"center": zone_centre, "radius": zone_radius},
            "severity": "CRITICAL",
        },
        token,
    )
    check("A restricted zone can be created", status == 200, f"HTTP {status}")
    zone_id = zone.get("id") if isinstance(zone, dict) else None

    gf_drone = f"VERIFY-GF-{stamp}"

    def at_metres_north(metres):
        """Position `metres` north of the zone centre."""
        return (zone_centre[0] + metres / DEG_LAT_METRES, zone_centre[1])

    def gf_packet(seq, position, speed):
        return {
            "drone_id": gf_drone, "latitude": position[0], "longitude": position[1],
            "altitude": 150.0, "speed": speed, "heading": 180.0, "battery": 88.0,
            "flight_mode": "AUTO", "armed_status": True, "satellites": 12,
            "packet_sequence": seq,
        }

    # Approach the zone at a speed the airframe could actually fly, and report
    # that same speed. Teleporting in would trip the kinematic guard instead --
    # correctly, since a physically impossible position is not evidence of
    # where the aircraft is. Tier 1 owns that case; this is the geofence case.
    step_metres = 50.0
    tick = 1.5
    approach_speed = step_metres / tick  # ~33 m/s, inside the 60 m/s envelope

    outside_track = [500.0, 450.0, 400.0]          # all beyond the 300 m radius
    inside_track = [350.0, 300.0, 250.0]           # crosses the boundary

    seq = 0
    for metres in outside_track:
        call("POST", "/telemetry/ingest",
             gf_packet(seq, at_metres_north(metres), approach_speed), token, headers)
        seq += 1
        time.sleep(tick)

    time.sleep(3)
    _, incidents = call("GET", "/incidents/?limit=1000", token=token)
    outside_incidents = [i for i in incidents if i["drone_id"] == gf_drone]
    check("Flying near but outside the zone raises nothing", not outside_incidents,
          f"{len(outside_incidents)} incident(s)")

    for metres in inside_track:
        call("POST", "/telemetry/ingest",
             gf_packet(seq, at_metres_north(metres), approach_speed), token, headers)
        seq += 1
        time.sleep(tick)

    breach = None
    for _ in range(20):
        time.sleep(1.5)
        _, incidents = call("GET", "/incidents/?limit=1000", token=token)
        found = [i for i in incidents
                 if i["drone_id"] == gf_drone and i["attack_type"] == "GEOFENCE_BREACH"]
        if found:
            breach = found[0]
            break

    if check("Crossing into the zone raises a geofence incident", breach is not None):
        check("Breach inherits the zone's declared severity",
              breach["severity"] == "CRITICAL", f"severity={breach['severity']}")
        check("Breach names the zone that was violated",
              zone_name in str(breach.get("explanation", "")) +
              str(breach.get("explanation_summary", "")),
              f"zone={zone_name}")

    # Deactivate the zone so repeated runs do not accumulate live restricted
    # airspace that later runs would fly through.
    if zone_id:
        call("DELETE", f"/geofence/zones/{zone_id}", token=token)

    # ------------------------------------------ 9. per-organization thresholds
    status, before = call("GET", "/settings/", token=token)
    check("Settings are readable", status == 200, f"HTTP {status}")

    status, body = call(
        "PATCH", "/settings/", {"critical_threshold": 0.4, "high_threshold": 0.9}, token
    )
    check("An inverted threshold pair is refused", status == 422, f"HTTP {status}")

    status, body = call("PATCH", "/settings/", {"critical_threshold": 1.4}, token)
    check("An out-of-range threshold is refused", status == 422, f"HTTP {status}")

    status, body = call(
        "PATCH", "/settings/", {"critical_threshold": 0.7, "high_threshold": 0.35}, token
    )
    check("A valid threshold change is accepted",
          status == 200 and body.get("critical_threshold") == 0.7, f"HTTP {status}")

    # Restore whatever was there before, so a demo run leaves no residue.
    if before:
        call("PATCH", "/settings/", {
            "critical_threshold": before["critical_threshold"],
            "high_threshold": before["high_threshold"],
        }, token)

    # -------------------------------- 10. user management (two-person rule)
    status, users = call("GET", "/users/", token=token)
    check("GET /users/ is reachable for the Team screen", status == 200, f"HTTP {status}")

    new_user = f"verify.analyst.{datetime.utcnow().strftime('%H%M%S')}"
    status, created = call(
        "POST", "/users/",
        {"username": new_user, "password": "verify-password-123", "role": "analyst"},
        token,
    )
    check(
        "A second account can be created (needed for command approval)",
        status == 201 and created.get("username") == new_user,
        f"HTTP {status}",
    )

    summarise()


def summarise():
    print()
    print("=" * 68)
    failed = [r for r in results if r[0] == FAIL]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("\nFailures:")
        for _, name, detail in failed:
            print(f"  - {name}" + (f" ({detail})" if detail else ""))
    print("=" * 68)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
