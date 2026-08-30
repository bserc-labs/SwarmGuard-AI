"""
build_dataset.py

Merges per-topic PX4 ulog2csv exports (one CSV per topic per flight) into a
single flat telemetry dataset, labeled by attack type.

Expected folder layout (as exported by your UAVAttackData download):

    UAVAttackData/
      Simulated - OTU Survey/
        PX4-QUAD-SITL/
          Normal/
            log_6_2020-8-1-21-26-31_vehicle_gps_position_0.csv
            log_6_2020-8-1-21-26-31_battery_status_0.csv
            ...
          Ping DoS/
            001-2021-01-27-12-34-48-014_vehicle_gps_position_0.csv
            ...
          GPS Spoofing/
            log_0_2020-8-2-10-39-13_vehicle_gps_position_0.csv
            ...
        PX4-QUAD-HITL/
          ...
      ...

Usage:
    python build_dataset.py --root "/path/to/UAVAttackData" --out raw_dataset.csv

Notes on assumptions (PX4 ulog2csv standard schema):
  - vehicle_gps_position_0.csv:   timestamp, lat, lon, alt  (lat/lon are int, x1e7 -> degrees;
                                   alt is int, mm -> meters; eph/epv use 655.35 as "no fix" sentinel -> NaN;
                                   rows with fix_type < 3 or lat/lon == 0,0 are dropped as pre-fix startup noise)
  - battery_status_0.csv:         timestamp, remaining      (0-1 fraction -> x100 for %)
  - vehicle_local_position_0.csv: timestamp, vx, vy, vz     (speed = sqrt(vx^2+vy^2+vz^2))
  - vehicle_attitude_0.csv:       timestamp, q[0], q[1], q[2], q[3]  (quaternion -> roll/pitch/yaw)
  - telemetry_status_0.csv:       timestamp, data_rate, rate_txerr, heartbeat_time
                                   (no rssi in SITL - no real radio - so link_data_rate/packet_errors/
                                   heartbeat_gap are used as DoS/jamming proxies instead)

  jamming_indicator was tested and dropped: confirmed always 0 in SITL data (no
  real GPS receiver hardware to trigger it), so it carried zero signal.

If your actual column names differ slightly (PX4 firmware version differences),
edit the COLUMN name constants below to match — run inspect_topic() first on
one file to check.
"""

import argparse
import glob
import math
import os
import re
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

# ---- Topic -> which file suffix to look for, and which columns we need ----
TOPICS = {
    "gps": {
        "suffix": "vehicle_gps_position_0.csv",
        # NOTE: jamming_indicator deliberately excluded — confirmed always 0 in
        # SITL sims (no real receiver hardware to detect jamming), so it added
        # zero signal and was dropped after EDA.
        "cols": ["timestamp", "lat", "lon", "alt", "satellites_used", "eph", "epv", "fix_type"],
    },
    "battery": {
        "suffix": "battery_status_0.csv",
        "cols": ["timestamp", "remaining"],
    },
    "local_pos": {
        "suffix": "vehicle_local_position_0.csv",
        "cols": ["timestamp", "vx", "vy", "vz"],
    },
    "attitude": {
        "suffix": "vehicle_attitude_0.csv",
        "cols": ["timestamp", "q[0]", "q[1]", "q[2]", "q[3]"],
    },
    "telemetry": {
        "suffix": "telemetry_status_0.csv",
        # SITL sims have no real radio, so there's no rssi field. Use MAVLink
        # transport stats instead: rate_txerr (dropped/errored msgs) and
        # heartbeat_time (gaps -> link disruption) are good DoS proxies.
        "cols": ["timestamp", "data_rate", "rate_txerr", "heartbeat_time"],
    },
}


def inspect_topic(path):
    """Quick helper: print the actual column names in a topic CSV so you can
    fix the COLS lists above if your PX4 version logs different names."""
    df = pd.read_csv(path, nrows=5)
    print(f"\n{path}\ncolumns: {list(df.columns)}")
    print(df.head())


def quat_to_euler(q0, q1, q2, q3):
    """PX4 quaternion (w,x,y,z order: q[0]=w, q[1]=x, q[2]=y, q[3]=z) -> roll,pitch,yaw in degrees."""
    # roll (x-axis rotation)
    sinr_cosp = 2 * (q0 * q1 + q2 * q3)
    cosr_cosp = 1 - 2 * (q1 * q1 + q2 * q2)
    roll = np.arctan2(sinr_cosp, cosr_cosp)

    # pitch (y-axis rotation)
    sinp = 2 * (q0 * q2 - q3 * q1)
    sinp = np.clip(sinp, -1.0, 1.0)
    pitch = np.arcsin(sinp)

    # yaw (z-axis rotation)
    siny_cosp = 2 * (q0 * q3 + q1 * q2)
    cosy_cosp = 1 - 2 * (q2 * q2 + q3 * q3)
    yaw = np.arctan2(siny_cosp, cosy_cosp)

    return np.degrees(roll), np.degrees(pitch), np.degrees(yaw)


def find_flight_groups(attack_folder):
    """Group all CSVs in a folder by their flight-run prefix (everything
    before the topic name)."""
    all_csvs = glob.glob(os.path.join(attack_folder, "*.csv"))
    groups = defaultdict(dict)
    for f in all_csvs:
        fname = os.path.basename(f)
        for topic_key, meta in TOPICS.items():
            suffix = meta["suffix"]
            if fname.endswith(suffix):
                prefix = fname[: -len(suffix)].rstrip("_")
                groups[prefix][topic_key] = f
                break
    return groups


def load_topic(path, cols):
    df = pd.read_csv(path)
    missing = [c for c in cols if c not in df.columns]
    if missing:
        print(f"  [warn] {os.path.basename(path)} missing expected cols {missing}; "
              f"available: {list(df.columns)[:10]}...")
        cols = [c for c in cols if c in df.columns]
    return df[cols].copy()


def build_flight_dataframe(prefix, files, attack_label, airframe):
    frames = {}
    for topic_key, meta in TOPICS.items():
        if topic_key not in files:
            continue
        try:
            frames[topic_key] = load_topic(files[topic_key], meta["cols"])
        except Exception as e:
            print(f"  [error] failed to load {files[topic_key]}: {e}")

    if "gps" not in frames:
        print(f"  [skip] {prefix}: no GPS topic found, skipping flight")
        return None

    base = frames["gps"].sort_values("timestamp").rename(
        columns={"lat": "latitude_raw", "lon": "longitude_raw", "alt": "altitude_mm"}
    )
    # PX4 logs lat/lon as int scaled by 1e7
    if base["latitude_raw"].abs().max() > 1000:
        base["latitude"] = base["latitude_raw"] / 1e7
        base["longitude"] = base["longitude_raw"] / 1e7
    else:
        base["latitude"] = base["latitude_raw"]
        base["longitude"] = base["longitude_raw"]
    base = base.drop(columns=["latitude_raw", "longitude_raw"])

    # PX4 logs altitude in mm -> convert to meters
    base["altitude"] = base["altitude_mm"] / 1000.0
    base = base.drop(columns=["altitude_mm"])

    # eph/epv use 655.35 as a "no fix yet" sentinel (uint16 max scaled by 0.01) -> NaN
    for col in ("eph", "epv"):
        if col in base.columns:
            base.loc[base[col] >= 655.0, col] = np.nan

    # Drop pre-GPS-fix startup rows (lat/lon = 0,0 and/or fix_type < 3 = no 3D fix).
    # These are simulator boot-up rows, not real telemetry, and would otherwise
    # look like a bogus (0,0) location outlier to every downstream step.
    before = len(base)
    fix_mask = pd.Series(True, index=base.index)
    if "fix_type" in base.columns:
        fix_mask &= base["fix_type"] >= 3
    fix_mask &= ~((base["latitude"] == 0) & (base["longitude"] == 0))
    base = base[fix_mask].copy()
    dropped = before - len(base)
    if dropped:
        print(f"  [info] {prefix}: dropped {dropped} pre-GPS-fix startup rows")

    if base.empty:
        print(f"  [skip] {prefix}: no rows left after dropping pre-fix rows")
        return None

    merged = base

    if "battery" in frames:
        bat = frames["battery"].sort_values("timestamp").rename(columns={"remaining": "battery"})
        if bat["battery"].max() <= 1.0:
            bat["battery"] = bat["battery"] * 100.0
        merged = pd.merge_asof(merged, bat, on="timestamp", direction="nearest")

    if "local_pos" in frames:
        lp = frames["local_pos"].sort_values("timestamp").copy()
        lp["speed"] = np.sqrt(lp["vx"] ** 2 + lp["vy"] ** 2 + lp["vz"] ** 2)
        lp = lp[["timestamp", "speed"]]
        merged = pd.merge_asof(merged, lp, on="timestamp", direction="nearest")

    if "attitude" in frames:
        att = frames["attitude"].sort_values("timestamp").copy()
        roll, pitch, yaw = quat_to_euler(att["q[0]"], att["q[1]"], att["q[2]"], att["q[3]"])
        att["roll"], att["pitch"], att["yaw"] = roll, pitch, yaw
        att = att[["timestamp", "roll", "pitch", "yaw"]]
        merged = pd.merge_asof(merged, att, on="timestamp", direction="nearest")

    if "telemetry" in frames:
        tel = frames["telemetry"].sort_values("timestamp").rename(
            columns={"data_rate": "link_data_rate", "rate_txerr": "packet_errors"}
        )
        # heartbeat_time == 0 means "no heartbeat received yet" (same startup
        # sentinel pattern as eph/epv). Capture it as its own binary feature
        # BEFORE nulling it out -- a sustained "no heartbeat" state during
        # flight (not just at startup) could itself be a real DoS signal,
        # not just noise to discard.
        if "heartbeat_time" in tel.columns:
            tel["heartbeat_lost"] = (tel["heartbeat_time"] <= 0).astype(int)
            tel.loc[tel["heartbeat_time"] <= 0, "heartbeat_time"] = np.nan
        merged = pd.merge_asof(merged, tel, on="timestamp", direction="nearest")
        # heartbeat gap = time since last heartbeat vs current timestamp; a growing
        # gap signals link disruption (useful DoS/jamming proxy for "signal drop")
        if "heartbeat_time" in merged.columns:
            merged["heartbeat_gap"] = merged["timestamp"] - merged["heartbeat_time"]

    merged["packet_seq"] = range(len(merged))
    merged["attack_type"] = attack_label
    merged["is_attack"] = 0 if attack_label.strip().lower() == "normal" else 1
    merged["airframe"] = airframe
    merged["flight_id"] = prefix

    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="Path to UAVAttackData root (or the 'Simulated - OTU Survey' folder)")
    ap.add_argument("--out", default="raw_dataset.csv")
    ap.add_argument("--inspect", help="Path to a single topic CSV to print its columns, then exit")
    args = ap.parse_args()

    if args.inspect:
        inspect_topic(args.inspect)
        return

    all_flights = []

    # Walk two levels: <root>/<AIRFRAME>/<ATTACK_TYPE>/*.csv
    for airframe in sorted(os.listdir(args.root)):
        airframe_path = os.path.join(args.root, airframe)
        if not os.path.isdir(airframe_path):
            continue
        for attack_label in sorted(os.listdir(airframe_path)):
            attack_path = os.path.join(airframe_path, attack_label)
            if not os.path.isdir(attack_path):
                continue

            print(f"\n=== {airframe} / {attack_label} ===")
            groups = find_flight_groups(attack_path)
            if not groups:
                print("  (no matching topic CSVs found)")
                continue

            for prefix, files in groups.items():
                print(f"  flight {prefix}: topics found = {list(files.keys())}")
                df = build_flight_dataframe(prefix, files, attack_label, airframe)
                if df is not None:
                    all_flights.append(df)

    if not all_flights:
        print("\nNo flights were successfully parsed. Run with --inspect on one "
              "topic CSV to check column names match the script's assumptions.")
        sys.exit(1)

    final = pd.concat(all_flights, ignore_index=True)
    before_dedup = len(final)
    final = final.drop_duplicates(subset=["flight_id", "timestamp"], keep="first")
    if before_dedup != len(final):
        print(f"\n[info] Dropped {before_dedup - len(final)} duplicate (flight_id, timestamp) rows")
    final = final.sort_values(["airframe", "attack_type", "flight_id", "timestamp"])
    final.to_csv(args.out, index=False)
    print(f"\nDone. Wrote {len(final)} rows across {len(all_flights)} flights to {args.out}")
    print(f"Attack type counts:\n{final['attack_type'].value_counts()}")


if __name__ == "__main__":
    main()
