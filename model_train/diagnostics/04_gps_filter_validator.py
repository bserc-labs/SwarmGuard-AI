"""
============================================================

GPS Filter Validator

Purpose
-------
Determine whether the preprocessing step

    fix_type >= 3
    latitude != 0
    longitude != 0

is responsible for making

    satellites_used
    eph
    epv
    fix_type

appear constant.

============================================================
"""

from pathlib import Path
import pandas as pd
import numpy as np

# ==========================================================
# PATHS
# ==========================================================

MODEL_ROOT = Path(__file__).resolve().parent.parent

SIM_ROOT = MODEL_ROOT / "dataset" / "Simulated - OTU Survey"

REPORT_DIR = MODEL_ROOT / "reports" / "gps_filter_validation"

REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ==========================================================
# HELPERS
# ==========================================================

def unique_count(df, col):
    if col not in df.columns:
        return None
    return df[col].nunique(dropna=False)

def min_val(df, col):
    if col not in df.columns:
        return None
    return df[col].min()

def max_val(df, col):
    if col not in df.columns:
        return None
    return df[col].max()

# ==========================================================
# MAIN
# ==========================================================

records = []

print("="*70)
print("GPS FILTER VALIDATOR")
print("="*70)

gps_files = list(SIM_ROOT.rglob("*vehicle_gps_position_0.csv"))

print(f"GPS files found : {len(gps_files)}")
print()

for gps_file in gps_files:

    try:
        df = pd.read_csv(gps_file)

    except Exception as e:
        print("Failed:", gps_file)
        continue

    before = df.copy()

    # ------------------------------------------------------
    # Convert GPS coordinates exactly like build_dataset.py
    # ------------------------------------------------------

    if before["lat"].abs().max() > 1000:

        before["latitude"] = before["lat"] / 1e7
        before["longitude"] = before["lon"] / 1e7

    else:

        before["latitude"] = before["lat"]
        before["longitude"] = before["lon"]

    # ------------------------------------------------------
    # Apply eph/epv sentinel logic
    # ------------------------------------------------------

    after = before.copy()

    for col in ["eph", "epv"]:

        if col in after.columns:
            after.loc[after[col] >= 655.0, col] = np.nan

    # ------------------------------------------------------
    # Apply SAME FILTER as build_dataset.py
    # ------------------------------------------------------

    mask = pd.Series(True, index=after.index)

    if "fix_type" in after.columns:

        mask &= after["fix_type"] >= 3

    mask &= ~(
        (after["latitude"] == 0)
        &
        (after["longitude"] == 0)
    )

    filtered = after[mask].copy()

    removed = len(after) - len(filtered)

    record = {

        "file": gps_file.name,

        "rows_before": len(before),
        "rows_after": len(filtered),
        "rows_removed": removed,
        "percent_removed":
            round(
                removed / len(before) * 100,
                2
            ),

        # -------------------------------
        # FIX TYPE
        # -------------------------------

        "fix_unique_before":
            unique_count(before, "fix_type"),

        "fix_unique_after":
            unique_count(filtered, "fix_type"),

        "fix_min_before":
            min_val(before, "fix_type"),

        "fix_max_before":
            max_val(before, "fix_type"),

        "fix_min_after":
            min_val(filtered, "fix_type"),

        "fix_max_after":
            max_val(filtered, "fix_type"),

        # -------------------------------
        # SATELLITES
        # -------------------------------

        "sat_unique_before":
            unique_count(before, "satellites_used"),

        "sat_unique_after":
            unique_count(filtered, "satellites_used"),

        # -------------------------------
        # EPH
        # -------------------------------

        "eph_unique_before":
            unique_count(before, "eph"),

        "eph_unique_after":
            unique_count(filtered, "eph"),

        "eph_min_after":
            min_val(filtered, "eph"),

        "eph_max_after":
            max_val(filtered, "eph"),

        # -------------------------------
        # EPV
        # -------------------------------

        "epv_unique_before":
            unique_count(before, "epv"),

        "epv_unique_after":
            unique_count(filtered, "epv"),

        "epv_min_after":
            min_val(filtered, "epv"),

        "epv_max_after":
            max_val(filtered, "epv"),
    }

    records.append(record)

# ==========================================================
# SAVE
# ==========================================================

report = pd.DataFrame(records)

report = report.sort_values(
    ["file"]
)

report.to_csv(
    REPORT_DIR / "gps_filter_report.csv",
    index=False
)

print(report)

print()
print("="*70)
print("SUMMARY")
print("="*70)

print()

print("Flights analysed :", len(report))

print()

print("Average rows removed :")

print(report["percent_removed"].mean())

print()

print("Rows removed per flight")

print(
    report[
        [
            "file",
            "rows_removed",
            "percent_removed"
        ]
    ]
)

print()

print("Unique fix_type BEFORE")

print(report["fix_unique_before"].value_counts())

print()

print("Unique fix_type AFTER")

print(report["fix_unique_after"].value_counts())

print()

print("Unique satellites BEFORE")

print(report["sat_unique_before"].value_counts())

print()

print("Unique satellites AFTER")

print(report["sat_unique_after"].value_counts())

print()

print("Saved to")

print(REPORT_DIR)