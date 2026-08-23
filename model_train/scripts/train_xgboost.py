"""
train_xgboost.py — Supervised multi-class classifier (primary model)

Predicts attack_type directly (Normal / Ping DoS / GPS Spoofing), rather than
just "anomalous or not". Complements isolation_forest.pkl:
  - XGBoost: names the specific attack (what the SwarmGuard-AI dashboard
    needs to display), better precision/recall since it uses the labels
    we actually have.
  - Isolation Forest: kept as a secondary layer that can flag a genuinely
    novel attack type XGBoost was never trained on (XGBoost can only ever
    predict one of its known classes -- it has no "unknown" bucket).

Usage:
    python train_xgboost.py --train dataset/train.csv --test dataset/test.csv \
        --scaler models/scaler.pkl --model models/xgboost_classifier.pkl
"""

import argparse
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default="dataset/train.csv")
    ap.add_argument("--test", default="dataset/test.csv")
    ap.add_argument("--scaler", default="models/scaler.pkl")
    ap.add_argument("--model", default="models/xgboost_classifier.pkl")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    bundle = joblib.load(args.scaler)
    feature_cols = bundle["feature_cols"]
    print(f"Using {len(feature_cols)} features: {feature_cols}")

    train_df = pd.read_csv(args.train)
    test_df = pd.read_csv(args.test)

    le = LabelEncoder()
    y_train_full = le.fit_transform(train_df["attack_type"])
    y_test = le.transform(test_df["attack_type"])
    print(f"Classes: {list(le.classes_)}")

    # Small internal validation split (row-level) purely for early stopping --
    # NOT a substitute for the flight-held-out test.csv, which remains the
    # real generalization check.
    X_fit, X_val, y_fit, y_val = train_test_split(
        train_df[feature_cols], y_train_full, test_size=0.15,
        random_state=args.seed, stratify=y_train_full,
    )

    # Class weights: train's split isn't perfectly balanced (roughly 30-39%
    # per class from Step 4) -- weight samples so no class dominates the loss.
    sample_weight = compute_sample_weight("balanced", y_fit)

    model = XGBClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.05,
        objective="multi:softprob",
        num_class=len(le.classes_),
        eval_metric="mlogloss",
        early_stopping_rounds=20,
        random_state=args.seed,
        n_jobs=-1,
    )
    model.fit(
        X_fit, y_fit,
        sample_weight=sample_weight,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )
    print(f"Model fit complete (best iteration: {model.best_iteration})")

    # --- Evaluate on the full held-out test set ---
    X_test = test_df[feature_cols]
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)

    print("\n=== Test set performance (per attack type) ===")
    print(classification_report(y_test, y_pred, target_names=le.classes_))
    print("Confusion matrix (rows=true, cols=predicted):")
    print(f"Classes order: {list(le.classes_)}")
    print(confusion_matrix(y_test, y_pred))

    # --- Feature importance ---
    importances = pd.Series(model.feature_importances_, index=feature_cols).sort_values(ascending=False)
    print("\n=== Feature importance ===")
    print(importances.to_string())

    os.makedirs(os.path.dirname(args.model) or ".", exist_ok=True)
    joblib.dump({"model": model, "label_encoder": le, "feature_cols": feature_cols}, args.model)
    print(f"\nSaved model to {args.model}")


if __name__ == "__main__":
    main()
