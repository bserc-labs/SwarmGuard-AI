"""
train.py — Step 5: Train the Isolation Forest anomaly detector

Fits on NORMAL-ONLY rows from dataset/train.csv (Isolation Forest is
unsupervised -- it needs to learn what "normal" looks like, not be handed a
train set where attacks are 70% of the data). Evaluates on the full
(mixed) dataset/test.csv using the attack_type/is_attack labels we already
have as ground truth.

Usage:
    python train.py --train dataset/train.csv --test dataset/test.csv \
        --scaler models/scaler.pkl --model models/isolation_forest.pkl
"""

import argparse
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (classification_report, confusion_matrix, f1_score,
                              precision_score, recall_score)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default="dataset/train.csv")
    ap.add_argument("--test", default="dataset/test.csv")
    ap.add_argument("--scaler", default="models/scaler.pkl")
    ap.add_argument("--model", default="models/isolation_forest.pkl")
    ap.add_argument("--contamination", default="auto",
                     help="Expected anomaly proportion, or 'auto'. If your test set's "
                          "attack rate is known and stable, passing that number "
                          "directly (e.g. 0.5) often works better than 'auto'.")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    bundle = joblib.load(args.scaler)
    feature_cols = bundle["feature_cols"]
    print(f"Using {len(feature_cols)} features: {feature_cols}")

    train_df = pd.read_csv(args.train)
    test_df = pd.read_csv(args.test)

    train_normal = train_df[train_df["is_attack"] == 0]
    print(f"\nTrain set: {len(train_df)} rows total, "
          f"{len(train_normal)} Normal rows used for fitting "
          f"({len(train_normal) / len(train_df):.1%} of train)")

    if len(train_normal) < 100:
        print("[warn] Very few normal rows to fit on -- results may be unstable.")

    contamination = args.contamination
    if contamination != "auto":
        contamination = float(contamination)

    model = IsolationForest(
        n_estimators=200,
        contamination=contamination,
        random_state=args.seed,
        n_jobs=-1,
    )
    model.fit(train_normal[feature_cols])
    print("Model fit complete.")

    # --- Evaluate on the full (mixed) test set ---
    X_test = test_df[feature_cols]
    raw_pred = model.predict(X_test)  # 1 = inlier (normal), -1 = outlier (anomaly)
    pred_attack = (raw_pred == -1).astype(int)
    anomaly_score = model.decision_function(X_test)  # higher = more normal

    y_true = test_df["is_attack"].values

    precision = precision_score(y_true, pred_attack, zero_division=0)
    recall = recall_score(y_true, pred_attack, zero_division=0)
    f1 = f1_score(y_true, pred_attack, zero_division=0)

    print(f"\n=== Overall test set performance (Normal vs Any Attack) ===")
    print(f"Precision: {precision:.3f}")
    print(f"Recall:    {recall:.3f}")
    print(f"F1:        {f1:.3f}")
    print("\nConfusion matrix (rows=true, cols=predicted) [Normal, Attack]:")
    print(confusion_matrix(y_true, pred_attack))
    print("\n" + classification_report(y_true, pred_attack, target_names=["Normal", "Attack"]))

    # --- Per-attack-type recall breakdown ---
    # Overall recall hides whether the model is actually catching BOTH attack
    # types, or acing one and missing the other entirely.
    print("=== Recall by attack type (rows correctly flagged as anomalous) ===")
    test_df = test_df.copy()
    test_df["pred_attack"] = pred_attack
    for atype, group in test_df.groupby("attack_type"):
        if atype == "Normal":
            # for Normal, "correct" means NOT flagged -> report false positive rate instead
            fpr = group["pred_attack"].mean()
            print(f"  {atype}: {fpr:.1%} false-positive rate ({int(group['pred_attack'].sum())}/{len(group)} wrongly flagged)")
        else:
            recall_i = group["pred_attack"].mean()
            print(f"  {atype}: {recall_i:.1%} recall ({int(group['pred_attack'].sum())}/{len(group)} correctly flagged)")

    os.makedirs(os.path.dirname(args.model) or ".", exist_ok=True)
    joblib.dump({"model": model, "feature_cols": feature_cols}, args.model)
    print(f"\nSaved model to {args.model}")


if __name__ == "__main__":
    main()
