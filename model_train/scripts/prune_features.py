"""
======================================================================

SwarmGuard AI
Feature Pruning

Purpose
--------
Removes highly correlated / redundant features discovered during
correlation analysis.

Input
-----
dataset/training_dataset.csv

Output
------
dataset/final_training_dataset.csv

======================================================================
"""

from pathlib import Path
import pandas as pd

# ==========================================================
# PATHS
# ==========================================================

SCRIPT_DIR = Path(__file__).resolve().parent

MODEL_ROOT = SCRIPT_DIR.parent

DATASET_DIR = MODEL_ROOT / "dataset"

INPUT_DATASET = DATASET_DIR / "training_dataset.csv"

OUTPUT_DATASET = DATASET_DIR / "final_training_dataset.csv"

# ==========================================================
# FEATURES TO REMOVE
# ==========================================================

DROP_COLUMNS = [

    # -----------------------------------------
    # GPS Cluster
    # -----------------------------------------

    "gps_jump_distance",
    "gps_speed",
    "gps_speed_error",

    # -----------------------------------------
    # Log Transform Features
    # -----------------------------------------

    "gps_jump_log",
    "gps_speed_log",

    # -----------------------------------------
    # Motion
    # -----------------------------------------

    "altitude_change",

    # -----------------------------------------
    # Packet Counter
    # -----------------------------------------

    "packet_seq"

]

# ==========================================================
# MAIN
# ==========================================================

def main():

    print("=" * 70)
    print("FEATURE PRUNING")
    print("=" * 70)

    print("\nLoading Dataset...")

    df = pd.read_csv(INPUT_DATASET)

    print(f"Rows    : {len(df):,}")
    print(f"Columns : {len(df.columns)}")

    print("\nRemoving Features...\n")

    removed = []

    for feature in DROP_COLUMNS:

        if feature in df.columns:

            df.drop(columns=feature, inplace=True)

            removed.append(feature)

            print(f"✓ {feature}")

    print("\n----------------------------------------------")

    print(f"Removed Features : {len(removed)}")

    print(f"Remaining Columns : {len(df.columns)}")

    print("----------------------------------------------")

    print("\nRemaining Features\n")

    for feature in df.columns:

        print(feature)

    print("\nSaving Dataset...")

    df.to_csv(

        OUTPUT_DATASET,

        index=False

    )

    print()

    print("Saved to")

    print(OUTPUT_DATASET)

    print()

    print("=" * 70)
    print("FEATURE PRUNING COMPLETE")
    print("=" * 70)


if __name__ == "__main__":

    main()