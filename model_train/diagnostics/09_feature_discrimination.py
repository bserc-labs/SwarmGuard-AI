"""
============================================================

Feature Discrimination Report

Purpose
--------
Evaluate how useful every feature is before training.

============================================================
"""

from pathlib import Path
import pandas as pd
import numpy as np

# ==========================================================
# PATHS
# ==========================================================

MODEL_ROOT = Path(__file__).resolve().parent.parent

DATASET = MODEL_ROOT / "dataset" / "feature_dataset.csv"

REPORT_DIR = MODEL_ROOT / "reports" / "feature_discrimination"

REPORT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 70)
print("FEATURE DISCRIMINATION")
print("=" * 70)

# ==========================================================
# LOAD
# ==========================================================

df = pd.read_csv(DATASET)

print()

print(f"Rows    : {len(df):,}")

print(f"Columns : {len(df.columns)}")

# ==========================================================
# NUMERIC FEATURES
# ==========================================================

numeric = df.select_dtypes(include=np.number).columns.tolist()

# Don't evaluate timestamp or target labels
remove = [
    "timestamp",
    "is_attack"
]

numeric = [c for c in numeric if c not in remove]

summary_rows = []

attack_rows = []

# ==========================================================
# FEATURE SUMMARY
# ==========================================================

print()

print("Analysing Features...")

for feature in numeric:

    series = df[feature]

    summary_rows.append({

        "feature": feature,

        "missing_percent":
            round(series.isna().mean() * 100, 2),

        "variance":
            float(series.var()),

        "unique":
            int(series.nunique()),

        "mean":
            float(series.mean()),

        "std":
            float(series.std()),

        "median":
            float(series.median())

    })

    # ------------------------------------------

    # Per attack statistics

    # ------------------------------------------

    grouped = (

        df

        .groupby("attack_type")[feature]

    )

    for attack, values in grouped:

        attack_rows.append({

            "feature": feature,

            "attack_type": attack,

            "count": values.count(),

            "mean": values.mean(),

            "median": values.median(),

            "std": values.std(),

            "min": values.min(),

            "max": values.max(),

            "q25": values.quantile(0.25),

            "q75": values.quantile(0.75)

        })

# ==========================================================
# SAVE
# ==========================================================

summary = pd.DataFrame(summary_rows)

attack_stats = pd.DataFrame(attack_rows)

summary.to_csv(

    REPORT_DIR / "feature_summary.csv",

    index=False

)

attack_stats.to_csv(

    REPORT_DIR / "attack_statistics.csv",

    index=False

)

# ==========================================================
# LOW VARIANCE
# ==========================================================

low_variance = summary[

    summary["variance"] < 1e-8

]

low_variance.to_csv(

    REPORT_DIR / "low_variance_features.csv",

    index=False

)

# ==========================================================
# HIGH MISSING
# ==========================================================

missing = summary[

    summary["missing_percent"] > 20

]

missing.to_csv(

    REPORT_DIR / "missing_features.csv",

    index=False

)

# ==========================================================
# SIMPLE FEATURE SCORE
# ==========================================================

scores = []

for feature in numeric:

    means = (

        df

        .groupby("attack_type")[feature]

        .mean()

    )

    if len(means) < 2:

        continue

    score = means.max() - means.min()

    scores.append({

        "feature": feature,

        "mean_separation": score

    })

ranking = (

    pd.DataFrame(scores)

    .sort_values(

        "mean_separation",

        ascending=False

    )

)

ranking.to_csv(

    REPORT_DIR / "feature_ranking.csv",

    index=False

)

# ==========================================================
# CONSOLE
# ==========================================================

print()

print("=" * 70)

print("Top 20 Features")

print("=" * 70)

print()

print(ranking.head(20))

print()

print("=" * 70)

print("High Missing Features")

print("=" * 70)

print()

print(missing)

print()

print("=" * 70)

print("Low Variance Features")

print("=" * 70)

print()

print(low_variance)

print()

print("Reports saved to")

print(REPORT_DIR)