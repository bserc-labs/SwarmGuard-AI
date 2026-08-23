"""
============================================================

Source NaN Audit

Purpose
-------
Inspect every ORIGINAL PX4 topic CSV and determine:

- Which columns contain NaNs
- How many NaNs
- Percentage missing
- Whether an entire column is empty
- Whether values are constant

============================================================
"""

from pathlib import Path
import pandas as pd
import numpy as np

# ============================================================
# Paths
# ============================================================

MODEL_ROOT = Path(__file__).resolve().parent.parent

SIM_ROOT = MODEL_ROOT / "dataset" / "Simulated - OTU Survey"

REPORT_DIR = MODEL_ROOT / "reports" / "source_nan_audit"

REPORT_DIR.mkdir(parents=True, exist_ok=True)

records = []

print("=" * 70)
print("SOURCE NAN AUDIT")
print("=" * 70)

csv_files = sorted(SIM_ROOT.rglob("*.csv"))

print(f"CSV Files Found : {len(csv_files)}")
print()

# ============================================================
# Scan every CSV
# ============================================================

for csv_file in csv_files:

    try:
        df = pd.read_csv(csv_file)

    except Exception as e:

        print(f"Could not read {csv_file.name}")

        continue

    relative_path = csv_file.relative_to(SIM_ROOT)

    for column in df.columns:

        missing = int(df[column].isna().sum())

        total = len(df)

        percent = round(missing / total * 100, 2) if total else 0

        unique = df[column].nunique(dropna=False)

        constant = unique == 1

        all_nan = missing == total

        dtype = str(df[column].dtype)

        try:
            minimum = df[column].min()
            maximum = df[column].max()
        except Exception:
            minimum = None
            maximum = None

        records.append({

            "file": csv_file.name,

            "relative_path": str(relative_path),

            "topic": csv_file.stem,

            "column": column,

            "rows": total,

            "dtype": dtype,

            "missing_count": missing,

            "missing_percent": percent,

            "unique_values": unique,

            "constant": constant,

            "all_nan": all_nan,

            "minimum": minimum,

            "maximum": maximum

        })

# ============================================================
# Save master report
# ============================================================

report = pd.DataFrame(records)

report.to_csv(

    REPORT_DIR / "source_nan_report.csv",

    index=False

)

# ============================================================
# High Missing Columns
# ============================================================

high_missing = report[

    report["missing_percent"] > 0

].sort_values(

    "missing_percent",

    ascending=False

)

high_missing.to_csv(

    REPORT_DIR / "columns_with_missing.csv",

    index=False

)

# ============================================================
# Constant Columns
# ============================================================

constant = report[

    report["constant"]

]

constant.to_csv(

    REPORT_DIR / "constant_columns.csv",

    index=False

)

# ============================================================
# Completely Empty Columns
# ============================================================

empty = report[

    report["all_nan"]

]

empty.to_csv(

    REPORT_DIR / "all_nan_columns.csv",

    index=False

)

# ============================================================
# Summary by Topic
# ============================================================

summary = (

    report

    .groupby("file")

    .agg(

        Columns=("column", "count"),

        ColumnsWithNaN=("missing_count",
                        lambda x: (x > 0).sum()),

        TotalNaNs=("missing_count", "sum")

    )

)

summary.to_csv(

    REPORT_DIR / "topic_summary.csv"

)

# ============================================================
# Console Summary
# ============================================================

print("=" * 70)
print("SUMMARY")
print("=" * 70)

print()

print(f"CSV Files               : {len(csv_files)}")
print(f"Columns Analysed        : {len(report)}")

print()

print("Columns With Missing Values :")

print(len(high_missing))

print()

print("Constant Columns :")

print(len(constant))

print()

print("Completely Empty Columns :")

print(len(empty))

print()

print("Top 25 Columns With Highest Missing Percentage")

print()

display_cols = [

    "file",

    "column",

    "missing_percent",

    "missing_count",

    "rows"

]

print(

    high_missing[display_cols]

    .head(25)

)

print()

print("Reports saved to")

print(REPORT_DIR)

print("=" * 70)