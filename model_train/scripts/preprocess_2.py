"""
preprocess.py

Stage 2 - Dataset Preprocessing

Input:
    dataset/raw_dataset.csv

Output:
    dataset/clean_dataset.csv
"""

from pathlib import Path
import pandas as pd
import numpy as np

# ============================================================
# Paths
# ============================================================

MODEL_ROOT = Path(__file__).resolve().parent.parent

DATASET_DIR = MODEL_ROOT / "dataset"
MODELS_DIR = MODEL_ROOT / "models"
REPORTS_DIR = MODEL_ROOT / "reports"

INPUT_DATASET = DATASET_DIR / "raw_dataset.csv"
OUTPUT_DATASET = DATASET_DIR / "clean_dataset.csv"

REPORTS_DIR.mkdir(exist_ok=True)

# ============================================================
# Required Columns
# ============================================================

REQUIRED_COLUMNS = [
    "timestamp",
    "attack_type",
    "flight_id",
]

# ============================================================
# Load Dataset
# ============================================================

def load_dataset(path: Path) -> pd.DataFrame:

    print("=" * 60)
    print("Loading Dataset")
    print("=" * 60)

    if not path.exists():
        raise FileNotFoundError(f"\nDataset not found:\n{path}")

    df = pd.read_csv(path)

    print(f"Dataset Loaded Successfully")
    print(f"Rows    : {len(df)}")
    print(f"Columns : {len(df.columns)}")

    return df


# ============================================================
# Validate Dataset
# ============================================================

def validate_schema(df: pd.DataFrame):

    print("\nChecking Dataset Schema...")

    missing = []

    for col in REQUIRED_COLUMNS:

        if col not in df.columns:
            missing.append(col)

    if missing:
        raise ValueError(
            f"Missing Required Columns:\n{missing}"
        )

    print("Schema Validation Passed")


# ============================================================
# Dataset Summary
# ============================================================

def dataset_summary(df: pd.DataFrame):

    print("\n" + "=" * 60)
    print("Dataset Summary")
    print("=" * 60)

    print("\nData Types\n")
    print(df.dtypes)

    print("\nShape")
    print(df.shape)

    print("\nMemory Usage")

    memory = df.memory_usage(deep=True).sum() / (1024 ** 2)

    print(f"{memory:.2f} MB")

    print("\nAttack Distribution")

    print(df["attack_type"].value_counts())

    print("\nAirframe Distribution")

    if "airframe" in df.columns:
        print(df["airframe"].value_counts())


# ============================================================
# Remove Duplicates
# ============================================================

def remove_duplicates(df: pd.DataFrame):

    print("\n" + "=" * 60)
    print("Duplicate Check")
    print("=" * 60)

    before = len(df)

    df = df.drop_duplicates()

    after = len(df)

    print(f"Removed : {before-after}")

    return df


# ============================================================
# Missing Value Report
# ============================================================

def missing_report(df: pd.DataFrame):

    print("\n" + "=" * 60)
    print("Missing Value Report")
    print("=" * 60)

    report = pd.DataFrame({

        "Missing Count":
            df.isna().sum(),

        "Missing %":
            (df.isna().sum() / len(df) * 100).round(2)

    })

    report = report.sort_values(
        "Missing %",
        ascending=False
    )

    print(report)

    report.to_csv(
        REPORTS_DIR / "missing_value_report.csv"
    )

    return report


# ============================================================
# Datatypes
# ============================================================

def convert_dtypes(df: pd.DataFrame):

    print("\nChecking Data Types...")

    # Placeholder for future conversions.

    return df


# ============================================================
# Sort Dataset
# ============================================================

def sort_dataset(df: pd.DataFrame):

    print("\nSorting Dataset...")

    if (
        "flight_id" in df.columns
        and
        "timestamp" in df.columns
    ):

        df = df.sort_values(
            ["flight_id", "timestamp"]
        )

    return df


# ============================================================
# Save
# ============================================================

def save_dataset(df: pd.DataFrame):

    print("\nSaving Clean Dataset...")

    df.to_csv(
        OUTPUT_DATASET,
        index=False
    )

    print(f"\nSaved to:\n{OUTPUT_DATASET}")


# ============================================================
# Main
# ============================================================

def main():

    print("\n")
    print("=" * 60)
    print("SwarmGuard AI")
    print("Stage 2 - Dataset Preprocessing")
    print("=" * 60)

    print("\nResolved Paths\n")

    print(f"MODEL_ROOT    : {MODEL_ROOT}")
    print(f"DATASET_DIR   : {DATASET_DIR}")
    print(f"INPUT_DATASET : {INPUT_DATASET}")
    print(f"OUTPUT_DATASET: {OUTPUT_DATASET}")

    df = load_dataset(INPUT_DATASET)

    validate_schema(df)

    dataset_summary(df)

    df = remove_duplicates(df)

    df = convert_dtypes(df)

    missing_report(df)

    df = sort_dataset(df)

    save_dataset(df)

    print("\n")
    print("=" * 60)
    print("Preprocessing Complete")
    print("=" * 60)


if __name__ == "__main__":
    main()