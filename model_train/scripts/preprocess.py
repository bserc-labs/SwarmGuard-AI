"""
preprocess.py — Step 3: Feature Engineering

Takes dataset/raw_dataset.csv (output of build_dataset.py) and adds derived
telemetry features, per flight (never diffing across flight boundaries).

Derived features:
  - speed_change     : row-to-row delta in `speed`
  - gps_delta_m       : great-circle distance (meters) between consecutive
                        (lat, lon) points — using the haversine formula
  - altitude_diff     : row-to-row delta in `altitude`
  - packet_loss_rate  : row-to-row delta in `packet_errors` (rate_txerr),
                        clipped at 0 (errors are cumulative counters in PX4,
                        so a negative diff means a counter reset, not "negative loss")
  - signal_drop       : row-to-row delta in `link_data_rate` (negative = link degrading);
                        also `heartbeat_gap_change` as a second signal-health proxy

Usage:
    python preprocess.py --in dataset/raw_dataset.csv --out dataset/clean_dataset.csv
"""

import argparse

import numpy as np
import pandas as pd

EARTH_RADIUS_M = 6371000.0


def haversine_delta(lat, lon, prev_lat, prev_lon):
    """Great-circle distance in meters between consecutive GPS points."""
    lat1, lon1, lat2, lon2 = map(np.radians, [prev_lat, prev_lon, lat, lon])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    c = 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    return EARTH_RADIUS_M * c


def add_derived_features(df):
    df = df.sort_values(["flight_id", "timestamp"]).reset_index(drop=True)
    grp = df.groupby("flight_id", sort=False)

    # --- speed change ---
    if "speed" in df.columns:
        df["speed_change"] = grp["speed"].diff()

    # --- GPS delta (distance moved since previous row, per flight) ---
    if {"latitude", "longitude"}.issubset(df.columns):
        prev_lat = grp["latitude"].shift(1)
        prev_lon = grp["longitude"].shift(1)
        df["gps_delta_m"] = haversine_delta(df["latitude"], df["longitude"], prev_lat, prev_lon)
        # first row of each flight has no "previous" point -> NaN (correct, not 0)
        df.loc[prev_lat.isna(), "gps_delta_m"] = np.nan

        # Raw distance alone conflates "big jump because of a long time gap"
        # with "big jump because of a spoofed teleport". Normalize by elapsed
        # time to get an implied speed, which is what actually flags a
        # physically-impossible movement.
        dt_s = grp["timestamp"].diff() / 1e6  # PX4 timestamps are microseconds
        df["implied_gps_speed"] = np.where(dt_s > 0, df["gps_delta_m"] / dt_s, np.nan)

    # --- altitude diff ---
    if "altitude" in df.columns:
        df["altitude_diff"] = grp["altitude"].diff()

    # --- packet loss rate (from cumulative tx error counter) ---
    if "packet_errors" in df.columns:
        raw_diff = grp["packet_errors"].diff()
        # counters can reset to 0 (e.g. link reconnect) producing a spurious
        # negative diff -> treat resets as "no new loss this row", not real loss
        df["packet_loss_rate"] = raw_diff.clip(lower=0)

    # --- signal drop proxies ---
    if "link_data_rate" in df.columns:
        df["signal_drop"] = grp["link_data_rate"].diff()  # negative = degrading
    if "heartbeat_gap" in df.columns:
        df["heartbeat_gap_change"] = grp["heartbeat_gap"].diff()

    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", default="dataset/raw_dataset.csv")
    ap.add_argument("--out", dest="outfile", default="dataset/clean_dataset.csv")
    args = ap.parse_args()

    df = pd.read_csv(args.infile)
    print(f"Loaded {len(df)} rows, {df['flight_id'].nunique()} flights")

    df = add_derived_features(df)

    new_cols = ["speed_change", "gps_delta_m", "implied_gps_speed", "altitude_diff",
                "packet_loss_rate", "signal_drop", "heartbeat_gap_change", "heartbeat_lost"]
    present = [c for c in new_cols if c in df.columns]
    print(f"Added derived features: {present}")
    print(df[present].describe().T)

    dead = [c for c in present if df[c].std(skipna=True) == 0]
    if dead:
        print(f"\n[warn] Zero-variance features (no discriminative value as-is): {dead}")

    # Diagnostic: confirm implied_gps_speed spikes line up with GPS Spoofing,
    # not a bug showing up in Normal flights.
    if "implied_gps_speed" in df.columns and "attack_type" in df.columns:
        top = df.nlargest(5, "implied_gps_speed")[
            ["flight_id", "attack_type", "timestamp", "gps_delta_m", "implied_gps_speed"]
        ]
        print("\nTop 5 implied_gps_speed rows (should be GPS Spoofing, not Normal):")
        print(top.to_string(index=False))

    # Diagnostic: is heartbeat_lost concentrated in Ping DoS, or spread evenly
    # (which would suggest it's just a startup/logging artifact, not a signal)?
    if "heartbeat_lost" in df.columns and "attack_type" in df.columns:
        rate = df.groupby("attack_type")["heartbeat_lost"].mean().sort_values(ascending=False)
        print("\nheartbeat_lost rate by attack_type (higher = more heartbeats missed):")
        print(rate.to_string())

    df.to_csv(args.outfile, index=False)
    print(f"\nWrote {len(df)} rows to {args.outfile}")


if __name__ == "__main__":
    main()
