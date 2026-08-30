"""
======================================================================

SwarmGuard AI
Random Forest Trainer

Part 1
-------
Dataset Loading
Feature Preparation
Leave-One-Flight-Out Split

======================================================================
"""

from pathlib import Path

import pandas as pd
import numpy as np

from sklearn.model_selection import LeaveOneGroupOut
from sklearn.metrics import (
    accuracy_score,
    precision_recall_fscore_support,
    confusion_matrix,
    classification_report
)

# ==========================================================
# PATHS
# ==========================================================

SCRIPT_DIR = Path(__file__).resolve().parent

MODEL_ROOT = SCRIPT_DIR.parent

DATASET = MODEL_ROOT / "dataset" / "final_training_dataset.csv"

MODELS_DIR = MODEL_ROOT / "models"

REPORT_DIR = MODEL_ROOT / "reports" / "random_forest"

MODELS_DIR.mkdir(exist_ok=True)

REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ==========================================================
# LOAD DATASET
# ==========================================================

def load_dataset():

    print("=" * 70)
    print("LOADING DATASET")
    print("=" * 70)

    df = pd.read_csv(DATASET)

    print(f"Rows    : {len(df):,}")
    print(f"Columns : {len(df.columns)}")

    return df


# ==========================================================
# PREPARE FEATURES
# ==========================================================

def prepare_dataset(df):

    print("\nPreparing Features...")

    feature_columns = [

        c for c in df.columns

        if c not in [

            "attack_type",
            "is_attack",
            "flight_id",
            "airframe"

        ]

    ]

    X = df[feature_columns].copy()

    y = df["attack_type"].copy()

    groups = df["flight_id"].copy()

    metadata = df[

        [

            "flight_id",

            "airframe",

            "attack_type"

        ]

    ].copy()

    print()

    print(f"Features : {X.shape[1]}")

    print(f"Samples  : {len(X):,}")

    print()

    print("Attack Distribution")

    print(y.value_counts())

    print()

    print(f"Unique Flights : {groups.nunique()}")

    return X, y, groups, metadata


# ==========================================================
# CREATE LOFO SPLITS
# ==========================================================

def create_lofo_splits(

    X,

    y,

    groups,

    metadata

):

    print()

    print("=" * 70)

    print("LEAVE ONE FLIGHT OUT")

    print("=" * 70)

    logo = LeaveOneGroupOut()

    folds = []

    for fold_id, (

        train_idx,

        test_idx

    ) in enumerate(

        logo.split(

            X,

            y,

            groups

        ),

        start=1

    ):

        held_out = metadata.iloc[test_idx]

        flight = held_out["flight_id"].iloc[0]

        attack = held_out["attack_type"].iloc[0]

        airframe = held_out["airframe"].iloc[0]

        print(

            f"\nFold {fold_id:02d}"

        )

        print(

            f"Held-out Flight : {flight}"

        )

        print(

            f"Attack          : {attack}"

        )

        print(

            f"Airframe        : {airframe}"

        )

        print(

            f"Train Rows      : {len(train_idx):,}"

        )

        print(

            f"Test Rows       : {len(test_idx):,}"

        )

        folds.append(

            {

                "fold": fold_id,

                "train_idx": train_idx,

                "test_idx": test_idx,

                "flight_id": flight,

                "attack": attack,

                "airframe": airframe

            }

        )

    print()

    print("=" * 70)

    print(f"Total Folds : {len(folds)}")

    print("=" * 70)

    return folds

# ==========================================================
# IMPORTS FOR TRAINING
# ==========================================================

from sklearn.impute import SimpleImputer
from sklearn.preprocessing import LabelEncoder
from sklearn.ensemble import RandomForestClassifier

def train_one_fold(
    X,
    y,
    fold
):

    train_idx = fold["train_idx"]
    test_idx = fold["test_idx"]

    X_train = X.iloc[train_idx].copy()
    X_test = X.iloc[test_idx].copy()

    y_train = y.iloc[train_idx].copy()
    y_test = y.iloc[test_idx].copy()

    # ---------------------------------------------
    # Missing Value Imputation
    # ---------------------------------------------

    imputer = SimpleImputer(strategy="median")

    X_train = pd.DataFrame(
        imputer.fit_transform(X_train),
        columns=X_train.columns,
        index=X_train.index,
    )

    X_test = pd.DataFrame(
        np.asarray(imputer.transform(X_test)),
        columns=X_test.columns,
        index=X_test.index,
    )

    # ---------------------------------------------
    # Label Encoding
    # ---------------------------------------------

    encoder = LabelEncoder()

    y_train_enc = encoder.fit_transform(y_train)
    print()

    print("Training labels")

    print(pd.Series(y_train).value_counts())

    print()

    print("Testing labels")

    print(pd.Series(y_test).value_counts())

    print()
    y_test_enc = encoder.transform(y_test)

    # ---------------------------------------------
    # Model
    # ---------------------------------------------

    model = RandomForestClassifier(
        n_estimators=500,
        random_state=42,
        class_weight="balanced_subsample",
        n_jobs=-1
    )

    print(f"Training Fold {fold['fold']:02d}...")

    model.fit(X_train, y_train_enc)

    predictions = model.predict(X_test)

    print("\nEncoder classes:")
    print(encoder.classes_)

    print("\nPredicted labels")
    print(pd.Series(encoder.inverse_transform(predictions)).value_counts())

    print("\nTrue labels")
    print(pd.Series(y_test).value_counts())

    probabilities = model.predict_proba(X_test)

    return {
        "model": model,
        "encoder": encoder,
        "imputer": imputer,
        "y_true": y_test_enc,
        "y_pred": predictions,
        "y_prob": probabilities,
        "feature_names": X.columns,
        "importance": model.feature_importances_,
        "flight_id": fold["flight_id"],
        "attack": fold["attack"],
        "airframe": fold["airframe"]
    }   


# ==========================================================
# TRAIN ALL FOLDS
# ==========================================================

def train_all_folds(
    X,
    y,
    folds
):

    print()
    print("=" * 70)
    print("TRAINING RANDOM FOREST")
    print("=" * 70)

    results = []

    all_true = []
    all_pred = []

    flight_results = []

    feature_importance = np.zeros(len(X.columns))

    for fold in folds:

        result = train_one_fold(
            X,
            y,
            fold
        )

        results.append(result)

        # ---------------------------------------
        # Collect predictions
        # ---------------------------------------

        all_true.extend(result["y_true"])
        all_pred.extend(result["y_pred"])

        # ---------------------------------------
        # Feature importance
        # ---------------------------------------

        feature_importance += result["importance"]

        # ---------------------------------------
        # Per-flight accuracy
        # ---------------------------------------

        acc = accuracy_score(

            result["y_true"],

            result["y_pred"]

        )

        flight_results.append({

            "flight_id": result["flight_id"],

            "attack": result["attack"],

            "airframe": result["airframe"],

            "accuracy": acc

        })

        print(
            f"Fold {fold['fold']:02d} Accuracy : {acc:.4f}"
        )

    # =====================================================
    # OVERALL METRICS
    # =====================================================

    print()

    print("=" * 70)
    print("OVERALL RESULTS")
    print("=" * 70)

    accuracy = accuracy_score(

        all_true,

        all_pred

    )

    precision, recall, f1, _ = precision_recall_fscore_support(

        all_true,

        all_pred,

        average="weighted"

    )

    print(f"Accuracy  : {accuracy:.4f}")
    print(f"Precision : {precision:.4f}")
    print(f"Recall    : {recall:.4f}")
    print(f"F1 Score  : {f1:.4f}")

    # =====================================================
    # CLASSIFICATION REPORT
    # =====================================================

    print()

    print("=" * 70)
    print("CLASSIFICATION REPORT")
    print("=" * 70)

    print(

        classification_report(

            all_true,

            all_pred

        )

    )

    # =====================================================
    # CONFUSION MATRIX
    # =====================================================

    cm = confusion_matrix(

        all_true,

        all_pred

    )

    print()

    print("=" * 70)
    print("CONFUSION MATRIX")
    print("=" * 70)

    print(cm)

    # =====================================================
    # FEATURE IMPORTANCE
    # =====================================================

    feature_importance /= len(folds)

    importance_df = pd.DataFrame({

        "feature": X.columns,

        "importance": feature_importance

    })

    importance_df = importance_df.sort_values(

        "importance",

        ascending=False

    )

    print()

    print("=" * 70)
    print("TOP FEATURES")
    print("=" * 70)

    print(importance_df.head(20))

    # =====================================================
    # PER FLIGHT
    # =====================================================

    flight_df = pd.DataFrame(flight_results)

    print()

    print("=" * 70)
    print("PER FLIGHT")
    print("=" * 70)

    print(flight_df)

    return results

# ==========================================================
# MAIN
# ==========================================================

def main():

    df = load_dataset()

    X, y, groups, metadata = prepare_dataset(df)

    folds = create_lofo_splits(

        X,

        y,

        groups,

        metadata

    )
    results = train_all_folds(
    X,
    y,
    folds
)

    print()
    print("=" * 70)
    print("Training Complete")
    print("=" * 70)
    print(f"Completed {len(results)} folds.")


if __name__ == "__main__":

    main()