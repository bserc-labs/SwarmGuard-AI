# SwarmGuard AI Architecture

How telemetry becomes an explainable incident.

## Overview

The AI pipeline runs **on the live ingest path**, asynchronously. A packet is
persisted first, then a background task scores that drone's recent window and
raises an incident if warranted.

An earlier revision of this document described the AI layer as "strictly
decoupled from the MAVLink telemetry ingestor." That was accurate at the time
and it was the central gap in the system: `incident_engine.process_ai_detection`
had no callers, so no incident was ever raised from real telemetry. Inference
only happened if a human POSTed to `/ai/predict`. That is no longer the case —
`services/detection_pipeline.py` is the integration.

```
POST /telemetry/ingest
   │
   ├─ authenticate (operator JWT + device API key)
   ├─ persist packet, commit                      ← transaction ends here
   │
   └─ BackgroundTask: run_detection(drone_id, organization_id)
          │
          ├─ load last N packets for this drone, tenant-scoped
          │
          ├─ TIER 1  KinematicGuard.evaluate()    → deterministic physics
          │            └─ fires? that is the incident, stop here
          │
          ├─ TIER 2  FeatureEngineer.transform()  → rolling feature vector
          │          AIInferenceService.predict() → is_anomaly, score 0-100
          │          ExplainabilityEngine.explain()→ TreeSHAP attributions
          │            [only when AI_INCIDENTS_ENABLED]
          │
          ├─ IncidentEngine.process_ai_detection()→ severity, priority,
          │                                          suppression, persist
          └─ ws_manager.broadcast()               → org-scoped live feed
```

### Why physics runs first, and why the model is off

The v2 model was trained on real PX4 flights and validated
leave-one-flight-out. It scores **F1 0.086 at a 0.862 false-positive rate** —
it flags 86% of normal telemetry while catching 10% of real attacks. Full
numbers in `backend/models_ml/v2/evaluation.json` and the root README.

So `AI_INCIDENTS_ENABLED` defaults to false. That is a measured decision, not
caution: at a 0.862 false-positive rate almost every alert it raised would be
noise, and an operator who learns to ignore the dashboard is worse off than one
who has none.

`KinematicGuard` is what runs. It cannot false-positive on a manoeuvre the
airframe is physically capable of, it needs no training data, and every alert
carries arithmetic an analyst can re-check. When both tiers would fire, the
explanation an operator sees should be the one with checkable numbers behind
it — hence the ordering.

### Why detection reads the window back from the database

Every feature the model consumes is a *rolling* statistic — a difference, a
rate, a variance — so a single packet has no defined feature vector. The
detector needs the preceding packets, and the packet that triggered it must
already be committed. Hence: after commit, not inside the transaction.

### Why it runs off the request path

Inference is synchronous CPU-bound sklearn work plus a blocking DB read. Doing
it inline would put model latency on the drone's ingest path, which is rate
limited at 50 packets/second. `run_detection` is `async` but immediately hands
the work to `asyncio.to_thread`, keeping the event loop free; only the
WebSocket broadcast runs on the loop itself, because the loop owns the sockets.
This mirrors the heartbeat monitor in `main.py`.

## 1. Feature Engineering (`models_ml/preprocess.py`)

The same `FeatureEngineer` serves training and inference, so a feature means
the same thing in both places. Two families are supported:

**v2 (deployable, active)** — per-flight kinematics and GPS consistency:

| Feature | Meaning |
|---|---|
| `gps_speed_error_abs` | \|GPS-derived ground speed − reported speed\| |
| `gps_speed_error_ratio` | the same error, relative to reported speed |
| `gps_acceleration` | rate of change of GPS-derived speed |
| `vertical_speed` | altitude change / time delta |
| `speed_change`, `yaw_change` | frame-to-frame deltas |
| `time_delta` | seconds between fixes |
| `altitude`, `yaw` | instantaneous state |

The spoofing signal: derive ground speed from successive position fixes and
compare it to what the airframe reports. A spoofed position jumps while the
airframe's own speed estimate stays plausible, so the two diverge sharply.

`haversine_vectorized` and `angle_difference` are duplicated verbatim from
`model_train/scripts/feature_engineering.py`. **These must not drift** — a
difference between them is train/serve skew, which presents as a model that
validates well and misbehaves live for no visible reason.

**v1 (synthetic, legacy)** — rolling-window statistics over the original
generated dataset. Retained so `MODEL_VERSION=v1` remains servable.

Which family is returned is driven by the loaded model's `feature_list` in its
registry metadata, falling back to `settings.FEATURE_LIST`. The model is the
authority: deriving it from config alone meant changing `MODEL_VERSION` without
also editing `FEATURE_LIST` fed the new model the old model's columns — same
shape, different meaning, no error raised.

## 2. Model Training & Registry

Training lives in `model_train/`, not in the backend. See the root README for
the validation protocol (leave-one-flight-out) and the ICC confound analysis
that determined the feature set.

`model_train/scripts/train_deployable_v2.py` writes registry artifacts directly
to `backend/models_ml/v2/`:

| File | Contents |
|---|---|
| `model.joblib` | fitted estimator |
| `scaler.joblib` | fitted StandardScaler |
| `metadata.json` | feature list, algorithm, scope limits, importances |
| `training_config.json` | hyperparameters, seed |
| `evaluation.json` | LOFO metrics (headline) + row-level ceiling (contrast) |

`registry.py` records SHA256 hashes of the serialized artifacts alongside the
Python and sklearn versions used, so a model in production can be traced to the
run that produced it.

## 3. Inference Service (`services/ai_service.py`)

`AIInferenceService` lazy-loads the version named by `MODEL_VERSION` and
rebinds its `FeatureEngineer` to that model's trained columns.

Scoring branches on model capability, not on a version string:

- **Supervised classifier** (v2) — `predict_proba` gives P(attack) directly;
  scaled to 0–100.
- **Unsupervised outlier detector** (v1 IsolationForest) — `predict` returns
  −1 for outliers and `decision_function` returns a signed margin, squashed to
  0–100 by hand.

Neither path is a fallback for the other. Reading an IsolationForest's −1 out
of a classifier silently inverts the verdict.

## 4. Explainability (`models_ml/explainability.py`)

TreeSHAP over the scaled feature vector, with a KernelExplainer fallback for
models TreeExplainer cannot handle.

SHAP output shape depends on the model and getting it wrong is silent rather
than loud — you get numbers, just the wrong ones. `_to_2d` normalises:

- single-output → already `(n_samples, n_features)`
- binary classifier under shap ≥ 0.45 → 3D `(n_samples, n_features, n_classes)`,
  reduced to the **positive class** (attributions for "this is normal" are the
  negation of what an analyst asked for)
- older shap / multi-output → a list, one array per class

Attributions are labelled from the loaded model's own feature list, so a
retrained model with different columns cannot mislabel its attributions against
a stale hardcoded list.

`explanation_confidence_percent` is the share of total attribution magnitude
carried by the top three features. Below 50% the summary is flagged: the
anomaly is distributed across many small contributions and no single cause
explains it.

## 5. Incident Engine (`services/incident_engine.py`)

Converts a detection into a persisted, prioritised incident.

- **Attack type** — voted across the top three SHAP features rather than taken
  from the single largest, so a marginally-larger unrelated feature cannot name
  an incident in a way that contradicts the explanation shown beneath it.
- **Suppression** — a repeat detection within 60s updates the open incident
  instead of creating a duplicate.
- **Threat level** — the inference layer reports a band name; the column stores
  an Integer rank. `_threat_level_ordinal` converts. Passing the raw string
  through raised a DataError on insert.
- **Tenancy** — `organization_id` is required and applied to the suppression
  lookup, the repeat count, and the created row. Without it, suppression reads
  across tenants and the incident is invisible to the org that owns the drone.

## Honest limitations

- **The ML tier does not generalize across flights.** LOFO F1 0.086. An
  ablation dropping `altitude`/`yaw` reached 0.055. The features the live
  schema can compute do not carry transferable attack signal on this dataset.
  Per-flight normalisation is the next thing to try.
- **Tier 1 catches gross manipulation, not subtle drift.** A spoofer that walks
  the position slowly enough to stay inside the airframe's envelope will not
  trip a physical threshold. That is the honest boundary of a physics detector,
  and it is precisely the gap the ML tier was meant to close.
- **GPS spoofing only.** Jamming and Ping DoS live in MAVLink link statistics
  that `TelemetryPacket` does not carry. The model structurally cannot see them.
- **Warm-up.** A drone needs `WINDOW_SIZE` packets before any detection runs.
  Below that the pipeline declines rather than emitting a warm-up verdict that
  looks like a real one.
- **Single-drone context.** Detection is per-drone; cross-drone swarm-level
  correlation is not implemented.
