"""
preprocess_pipeline.py — Step 4: Preprocessing pipeline

Takes dataset/clean_dataset.csv (output of preprocess.py's feature engineering)
and produces the final model-ready arrays: missing-value handling, feature
scaling, and a train/test split. Saves the fitted scaler for reuse in predict.py.

Feature selection follows the EDA + feature-engineering findings:
  - Dropped: jamming_indicator (already absent), packet_loss_rate (always 0),
    heartbeat_lost / heartbeat_gap_change (not attack-specific, poor coverage)
  - Kept: gps/attitude/battery telemetry + the validated derived features
    (implied_gps_speed, gps_delta_m, speed_change, altitude_diff, signal_drop)

Usage:
    python preprocess_pipeline.py --in dataset/clean_dataset.csv \
        --out-train dataset/train.csv --out-test dataset/test.csv \
        --scaler models/scaler.pkl
"""

import argparse
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

# Features to feed the model. Deliberately excludes identifiers (flight_id,
# airframe, attack_type, is_attack, timestamp, packet_seq) and the
# confirmed-dead/non-discriminative columns from Step 3's diagnostics.
#
# NOTE: raw latitude/longitude deliberately excluded. With only ~16 flights
# total, absolute GPS coordinates mostly encode "which survey area/flight
# this is" rather than "attack or not" -- an early training run showed this
# caused the model to flag unfamiliar-but-benign flights as anomalies (70%
# false-positive rate on Normal). The validated MOVEMENT-based signal
# (gps_delta_m, implied_gps_speed) is kept, since that's what actually
# captures a spoofing "teleport" regardless of where the flight is.
FEATURE_COLS = [
    "altitude",
    "satellites_used", "eph", "epv",
    "battery", "speed",
    "roll", "pitch", "yaw",
    "link_data_rate",
    "speed_change", "gps_delta_m", "implied_gps_speed",
    "altitude_diff", "signal_drop",
]

DROP_COLS = ["packet_loss_rate", "heartbeat_lost", "heartbeat_gap_change",
             "heartbeat_time", "packet_errors"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", default="dataset/clean_dataset.csv")
    ap.add_argument("--out-train", default="dataset/train.csv")
    ap.add_argument("--out-test", default="dataset/test.csv")
    ap.add_argument("--scaler", default="models/scaler.pkl")
    ap.add_argument("--test-size", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    df = pd.read_csv(args.infile)
    print(f"Loaded {len(df)} rows, {df['flight_id'].nunique()} flights")

    present_drop = [c for c in DROP_COLS if c in df.columns]
    if present_drop:
        print(f"Dropping confirmed-dead/non-discriminative columns: {present_drop}")

    feature_cols = [c for c in FEATURE_COLS if c in df.columns]
    missing_expected = [c for c in FEATURE_COLS if c not in df.columns]
    if missing_expected:
        print(f"[warn] Expected feature columns not found in input, skipping: {missing_expected}")

    # --- Airframe one-hot encoding ---
    # Different airframes (quad/plane/VTOL/tail) have fundamentally different
    # baseline flight dynamics. Without airframe context, the model can only
    # learn one global "normal", and flags a different-but-benign airframe as
    # anomalous. One-hot encoding here (on the FULL df, before the split) so
    # train and test always get the identical set of dummy columns even if a
    # given airframe happens to land entirely on one side of the split.
    if "airframe" in df.columns:
        airframe_dummies = pd.get_dummies(df["airframe"], prefix="airframe").astype(int)
        df = pd.concat([df, airframe_dummies], axis=1)
        feature_cols = feature_cols + list(airframe_dummies.columns)
        print(f"Added airframe one-hot columns: {list(airframe_dummies.columns)}")

    # --- Missing value handling ---
    # Row-to-row derived features (speed_change, gps_delta_m, implied_gps_speed,
    # altitude_diff, signal_drop) are legitimately NaN on the first row of every
    # flight -- fill those with 0 (no change from a non-existent previous row).
    first_row_features = ["speed_change", "gps_delta_m", "implied_gps_speed",
                           "altitude_diff", "signal_drop"]
    for col in first_row_features:
        if col in df.columns:
            df[col] = df[col].fillna(0)

    # Remaining missingness (roll/pitch/yaw/speed on flights lacking that topic
    # entirely; eph/epv pre-fix sentinel rows we already dropped upstream) is
    # imputed per-flight first (carries the flight's own typical values),
    # falling back to the global median for any flight missing a column outright.
    for col in feature_cols:
        if df[col].isna().any():
            df[col] = df.groupby("flight_id")[col].transform(lambda s: s.fillna(s.median()))
            df[col] = df[col].fillna(df[col].median())

    remaining_na = df[feature_cols].isna().sum()
    remaining_na = remaining_na[remaining_na > 0]
    if len(remaining_na):
        print(f"[warn] Columns still with NaN after imputation (dropping these rows): "
              f"{remaining_na.to_dict()}")
        df = df.dropna(subset=feature_cols)

    print(f"\nRows after missing-value handling: {len(df)}")

    # --- Train/test split ---
    # Split by flight_id, not by row, so the same flight never leaks across
    # both sets. A plain stratified split balances FLIGHT COUNT per class, but
    # with only ~16 flights of wildly different lengths (2k-7k+ rows each),
    # that can still leave test badly skewed at the ROW level even though
    # flight counts look proportional. Instead, brute-force the subset of
    # each class's flights whose row-count sum lands closest to the target
    # test proportion -- feasible since each class only has a handful of flights.
    from itertools import combinations

    flight_sizes = df.groupby(["flight_id", "attack_type"]).size().reset_index(name="rows")

    test_flights = []
    for atype, group in flight_sizes.groupby("attack_type"):
        flights = list(zip(group["flight_id"], group["rows"]))
        total = sum(r for _, r in flights)
        target = total * args.test_size

        if len(flights) <= 18:  # 2^18 subsets max -- stays fast
            best_subset, best_diff = None, float("inf")
            for k in range(1, len(flights)):  # never take all or none of a class
                for combo in combinations(flights, k):
                    s = sum(r for _, r in combo)
                    diff = abs(s - target)
                    if diff < best_diff:
                        best_diff, best_subset = diff, combo
            chosen = [fid for fid, _ in best_subset] if best_subset else []
        else:
            # fallback for a class with many flights: greedy sort
            flights_sorted = sorted(flights, key=lambda x: -x[1])
            chosen, running = [], 0
            for fid, r in flights_sorted:
                if running < target:
                    chosen.append(fid)
                    running += r
        test_flights.extend(chosen)

    all_flights = set(flight_sizes["flight_id"])
    train_flights = list(all_flights - set(test_flights))
    test_flights = list(test_flights)

    train_df = df[df["flight_id"].isin(train_flights)].copy()
    test_df = df[df["flight_id"].isin(test_flights)].copy()

    print(f"\nTrain: {len(train_df)} rows across {len(train_flights)} flights")
    print((train_df["attack_type"].value_counts(normalize=True) * 100).round(1).astype(str) + "%")
    print(f"\nTest: {len(test_df)} rows across {len(test_flights)} flights")
    print((test_df["attack_type"].value_counts(normalize=True) * 100).round(1).astype(str) + "%")

    # --- Scaling ---
    # Fit the scaler on TRAIN only (never on test, to avoid leakage), then
    # apply to both.
    scaler = StandardScaler()
    train_df[feature_cols] = scaler.fit_transform(train_df[feature_cols])
    test_df[feature_cols] = scaler.transform(test_df[feature_cols])

    os.makedirs(os.path.dirname(args.scaler) or ".", exist_ok=True)
    joblib.dump({"scaler": scaler, "feature_cols": feature_cols}, args.scaler)
    print(f"\nSaved scaler + feature column order to {args.scaler}")

    os.makedirs(os.path.dirname(args.out_train) or ".", exist_ok=True)
    train_df.to_csv(args.out_train, index=False)
    test_df.to_csv(args.out_test, index=False)
    print(f"Wrote {args.out_train} and {args.out_test}")


if __name__ == "__main__":
    main()
