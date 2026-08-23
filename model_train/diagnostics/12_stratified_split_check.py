"""
diagnostics/12_stratified_split_check.py — Pending experiment (Handoff Section 14)

Runs a CONVENTIONAL stratified row-level split (not flight-aware) with the
same Random Forest config as the LOFO baseline. This answers a different
question than LOFO does:

  LOFO answers:       "Does this model generalize to an unseen flight?"
  This script answers: "Does this feature set contain learnable signal at all?"

Interpretation:
  - High score here + poor LOFO  -> bottleneck is flight-diversity/generalization
                                     (matches the ICC/confound findings already made)
  - Poor score here too          -> bottleneck is feature engineering / label
                                     quality / attack signature strength, not
                                     just generalization. Don't just try more
                                     models -- go back to feature mechanism audit.

NOTE: this split is intentionally "wrong" for a final model (same-flight rows
leak across train/test), so a high score here is NOT evidence the model is
ready to ship -- it's purely a ceiling/sanity check.

Usage:
    python diagnostics/12_stratified_split_check.py --data dataset/final_training_dataset.csv
"""

import argparse

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split

EXCLUDE_COLS = ["attack_type", "is_attack", "flight_id", "airframe"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="dataset/final_training_dataset.csv")
    ap.add_argument("--test-size", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    print(f"Loaded {len(df)} rows, {df.shape[1]} columns")

    feature_cols = [c for c in df.columns if c not in EXCLUDE_COLS]
    print(f"Using {len(feature_cols)} features (excluding {EXCLUDE_COLS})")

    X = df[feature_cols]
    y = df["attack_type"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=args.test_size, random_state=args.seed, stratify=y
    )
    print(f"Train: {len(X_train)} rows, Test: {len(X_test)} rows (row-level split, NOT flight-aware)")

    model = RandomForestClassifier(
        n_estimators=500, random_state=args.seed,
        class_weight="balanced_subsample", n_jobs=-1,
    )
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)

    print("\n=== Conventional stratified split result (ceiling check, NOT a real generalization test) ===")
    print(classification_report(y_test, y_pred))
    print("Confusion matrix:")
    print(confusion_matrix(y_test, y_pred, labels=sorted(y.unique())))
    print(f"Classes order: {sorted(y.unique())}")

    macro_f1 = f1_score(y_test, y_pred, average="macro")
    print(f"\nMacro F1: {macro_f1:.3f}")
    if macro_f1 > 0.85:
        print("[interpretation] High ceiling score -> the LOFO problem is very likely "
              "flight-diversity/generalization (consistent with the ICC confound findings), "
              "not a lack of signal in the features themselves.")
    elif macro_f1 < 0.5:
        print("[interpretation] Ceiling score is ALSO poor -> don't just try more models. "
              "Revisit feature mechanism audit, label quality, and attack signature strength first.")
    else:
        print("[interpretation] Middling ceiling score -> some real signal exists but it's "
              "weak/noisy even without the generalization problem. Worth the feature-group "
              "ablation to see which mechanism (GPS vs Network vs Dynamics) is carrying it.")


if __name__ == "__main__":
    main()
