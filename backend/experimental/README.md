# experimental/

Modules that are not part of the running product.

Nothing in `backend/services/`, `backend/routers/` or `main.py` imports anything
here, and nothing here executes on the telemetry, request or detection path.
They are kept because each represents real work that could plausibly return —
not because anything depends on them.

A review flagged these as "zero imports". That was accurate for two of them and
wrong for three: `threat_service` and `sensor_fusion` carry real test coverage,
and `kalman_service` is a dependency of `sensor_fusion`. They were moved rather
than deleted, and their tests moved with the import path, so the coverage is
intact.

| Module | Status | Why it is here |
|---|---|---|
| `killchain_service.py` | Deliberately deferred | A dry-run kill-chain engine from Sprint 7. It evaluates threat conditions and records `PENDING` command requests. Leaving it unwired is a safety decision, not an oversight — an autonomous path to drone commands should not be reachable by accident. |
| `swarm_service.py` | Partially implemented | Formation and neighbour-distance helpers. Contains `Math_atan2_sqrt`, a mis-transliterated `Math.atan2(sqrt(a), sqrt(1-a))` from JavaScript, so its haversine is not trustworthy as written. Needs review before any use. |
| `threat_service.py` | Superseded, tested | Pluggable anomaly-score → threat-score mapping strategies. The live system computes threat scores inside `kinematic_guard` (log-scaled exceedance) and bands them in `alert_service` against per-organization thresholds, so this layer has no caller. Its tests still run. |
| `sensor_fusion.py` | Superseded, tested | Multi-sensor fusion producing a single confidence figure. The shipped detector deliberately compares GNSS against airframe-reported speed rather than fusing them — the disagreement *is* the spoofing signal, and fusing would average it away. Its tests still run. |
| `kalman_service.py` | Dependency of the above | A scalar Kalman filter used only by `sensor_fusion`. |

## Moving something back

Wire it into `services/`, move the file back in the same change, and give it
tests that run against the live path. Detection code in particular must go
through `IncidentEngine` — suppression, prioritisation, tenant scoping and the
audit trail all live there, and a second path around it would silently lose all
four.

## What is *not* here

`geofence_service.py` was on the same list and is now live: it is Tier 1b in
`detection_pipeline`, raising real incidents through `IncidentEngine`. It stays
in `services/`.
