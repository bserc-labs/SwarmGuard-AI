"""
============================================================

SwarmGuard AI
Feature Correlation Analysis

Purpose
--------
Analyse feature correlation before model training.

Outputs
-------
correlation_matrix.csv
high_correlation_pairs.csv
correlation_heatmap.png

============================================================
"""

from pathlib import Path

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ==========================================================
# PATHS
# ==========================================================

MODEL_ROOT = Path(__file__).resolve().parent.parent

DATASET = MODEL_ROOT / "dataset" / "training_dataset.csv"

REPORT_DIR = MODEL_ROOT / "reports" / "correlation"

REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ==========================================================
# LOAD
# ==========================================================

print("=" * 70)
print("FEATURE CORRELATION ANALYSIS")
print("=" * 70)

print("\nLoading dataset...")

df = pd.read_csv(DATASET)

print(f"Rows    : {len(df):,}")
print(f"Columns : {len(df.columns)}")

# ==========================================================
# KEEP ONLY NUMERIC FEATURES
# ==========================================================

numeric_df = df.select_dtypes(include=np.number)

# Labels are not model features
DROP = [
    "is_attack"
]

numeric_df = numeric_df.drop(
    columns=[c for c in DROP if c in numeric_df.columns]
)

print(f"\nNumeric Features : {len(numeric_df.columns)}")

# ==========================================================
# CORRELATION MATRIX
# ==========================================================

print("\nComputing correlation matrix...")

corr = numeric_df.corr()

corr.to_csv(
    REPORT_DIR / "correlation_matrix.csv"
)

# ==========================================================
# HIGH CORRELATION PAIRS
# ==========================================================

upper = corr.abs().where(

    np.triu(

        np.ones(corr.shape),

        k=1

    ).astype(bool)

)

pairs = []

THRESHOLD = 0.90

for column in upper.columns:

    for row in upper.index:

        value = upper.loc[row, column]

        if pd.notna(value) and value >= THRESHOLD:

            pairs.append({

                "Feature A": row,

                "Feature B": column,

                "Correlation": corr.loc[row, column]

            })

pairs = pd.DataFrame(pairs)

if not pairs.empty:

    pairs = pairs.sort_values(

        "Correlation",

        key=np.abs,

        ascending=False

    )

pairs.to_csv(

    REPORT_DIR / "high_correlation_pairs.csv",

    index=False

)

# ==========================================================
# HEATMAP
# ==========================================================

print("\nGenerating heatmap...")

plt.figure(figsize=(18, 15))

im = plt.imshow(

    corr,

    cmap="coolwarm",

    vmin=-1,

    vmax=1

)

plt.colorbar(im)

plt.xticks(

    range(len(corr.columns)),

    corr.columns,

    rotation=90,

    fontsize=8

)

plt.yticks(

    range(len(corr.columns)),

    corr.columns,

    fontsize=8

)

plt.title("Feature Correlation Matrix")

plt.tight_layout()

plt.savefig(

    REPORT_DIR / "correlation_heatmap.png",

    dpi=300

)

plt.close()

# ==========================================================
# SUMMARY
# ==========================================================

print()

print("=" * 70)

print("Highly Correlated Pairs")

print("=" * 70)

if len(pairs):

    print(pairs)

else:

    print("None")

print()

print("Reports saved to")

print(REPORT_DIR)

print()

print("=" * 70)
print("DONE")
print("=" * 70) 