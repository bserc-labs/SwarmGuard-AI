"""
======================================================================

SwarmGuard AI
Flight Distribution Analysis

Purpose
--------
Analyse flight composition before train/test split.

======================================================================
"""

from pathlib import Path
import pandas as pd

# ==========================================================
# PATHS
# ==========================================================

MODEL_ROOT = Path(__file__).resolve().parent.parent

DATASET = MODEL_ROOT / "dataset" / "final_training_dataset.csv"

REPORT_DIR = MODEL_ROOT / "reports" / "flight_distribution"

REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ==========================================================
# LOAD
# ==========================================================

print("=" * 70)
print("FLIGHT DISTRIBUTION")
print("=" * 70)

df = pd.read_csv(DATASET)

print()

print(f"Rows    : {len(df):,}")
print(f"Columns : {len(df.columns)}")

# ==========================================================
# SUMMARY
# ==========================================================

summary = (

    df.groupby("flight_id")
      .agg(
          attack=("attack_type", "first"),
          airframe=("airframe", "first"),
          rows=("flight_id", "size")
      )
      .reset_index()

)

print()

print("=" * 70)
print("FLIGHTS")
print("=" * 70)

print(summary)

print()

print("=" * 70)
print("ATTACK COUNTS")
print("=" * 70)

print(summary["attack"].value_counts())

print()

print("=" * 70)
print("AIRFRAME COUNTS")
print("=" * 70)

print(summary["airframe"].value_counts())

# ==========================================================
# ATTACK × AIRFRAME TABLE
# ==========================================================

pivot = pd.crosstab(

    summary["airframe"],

    summary["attack"]

)

print()

print("=" * 70)
print("AIRFRAME x ATTACK")
print("=" * 70)

print(pivot)

# ==========================================================
# SAVE
# ==========================================================

summary.to_csv(

    REPORT_DIR / "flight_summary.csv",

    index=False

)

pivot.to_csv(

    REPORT_DIR / "airframe_attack_table.csv"

)

print()

print("Reports saved to")

print(REPORT_DIR)