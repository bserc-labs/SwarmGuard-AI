"""
============================================================

SwarmGuard AI
Feature Engineering Pipeline (v1)

Creates:
    - speed_change
    - altitude_change
    - roll_change
    - pitch_change
    - yaw_change
    - time_delta
    - vertical_speed

============================================================
"""

from pathlib import Path
import numpy as np
import pandas as pd
from math import radians

# ==========================================================
# PATHS
# ==========================================================

SCRIPT_DIR = Path(__file__).resolve().parent

MODEL_ROOT = SCRIPT_DIR.parent

DATASET_DIR = MODEL_ROOT / "dataset"

RAW_DATASET = DATASET_DIR / "raw_dataset.csv"

OUTPUT_DATASET = DATASET_DIR / "feature_dataset.csv"

# ==========================================================
# LOAD
# ==========================================================

def load_dataset():

    print("=" * 70)
    print("Loading Dataset")
    print("=" * 70)

    df = pd.read_csv(RAW_DATASET)

    print(f"Rows    : {len(df):,}")
    print(f"Columns : {len(df.columns)}")

    return df


# ==========================================================
# SORT
# ==========================================================

def sort_dataset(df):

    print("\nSorting Dataset...")

    return (

        df

        .sort_values(

            [

                "flight_id",

                "timestamp"

            ]

        )

        .reset_index(drop=True)

    )


# ==========================================================
# DROP FEATURES
# ==========================================================

def drop_constant_features(df):

    print("\nDropping Constant Features...")

    drop = []

    for col in [

        "fix_type",

        "satellites_used"

    ]:

        if col in df.columns:

            drop.append(col)

    print("Dropped :", drop)

    return df.drop(columns=drop)


# ==========================================================
# ANGLE DIFFERENCE
# ==========================================================

def angle_difference(series):

    diff = series.diff()

    diff = (diff + 180) % 360 - 180

    return diff


# ==========================================================
# MOTION FEATURES
# ==========================================================

def add_motion_features(df):

    print("\nCreating Motion Features...")

    flights = df.groupby(

        "flight_id",

        sort=False

    )

    # ------------------------------------------------------

    df["speed_change"] = flights["speed"].diff()

    df["altitude_change"] = flights["altitude"].diff()

    df["roll_change"] = (

        flights["roll"]

        .transform(angle_difference)

    )

    df["pitch_change"] = (

        flights["pitch"]

        .transform(angle_difference)

    )

    df["yaw_change"] = (

        flights["yaw"]

        .transform(angle_difference)

    )

    # ------------------------------------------------------
    # Time Delta
    # ------------------------------------------------------

    dt = flights["timestamp"].diff()

    dt = dt / 1_000_000

    dt = dt.replace(

        0,

        np.nan

    )

    df["time_delta"] = dt

    # ------------------------------------------------------
    # Vertical Speed
    # ------------------------------------------------------

    df["vertical_speed"] = (

        df["altitude_change"]

        /

        df["time_delta"]

    )

    print("✓ Motion Features Added")

    return df

# ==========================================================
# GPS FEATURES
# ==========================================================

EARTH_RADIUS = 6371000.0  # metres


def haversine_vectorized(lat1, lon1, lat2, lon2):
    """
    Vectorized Haversine distance in metres.
    """

    lat1 = np.radians(lat1)
    lon1 = np.radians(lon1)

    lat2 = np.radians(lat2)
    lon2 = np.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(lat1)
        * np.cos(lat2)
        * np.sin(dlon / 2.0) ** 2
    )

    c = 2 * np.arctan2(
        np.sqrt(a),
        np.sqrt(1 - a)
    )

    return EARTH_RADIUS * c


def add_gps_features(df):

    print("\nCreating GPS Features...")

    flights = df.groupby(
        "flight_id",
        sort=False
    )

    prev_lat = flights["latitude"].shift(1)
    prev_lon = flights["longitude"].shift(1)

    # --------------------------------------------------
    # GPS Jump Distance
    # --------------------------------------------------

    df["gps_jump_distance"] = haversine_vectorized(
        prev_lat,
        prev_lon,
        df["latitude"],
        df["longitude"]
    )

    # --------------------------------------------------
    # GPS Speed
    # --------------------------------------------------

    df["gps_speed"] = (
        df["gps_jump_distance"]
        /
        df["time_delta"]
    )

    df.loc[
        df["time_delta"] <= 0,
        "gps_speed"
    ] = np.nan

    # --------------------------------------------------
    # GPS Acceleration
    # --------------------------------------------------

    flights = df.groupby(
        "flight_id",
        sort=False
    )

    df["gps_acceleration"] = (
        flights["gps_speed"].diff()
        /
        df["time_delta"]
    )

    # --------------------------------------------------
    # Log Features
    # --------------------------------------------------

    df["gps_jump_log"] = np.log1p(
        df["gps_jump_distance"]
    )

    df["gps_speed_log"] = np.log1p(
        df["gps_speed"]
    )

    # --------------------------------------------------
    # Speed Consistency
    # --------------------------------------------------

    df["gps_speed_error"] = (
        df["gps_speed"]
        -
        df["speed"]
    )

    df["gps_speed_error_abs"] = (
        df["gps_speed_error"].abs()
    )

    # --------------------------------------------------
    # Relative Error
    # --------------------------------------------------

    df["gps_speed_error_ratio"] = (
        df["gps_speed_error_abs"]
        /
        (df["speed"].abs() + 1e-6)
    )

    print("✓ GPS Features Added")

    return df

# ==========================================================
# SAVE
# ==========================================================

def save_dataset(df):

    print("\nSaving Dataset...")

    df.to_csv(

        OUTPUT_DATASET,

        index=False

    )

    print("Saved to")

    print(OUTPUT_DATASET)


# ==========================================================
# MAIN
# ==========================================================

def main():

    df = load_dataset()

    df = sort_dataset(df)

    df = drop_constant_features(df)

    df = add_motion_features(df)

    df = add_gps_features(df)


    save_dataset(df)

    print()

    print("=" * 70)

    print("Feature Engineering Complete")

    print("=" * 70)

    print()

    print(df.head())

    gps_columns =[

    "gps_jump_distance",

    "gps_jump_log",

    "gps_speed",

    "gps_speed_log",

    "gps_speed_error",

    "gps_speed_error_abs",

    "gps_speed_error_ratio",

    "gps_acceleration"]

    print()

    print(df[gps_columns].describe().T)


if __name__ == "__main__":

    main()