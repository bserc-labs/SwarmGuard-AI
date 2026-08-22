"""Train the v2 model that the backend can actually serve.

Why this script exists separately from the rest of model_train/:

The research pipeline produced `final_training_dataset_v2.csv` with 21 columns,
but the backend cannot serve a model that needs all of them. `TelemetryPacket`
(backend/schemas.py) carries no roll, no pitch, and no MAVLink link statistics,
so `roll_change`, `pitch_change`, `heartbeat_gap`, `heartbeat_lost` and
`link_data_rate_change` are unavailable at inference time. A model trained on
them scores beautifully offline and cannot run on the live feed at all.

So the feature set here is the intersection of two constraints:
  1. present in final_training_dataset_v2.csv (already confound-cleaned by
     diagnostics/16_apply_confound_fixes.py), and
  2. computable from a live TelemetryPacket window by the backend's
     FeatureEngineer.

Absolute latitude/longitude are dropped on top of that. Their ICC was low, but
they are absolute position: a model that has seen only flights around
(43.94, -78.89) would carry that geography into its decision boundary, which is
worthless for a system meant to fly somewhere else.

Scope: binary GPS Spoofing vs Normal. Ping DoS is excluded deliberately -- it is
a network-layer attack, its signal lives entirely in the heartbeat/link features
that the ingest schema does not carry, and including it as a positive class
would mean reporting recall for an attack this model structurally cannot see.
That is the honest boundary, and it matches what diagnostics/13's ablation was
set up to measure.

Headline metric is LOFO (leave-one-flight-out). The row-level stratified score
is computed too, but only as a contrast: attack_type is 1:1 with flight_id in
this dataset, so a random row split leaks the same flight into train and test
and inflates the number.

Usage:
    python model_train/scripts/train_deployable_v2.py
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler

SCRIPT_DIR = Path(__file__).resolve().parent
MODEL_ROOT = SCRIPT_DIR.parent
REPO_ROOT = MODEL_ROOT.parent

DATASET = MODEL_ROOT / "dataset" / "final_training_dataset_v2.csv"
REGISTRY_DIR = REPO_ROOT / "backend" / "models_ml" / "v2"

# Both in the cleaned dataset AND derivable from a live TelemetryPacket window.
#
# Split into two groups because `altitude` and `yaw` are *absolute* state, not
# rates of change. Their ICC came in under the 0.3 flag threshold, but ICC is a
# per-feature screen and a pair of weakly-flight-specific features can still
# encode flight identity jointly. Set SWARMGUARD_FEATURE_SET=deltas to drop
# them and train on rates alone.
ABSOLUTE_FEATURES = ["altitude", "yaw"]

DELTA_FEATURES = [
    "speed_change",
    "yaw_change",
    "time_delta",
    "vertical_speed",
    "gps_acceleration",
    "gps_speed_error_abs",
    "gps_speed_error_ratio",
]

_FEATURE_SET = os.environ.get("SWARMGUARD_FEATURE_SET", "full")
DEPLOYABLE_FEATURES = (
    DELTA_FEATURES if _FEATURE_SET == "deltas" else ABSOLUTE_FEATURES + DELTA_FEATURES
)

# Keeps an ablation run from overwriting the registered model.
REGISTRY_DIR = REGISTRY_DIR if _FEATURE_SET == "full" else REGISTRY_DIR.parent / f"v2_{_FEATURE_SET}"

POSITIVE_CLASS = "GPS Spoofing"
NEGATIVE_CLASS = "Normal"
SEED = 42
N_ESTIMATORS = 150

# Unbounded trees on 39k rows grow until every leaf is pure, which is
# memorisation -- exactly the failure the LOFO result exposed. It also produced
# a 327 MB artifact, over GitHub's 100 MB file limit, so the model could not be
# committed at all. Capping depth attacks both problems with one change.
MAX_DEPTH = 12

# joblib compression level. Trades a little load time for an order of magnitude
# on disk.
COMPRESS_LEVEL = 3

# Single-process by design. n_jobs=-1 makes joblib spawn a worker pool, and
# every worker re-imports the full sklearn stack; on a machine where process
# spawn is expensive (code-signing verification on first load) that dominates
# the runtime and the fit never gets going. One process on 9 features is fast
# enough. Override with SWARMGUARD_N_JOBS if your machine prefers the pool.
N_JOBS = int(os.environ.get("SWARMGUARD_N_JOBS", "1"))


def load() -> pd.DataFrame:
    if not DATASET.exists():
        sys.exit(
            f"Missing {DATASET}.\n"
            "Run: python model_train/diagnostics/16_apply_confound_fixes.py first."
        )
    df = pd.read_csv(DATASET)
    print(f"Loaded {len(df):,} rows x {df.shape[1]} columns from {DATASET.name}")

    missing = [c for c in DEPLOYABLE_FEATURES if c not in df.columns]
    if missing:
        sys.exit(f"Dataset is missing required features: {missing}")

    print(f"\nClass counts (full dataset):\n{df['attack_type'].value_counts().to_string()}")

    # Restrict to the two classes this feature set can actually separate.
    df = df[df["attack_type"].isin([POSITIVE_CLASS, NEGATIVE_CLASS])].copy()
    df["label"] = (df["attack_type"] == POSITIVE_CLASS).astype(int)

    # Rolling features are undefined on each flight's first row.
    before = len(df)
    df = df.dropna(subset=DEPLOYABLE_FEATURES)
    print(f"\nDropped {before - len(df):,} rows with undefined rolling features")

    # inf shows up where time_delta rounded to zero before the pipeline nulled it.
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=DEPLOYABLE_FEATURES)

    print(f"Training on {len(df):,} rows, {df['flight_id'].nunique()} flights")
    print(f"  {POSITIVE_CLASS}: {int(df['label'].sum()):,}")
    print(f"  {NEGATIVE_CLASS}: {int((1 - df['label']).sum()):,}")
    return df


def _metrics(y_true, y_pred, y_prob=None) -> dict:
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    out = {
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1_score": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "false_positive_rate": round(float(fp / (fp + tn)) if (fp + tn) else 0.0, 4),
        "false_negative_rate": round(float(fn / (fn + tp)) if (fn + tp) else 0.0, 4),
        "confusion_matrix": {"TN": int(tn), "FP": int(fp), "FN": int(fn), "TP": int(tp)},
    }
    # ROC-AUC is undefined on a single-class fold, which LOFO produces by
    # construction (each held-out flight is entirely one attack type).
    if y_prob is not None and len(np.unique(y_true)) > 1:
        out["roc_auc"] = round(float(roc_auc_score(y_true, y_prob)), 4)
    else:
        out["roc_auc"] = None
    return out


def _new_model() -> RandomForestClassifier:
    return RandomForestClassifier(
        n_estimators=N_ESTIMATORS,
        max_depth=MAX_DEPTH,
        random_state=SEED,
        class_weight="balanced_subsample",
        n_jobs=N_JOBS,
    )


def lofo(df: pd.DataFrame) -> dict:
    """Leave-one-flight-out. The honest generalization number."""
    print("\n" + "=" * 70)
    print("LOFO (leave-one-flight-out) -- headline metric")
    print("=" * 70)

    rows = []
    all_true, all_pred = [], []

    for held_out in sorted(df["flight_id"].unique()):
        train = df[df["flight_id"] != held_out]
        test = df[df["flight_id"] == held_out]

        # A fold whose training split lost a whole class cannot be fit.
        if train["label"].nunique() < 2 or test.empty:
            print(f"  {held_out}: skipped (degenerate fold)")
            continue

        scaler = StandardScaler().fit(train[DEPLOYABLE_FEATURES])
        model = _new_model()
        model.fit(scaler.transform(train[DEPLOYABLE_FEATURES]), train["label"])

        pred = model.predict(scaler.transform(test[DEPLOYABLE_FEATURES]))
        acc = float((pred == test["label"]).mean())

        all_true.extend(test["label"].tolist())
        all_pred.extend(pred.tolist())

        label = test["attack_type"].iloc[0]
        rows.append({"flight_id": held_out, "true_label": label, "accuracy": acc, "n": len(test)})
        print(f"  {held_out} ({label}, n={len(test):,}): accuracy={acc:.1%}")

    pooled = _metrics(np.array(all_true), np.array(all_pred))
    res = pd.DataFrame(rows)

    print(f"\nMean per-flight accuracy: {res['accuracy'].mean():.1%} (std {res['accuracy'].std():.1%})")
    print("\nPer-class mean accuracy:")
    print(res.groupby("true_label")["accuracy"].mean().to_string())
    print(f"\nPooled across all held-out flights:")
    print(f"  precision {pooled['precision']:.3f}  recall {pooled['recall']:.3f}  F1 {pooled['f1_score']:.3f}")
    print(f"  false positive rate {pooled['false_positive_rate']:.3f}")

    return {
        "pooled": pooled,
        "per_flight": rows,
        "mean_flight_accuracy": round(float(res["accuracy"].mean()), 4),
        "std_flight_accuracy": round(float(res["accuracy"].std()), 4),
        "n_folds": len(rows),
    }


def stratified_ceiling(df: pd.DataFrame) -> dict:
    """Row-level split. Inflated by design -- reported only for contrast."""
    print("\n" + "=" * 70)
    print("Stratified row-level split -- INFLATED CEILING, not a deployment claim")
    print("=" * 70)

    X, y = df[DEPLOYABLE_FEATURES].values, df["label"].values
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    true, pred, prob = [], [], []

    for tr, te in skf.split(X, y):
        scaler = StandardScaler().fit(X[tr])
        model = _new_model()
        model.fit(scaler.transform(X[tr]), y[tr])
        Xte = scaler.transform(X[te])
        true.extend(y[te])
        pred.extend(model.predict(Xte))
        prob.extend(model.predict_proba(Xte)[:, 1])

    m = _metrics(np.array(true), np.array(pred), np.array(prob))
    print(f"  precision {m['precision']:.3f}  recall {m['recall']:.3f}  F1 {m['f1_score']:.3f}  ROC-AUC {m['roc_auc']}")
    print("  ^ same flight's rows appear in train and test; treat as an upper bound only.")
    return m


def train_final(df: pd.DataFrame):
    print("\n" + "=" * 70)
    print("Fitting deployment model on all flights")
    print("=" * 70)

    scaler = StandardScaler().fit(df[DEPLOYABLE_FEATURES])
    model = _new_model()
    model.fit(scaler.transform(df[DEPLOYABLE_FEATURES]), df["label"])

    importances = sorted(
        zip(DEPLOYABLE_FEATURES, model.feature_importances_),
        key=lambda kv: kv[1],
        reverse=True,
    )
    print("\nFeature importances:")
    for name, imp in importances:
        print(f"  {name:<26} {imp:.4f}")

    return model, scaler, {k: round(float(v), 4) for k, v in importances}


def save(model, scaler, lofo_res, ceiling, importances, df):
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

    joblib.dump(model, REGISTRY_DIR / "model.joblib", compress=COMPRESS_LEVEL)
    joblib.dump(scaler, REGISTRY_DIR / "scaler.joblib", compress=COMPRESS_LEVEL)

    import sklearn

    metadata = {
        "model_version": "v2",
        "training_timestamp": datetime.utcnow().isoformat(),
        "dataset_source": "model_train/dataset/final_training_dataset_v2.csv",
        "dataset_description": (
            "Real PX4 ULog flights (Live GPS Spoofing and Jamming dataset), "
            "confound-cleaned by diagnostics/16_apply_confound_fixes.py"
        ),
        "feature_list": DEPLOYABLE_FEATURES,
        "algorithm": "RandomForestClassifier",
        "task": "binary classification",
        "positive_class": POSITIVE_CLASS,
        "scope_limitation": (
            "GPS Spoofing vs Normal only. Ping DoS is excluded: its signal lives in "
            "MAVLink link/heartbeat features that TelemetryPacket does not carry, so "
            "this model structurally cannot detect it."
        ),
        "excluded_features_reason": {
            "roll, roll_change, pitch_change": "not present in TelemetryPacket",
            "heartbeat_gap, heartbeat_lost, link_data_rate_change": "no link telemetry in ingest schema",
            "latitude, longitude": "absolute position ties the boundary to the dataset's geography",
            "battery, speed, pitch, link_data_rate": "dropped upstream as flight-identity confounds (ICC > 0.3)",
        },
        "validation_protocol": "leave-one-flight-out (LOFO)",
        "n_training_rows": int(len(df)),
        "n_flights": int(df["flight_id"].nunique()),
        "feature_importances": importances,
        "python_version": sys.version.split(" ")[0],
        "sklearn_version": sklearn.__version__,
        "feature_count": len(DEPLOYABLE_FEATURES),
    }

    training_config = {
        "algorithm": "RandomForestClassifier",
        "n_estimators": N_ESTIMATORS,
        "max_depth": MAX_DEPTH,
        "class_weight": "balanced_subsample",
        "random_seed": SEED,
        "preprocessing_configuration": "StandardScaler",
        "feature_engineering_configuration": "per-drone diffs + haversine GPS kinematics",
    }

    evaluation = {
        "headline": "LOFO pooled -- this is the number to quote",
        "lofo": lofo_res,
        "stratified_row_level_ceiling": ceiling,
        "ceiling_caveat": (
            "attack_type is 1:1 with flight_id, so a row-level split leaks flight "
            "identity across train/test. Reported for contrast only."
        ),
    }

    for name, payload in [
        ("metadata.json", metadata),
        ("training_config.json", training_config),
        ("evaluation.json", evaluation),
    ]:
        with open(REGISTRY_DIR / name, "w") as f:
            json.dump(payload, f, indent=4)

    print(f"\n✅ Saved v2 registry artifacts to {REGISTRY_DIR}")
    print("   Set MODEL_VERSION=v2 to activate.")


def main():
    df = load()
    lofo_res = lofo(df)
    ceiling = stratified_ceiling(df)
    model, scaler, importances = train_final(df)
    save(model, scaler, lofo_res, ceiling, importances, df)

    print("\n" + "=" * 70)
    print("SUMMARY -- quote the LOFO number, not the ceiling")
    print("=" * 70)
    p = lofo_res["pooled"]
    print(f"  LOFO pooled F1        : {p['f1_score']:.3f}")
    print(f"  LOFO pooled recall    : {p['recall']:.3f}")
    print(f"  LOFO pooled precision : {p['precision']:.3f}")
    print(f"  LOFO false pos rate   : {p['false_positive_rate']:.3f}")
    print(f"  Row-level ceiling F1  : {ceiling['f1_score']:.3f}  (inflated)")


if __name__ == "__main__":
    main()
