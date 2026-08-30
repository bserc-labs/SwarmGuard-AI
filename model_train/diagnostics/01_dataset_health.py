

from pathlib import Path
import pandas as pd
import numpy as np

# ===========================================================
# Paths
# ===========================================================

MODEL_ROOT = Path(__file__).resolve().parent.parent

DATASET = MODEL_ROOT / "dataset" / "raw_dataset.csv"

REPORT_DIR = MODEL_ROOT / "reports" / "dataset_health"

REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ===========================================================
# Load Dataset
# ===========================================================

print("=" * 70)
print("Loading Dataset")
print("=" * 70)

df = pd.read_csv(DATASET)

print(f"Rows    : {len(df):,}")
print(f"Columns : {len(df.columns)}")
print()

# ===========================================================
# Dataset Summary
# ===========================================================

summary = []

summary.append(f"Rows: {len(df)}")
summary.append(f"Columns: {len(df.columns)}")
summary.append(f"Memory: {df.memory_usage(deep=True).sum()/1024/1024:.2f} MB")

summary.append("")
summary.append("Columns")

for c in df.columns:
    summary.append(f"{c:<30}{df[c].dtype}")

with open(REPORT_DIR/"dataset_summary.txt","w") as f:
    f.write("\n".join(summary))

# ===========================================================
# Missing Values
# ===========================================================

missing = pd.DataFrame({
    "Missing Count": df.isna().sum(),
    "Missing Percent": (df.isna().sum()/len(df)*100).round(2)
})

missing = missing.sort_values(
    "Missing Percent",
    ascending=False
)

missing.to_csv(REPORT_DIR/"missing_values.csv")

print("Missing Values")

print(missing)

print()

# ===========================================================
# Duplicate Rows
# ===========================================================

duplicates = df.duplicated().sum()

with open(REPORT_DIR/"duplicate_summary.txt","w") as f:

    f.write(f"Duplicate Rows : {duplicates}")

print("Duplicate Rows :",duplicates)

print()

# ===========================================================
# Constant Columns
# ===========================================================

constant = []

for c in df.columns:

    if df[c].nunique(dropna=False)==1:

        constant.append(c)

constant_df = pd.DataFrame({
    "Constant Columns":constant
})

constant_df.to_csv(
    REPORT_DIR/"constant_columns.csv",
    index=False
)

print("Constant Columns")

print(constant)

print()

# ===========================================================
# Unique Values
# ===========================================================

unique = pd.DataFrame({

    "Feature":df.columns,

    "Unique Values":[
        df[c].nunique(dropna=False)
        for c in df.columns
    ]

})

unique.to_csv(

    REPORT_DIR/"unique_counts.csv",

    index=False

)

# ===========================================================
# Numeric Summary
# ===========================================================

numeric = df.select_dtypes(
    include=np.number
)

numeric.describe().T.to_csv(

    REPORT_DIR/"numeric_summary.csv"

)

# ===========================================================
# Categorical Summary
# ===========================================================

cat = []

for c in df.select_dtypes(include="object"):

    values = df[c].value_counts()

    values.to_csv(

        REPORT_DIR/f"{c}_distribution.csv"

    )

# ===========================================================
# Range Validation
# ===========================================================

range_report = []

def check_range(column,min_val,max_val):

    if column not in df.columns:
        return

    invalid = df[
        (df[column]<min_val)
        |
        (df[column]>max_val)
    ]

    range_report.append({

        "Feature":column,

        "Invalid Rows":len(invalid),

        "Minimum Allowed":min_val,

        "Maximum Allowed":max_val

    })

check_range("battery",0,100)

check_range("latitude",-90,90)

check_range("longitude",-180,180)

check_range("speed",0,100)

check_range("roll",-180,180)

check_range("pitch",-180,180)

check_range("yaw",-360,360)

range_df = pd.DataFrame(range_report)

range_df.to_csv(

    REPORT_DIR/"invalid_ranges.csv",

    index=False

)

# ===========================================================
# Airframe Summary
# ===========================================================

if "airframe" in df.columns:

    df["airframe"].value_counts().to_csv(

        REPORT_DIR/"airframe_distribution.csv"

    )

# ===========================================================
# Attack Summary
# ===========================================================

if "attack_type" in df.columns:

    df["attack_type"].value_counts().to_csv(

        REPORT_DIR/"attack_distribution.csv"

    )

# ===========================================================
# Flight Summary
# ===========================================================

if "flight_id" in df.columns:

    flights = df.groupby("flight_id").size()

    flights.to_csv(

        REPORT_DIR/"flight_sizes.csv"

    )

# ===========================================================
# Console Summary
# ===========================================================

print("="*70)

print("Dataset Health Summary")

print("="*70)

print(f"Rows                 : {len(df):,}")

print(f"Columns              : {len(df.columns)}")

print(f"Duplicate Rows       : {duplicates}")

print(f"Constant Columns     : {len(constant)}")

print(f"Features With NaNs   : {(missing['Missing Count']>0).sum()}")

print()

print("Reports Saved To")

print(REPORT_DIR)

print("="*70)