"""
diagnostics/13_feature_group_ablation.py — Pending experiment (Handoff Sections 13 & 17)

Runs LOFO (Leave-One-Flight-Out) across 5 feature-group configurations to see
which attack MECHANISM the dataset actually carries signal for:

  Model A: GPS features only
  Model B: Network features only
  Model C: Dynamics features only
  Model D: GPS + Network
  Model E: GPS + Network + Dynamics (all)

If GPS-only does well on GPS Spoofing folds but Network-only does poorly on
Ping DoS folds (or vice versa), that tells you which mechanism needs more
feature-engineering work -- rather than treating "poor LOFO" as one
undifferentiated problem.

Column names below are best-effort based on the project handoff doc. Any
column not actually present in your final_training_dataset.csv is dropped
from that group automatically (with a printed note) rather than erroring,
since exact column names may have shifted slightly during development.

Usage:
    python diagnostics/13_feature_group_ablation.py --data dataset/final_training_dataset.csv
"""

import argparse

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score

GPS_FEATURES = [
    "gps_jump_distance", "gps_speed", "gps_acceleration",
    "gps_speed_error", "gps_speed_error_abs", "gps_speed_error_ratio",
    "gps_jump_log", "gps_speed_log",
]
NETWORK_FEATURES = [
    "heartbeat_gap", "heartbeat_lost", "packet_seq", "packet_seq_delta",
    "link_data_rate", "packet_loss_rate", "heartbeat_gap_change",
]
DYNAMICS_FEATURES = [
    "speed_change", "altitude_change", "vertical_speed",
    "roll_change", "pitch_change", "yaw_change", "time_delta",
]

CONFIGS = {
    "A: GPS only": GPS_FEATURES,
    "B: Network only": NETWORK_FEATURES,
    "C: Dynamics only": DYNAMICS_FEATURES,
    "D: GPS + Network": GPS_FEATURES + NETWORK_FEATURES,
    "E: GPS + Network + Dynamics (all)": GPS_FEATURES + NETWORK_FEATURES + DYNAMICS_FEATURES,
}


def resolve_columns(cols, available, label):
    present = [c for c in cols if c in available]
    missing = [c for c in cols if c not in available]
    if missing:
        print(f"  [note] {label}: {len(missing)} expected columns not found, skipping: {missing}")
    return present


def run_lofo(df, feature_cols, seed=42):
    """Returns per-flight accuracy and macro-F1 for one feature set."""
    results = []
    for held_out in df["flight_id"].unique():
        train = df[df["flight_id"] != held_out]
        test = df[df["flight_id"] == held_out]

        model = RandomForestClassifier(
            n_estimators=500, random_state=seed,
            class_weight="balanced_subsample", n_jobs=-1,
        )
        model.fit(train[feature_cols], train["attack_type"])
        pred = model.predict(test[feature_cols])

        acc = accuracy_score(test["attack_type"], pred)
        f1 = f1_score(test["attack_type"], pred, average="macro", zero_division=0)
        true_label = test["attack_type"].iloc[0]
        results.append({"flight_id": held_out, "true_label": true_label, "accuracy": acc, "macro_f1": f1})
    return pd.DataFrame(results)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="dataset/final_training_dataset.csv")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    print(f"Loaded {len(df)} rows, {df['flight_id'].nunique()} flights\n")
    available = set(df.columns)

    summary = []
    for name, cols in CONFIGS.items():
        resolved = resolve_columns(cols, available, name)
        if not resolved:
            print(f"  [skip] {name}: no columns available, skipping this config\n")
            continue
        print(f"Running LOFO for {name} ({len(resolved)} features)...")
        fold_results = run_lofo(df, resolved, seed=args.seed)
        mean_acc = fold_results["accuracy"].mean()
        mean_f1 = fold_results["macro_f1"].mean()
        std_acc = fold_results["accuracy"].std()
        print(f"  Mean accuracy: {mean_acc:.1%} (std {std_acc:.1%})  |  Mean macro F1: {mean_f1:.3f}")
        print(fold_results.to_string(index=False))
        print()
        summary.append({"config": name, "n_features": len(resolved),
                         "mean_accuracy": mean_acc, "mean_macro_f1": mean_f1, "std_accuracy": std_acc})

    print("\n=== Summary across all configs ===")
    print(pd.DataFrame(summary).to_string(index=False))


if __name__ == "__main__":
    main()
