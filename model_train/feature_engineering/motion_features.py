"""
========================================================

Motion Feature Engineering

Features:
    speed_change
    altitude_change
    roll_change
    pitch_change
    yaw_change
    vertical_speed

========================================================
"""

import numpy as np
import pandas as pd


# -------------------------------------------------------
# Angle Wrapping
# -------------------------------------------------------

def angle_difference(series: pd.Series) -> pd.Series:
    """
    Computes the smallest angular difference.

    Example

        179 -> -179

    returns

        +2
    """

    diff = series.diff()

    diff = (diff + 180) % 360 - 180

    return diff


# -------------------------------------------------------
# Motion Features
# -------------------------------------------------------

def add_motion_features(df: pd.DataFrame) -> pd.DataFrame:

    print("\nCreating Motion Features...")

    groups = df.groupby(
        "flight_id",
        sort=False
    )

    # -----------------------------------------------
    # Speed
    # -----------------------------------------------

    df["speed_change"] = groups["speed"].diff()

    # -----------------------------------------------
    # Altitude
    # -----------------------------------------------

    df["altitude_change"] = groups["altitude"].diff()

    # -----------------------------------------------
    # Roll
    # -----------------------------------------------

    df["roll_change"] = groups["roll"].transform(
        angle_difference
    )

    # -----------------------------------------------
    # Pitch
    # -----------------------------------------------

    df["pitch_change"] = groups["pitch"].transform(
        angle_difference
    )

    # -----------------------------------------------
    # Yaw
    # -----------------------------------------------

    df["yaw_change"] = groups["yaw"].transform(
        angle_difference
    )

    # -----------------------------------------------
    # Time Difference
    # -----------------------------------------------

    dt = groups["timestamp"].diff()

    # PX4 timestamps are usually in microseconds
    dt = dt / 1_000_000

    dt = dt.replace(0, np.nan)

    df["time_delta"] = dt

    # -----------------------------------------------
    # Vertical Speed
    # -----------------------------------------------

    df["vertical_speed"] = (
        df["altitude_change"] /
        df["time_delta"]
    )

    print("✓ Motion Features Added")

    return df