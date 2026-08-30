"""
diagnostics/15_icc_confound_check.py — Flight-identity confound diagnostic

For every numeric feature, decomposes its variance into:
  - between-flight variance: how much is explained by "which flight is this"
  - within-flight variance:  how much is real moment-to-moment variation

Reports ICC = between-flight variance / total variance for each feature.

Why this matters here specifically: attack_type is 1:1 with flight_id (each
flight is entirely one attack type), so ANY feature with high ICC is a
feature the model can use as a flight-identity shortcut instead of learning
real attack behavior -- it'll look great on a row-level split (same flight's
rows leak across train/test) and collapse under LOFO, which is exactly the
pattern already observed (0.747 stratified ceiling vs near-0% LOFO on
Ping DoS folds).

High ICC (>0.3ish) = likely confound, dangerous for LOFO generalization.
Near-zero ICC = feature reflects instantaneous state, safe to trust.

This will NOT catch every problem (e.g. two features could jointly encode
flight identity even if neither alone has high ICC), but it's a fast,
principled first pass -- much better than guessing per-feature by analogy.

Usage:
    python diagnostics/15_icc_confound_check.py --data dataset/final_training_dataset.csv
"""

import argparse

import numpy as np
import pandas as pd

EXCLUDE_COLS = ["attack_type", "is_attack", "flight_id", "airframe", "timestamp"]


def compute_icc(df, col, group_col="flight_id"):
    sub = df[[col, group_col]].dropna()
    if len(sub) < 10:
        return np.nan, np.nan
    overall_var = sub[col].var()
    if overall_var == 0 or pd.isna(overall_var):
        return np.nan, sub[col].std()
    group_means = sub.groupby(group_col)[col].mean()
    group_counts = sub.groupby(group_col)[col].count()
    grand_mean = sub[col].mean()
    between_var = ((group_means - grand_mean) ** 2 * group_counts).sum() / (len(sub) - 1)
    icc = between_var / overall_var
    return icc, sub[col].std()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="dataset/final_training_dataset.csv")
    ap.add_argument("--high-threshold", type=float, default=0.3,
                     help="ICC above this is flagged as a likely confound")
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    if "flight_id" not in df.columns:
        print("[error] This diagnostic requires a flight_id column to group by. Not found.")
        return

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    candidate_cols = [c for c in numeric_cols if c not in EXCLUDE_COLS]

    results = []
    for col in candidate_cols:
        icc, std = compute_icc(df, col)
        results.append({"feature": col, "ICC_flight_identity": icc, "std": std})

    res_df = pd.DataFrame(results).sort_values("ICC_flight_identity", ascending=False, na_position="last")
    pd.set_option("display.float_format", lambda x: f"{x:.4f}")
    print(res_df.to_string(index=False))

    zero_var = res_df[res_df["ICC_flight_identity"].isna() & (res_df["std"] == 0)]
    high_icc = res_df[res_df["ICC_flight_identity"] > args.high_threshold]
    low_icc = res_df[res_df["ICC_flight_identity"] <= args.high_threshold]

    print(f"\n=== Recommended DROP (zero variance -- literally constant): {zero_var['feature'].tolist()}")
    print(f"\n=== Recommended DROP or fix (ICC > {args.high_threshold}, likely flight-identity confound):")
    print(high_icc[["feature", "ICC_flight_identity"]].to_string(index=False))
    print(f"\n=== Safe to keep (ICC <= {args.high_threshold}, reflects real within-flight signal):")
    print(low_icc[low_icc["ICC_flight_identity"].notna()][["feature", "ICC_flight_identity"]].to_string(index=False))


if __name__ == "__main__":
    main()
