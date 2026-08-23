"""
diagnostics/14_full_feature_lofo.py — Apples-to-apples LOFO vs the ceiling check

Runs LOFO using the EXACT same feature set as 12_stratified_split_check.py
(everything except attack_type/is_attack/flight_id/airframe) -- no guessed
column names, no risk of an incomplete feature-group subset. This isolates
ONE variable: row-level split vs flight-level split, with the feature set
held constant. Directly answers: how much does the 0.747 ceiling macro-F1
drop when the split respects flight boundaries?

Uses fewer trees than the official 500-tree baseline (configurable) since
this is a diagnostic scan, not the final model -- faster iteration matters
more than squeezing out the last bit of RF performance right now.

Usage:
    python diagnostics/14_full_feature_lofo.py --data dataset/final_training_dataset.csv
"""

import argparse

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score

EXCLUDE_COLS = ["attack_type", "is_attack", "flight_id", "airframe"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="dataset/final_training_dataset.csv")
    ap.add_argument("--n-estimators", type=int, default=200,
                     help="Fewer trees than the 500-tree baseline -- this is a "
                          "diagnostic scan across 16 folds, faster iteration matters more.")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    feature_cols = [c for c in df.columns if c not in EXCLUDE_COLS]
    print(f"Loaded {len(df)} rows, {df['flight_id'].nunique()} flights")
    print(f"Using {len(feature_cols)} features (same set as the stratified ceiling check): {feature_cols}\n")

    results = []
    for held_out in df["flight_id"].unique():
        train = df[df["flight_id"] != held_out]
        test = df[df["flight_id"] == held_out]

        model = RandomForestClassifier(
            n_estimators=args.n_estimators, random_state=args.seed,
            class_weight="balanced_subsample", n_jobs=-1,
        )
        model.fit(train[feature_cols], train["attack_type"])
        pred = model.predict(test[feature_cols])

        acc = accuracy_score(test["attack_type"], pred)
        f1 = f1_score(test["attack_type"], pred, average="macro", zero_division=0)
        true_label = test["attack_type"].iloc[0]
        airframe = test["airframe"].iloc[0] if "airframe" in test.columns else "?"
        results.append({"flight_id": held_out, "airframe": airframe, "true_label": true_label,
                         "accuracy": acc, "macro_f1": f1})
        print(f"  {held_out} ({airframe}, {true_label}): accuracy={acc:.1%}, macro_f1={f1:.3f}")

    res_df = pd.DataFrame(results)
    print(f"\n=== LOFO summary (full feature set, {args.n_estimators} trees) ===")
    print(f"Mean accuracy: {res_df['accuracy'].mean():.1%} (std {res_df['accuracy'].std():.1%})")
    print(f"Mean macro F1: {res_df['macro_f1'].mean():.3f} (std {res_df['macro_f1'].std():.3f})")
    print(f"\nCompare against the row-level stratified ceiling (0.747 macro F1, same feature set) "
          f"to see exactly what flight-boundary generalization costs.")
    print("\nPer true_label breakdown:")
    print(res_df.groupby("true_label")[["accuracy", "macro_f1"]].mean())


if __name__ == "__main__":
    main()
