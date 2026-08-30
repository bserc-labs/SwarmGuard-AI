"""
diagnostics/16_apply_confound_fixes.py — Apply ICC findings to produce a cleaned dataset

Based on 15_icc_confound_check.py results:
  DROP (ICC > 0.3, confirmed flight-identity confounds):
    battery (0.77), link_data_rate (0.67), pitch (0.65), speed (0.54)
  DROP (borderline, absolute clock-like value; heartbeat_gap is the
    already-clean derived alternative):
    heartbeat_time (0.26)

  ADD: link_data_rate_change -- a per-flight diff, following the same
  pattern that made pitch_change/speed_change come back essentially
  ICC=0.0000 while their raw counterparts were confounds. A PRIOR ratio-
  based normalization (value / flight's own median) was tested and found
  to wash out the Ping DoS signal -- this is a different transform
  (row-to-row diff, not ratio-to-baseline) and hasn't been tested yet.

pitch/speed are simply dropped rather than replaced, since pitch_change/
speed_change already exist in the dataset and are already clean.

Usage:
    python diagnostics/16_apply_confound_fixes.py \
        --in dataset/final_training_dataset.csv \
        --out dataset/final_training_dataset_v2.csv
"""

import argparse

import pandas as pd

DROP_COLS = ["battery", "link_data_rate", "pitch", "speed", "heartbeat_time"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", default="dataset/final_training_dataset.csv")
    ap.add_argument("--out", dest="outfile", default="dataset/final_training_dataset_v2.csv")
    args = ap.parse_args()

    df = pd.read_csv(args.infile)
    print(f"Loaded {len(df)} rows, {df.shape[1]} columns")

    if "link_data_rate" in df.columns and "flight_id" in df.columns:
        df = df.sort_values(["flight_id"]).reset_index(drop=True)
        df["link_data_rate_change"] = df.groupby("flight_id")["link_data_rate"].diff().fillna(0)
        print("Added link_data_rate_change (per-flight diff)")
    else:
        print("[warn] Could not add link_data_rate_change -- link_data_rate or flight_id missing")

    present_drop = [c for c in DROP_COLS if c in df.columns]
    missing_drop = [c for c in DROP_COLS if c not in df.columns]
    if missing_drop:
        print(f"[note] Already absent, nothing to drop: {missing_drop}")
    df = df.drop(columns=present_drop)
    print(f"Dropped confirmed confounds: {present_drop}")

    print(f"\nFinal shape: {df.shape}")
    df.to_csv(args.outfile, index=False)
    print(f"Wrote {args.outfile}")


if __name__ == "__main__":
    main()
