"""
============================================================

SwarmGuard AI
Training Dataset Preparation

Purpose
--------
Prepare the engineered dataset for model training.

============================================================
"""

from pathlib import Path
import pandas as pd

# ==========================================================
# PATHS
# ==========================================================

SCRIPT_DIR = Path(__file__).resolve().parent

MODEL_ROOT = SCRIPT_DIR.parent

DATASET_DIR = MODEL_ROOT / "dataset"

INPUT_DATASET = DATASET_DIR / "feature_dataset.csv"

OUTPUT_DATASET = DATASET_DIR / "training_dataset.csv"

# ==========================================================
# FEATURES TO DROP
# ==========================================================

DROP_COLUMNS = [

    # Constant Features
    "eph",
    "epv",
    "fix_type",
    "satellites_used",
    "packet_errors",

    # Identifiers
    "timestamp",
    #"flight_id",

]

# ==========================================================
# MAIN
# ==========================================================

def main():

    print("=" * 70)
    print("PREPARING TRAINING DATASET")
    print("=" * 70)

    print("\nLoading Dataset...")

    df = pd.read_csv(INPUT_DATASET)

    print(f"Rows    : {len(df):,}")
    print(f"Columns : {len(df.columns)}")

    print("\nDropping Features...")

    removed = []

    for column in DROP_COLUMNS:

        if column in df.columns:

            df.drop(columns=column, inplace=True)

            removed.append(column)

    print()

    print("Removed Features")

    for feature in removed:

        print(f"  ✓ {feature}")

    print()

    print(f"Remaining Columns : {len(df.columns)}")

    print("\nRemaining Features")

    for feature in df.columns:

        print(" -", feature)

    print("\nSaving Dataset...")

    df.to_csv(

        OUTPUT_DATASET,

        index=False

    )

    print()

    print("Saved to")

    print(OUTPUT_DATASET)

    print()
    #print(df.corr())

    print("=" * 70)
    print("DONE")
    print("=" * 70)

    


if __name__ == "__main__":

    main()