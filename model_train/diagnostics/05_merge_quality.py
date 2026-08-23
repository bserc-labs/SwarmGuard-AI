"""
============================================================
Merge Quality Validator

Replays the merge performed in build_dataset.py and reports:

- Match percentage
- Missing values introduced
- Timestamp distance statistics
- Merge quality per topic

============================================================
"""

from pathlib import Path
import pandas as pd
import numpy as np

# ------------------------------------------------------------
# PATHS
# ------------------------------------------------------------

MODEL_ROOT = Path(__file__).resolve().parent.parent

SIM_ROOT = MODEL_ROOT / "dataset" / "Simulated - OTU Survey"

REPORT_DIR = MODEL_ROOT / "reports" / "merge_quality"

REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------
# Topics used in build_dataset.py
# ------------------------------------------------------------

TOPICS = {
    "battery": "battery_status",
    "attitude": "vehicle_attitude",
    "telemetry": "telemetry_status",
    "local_position": "vehicle_local_position"
}


def find_topic(folder, topic):

    files = list(folder.glob(f"*{topic}*.csv"))

    if len(files) == 0:
        return None

    return files[0]


records = []

# ------------------------------------------------------------

for airframe in sorted(SIM_ROOT.iterdir()):

    if not airframe.is_dir():
        continue

    for attack in sorted(airframe.iterdir()):

        if not attack.is_dir():
            continue

        gps_file = find_topic(
            attack,
            "vehicle_gps_position"
        )

        if gps_file is None:
            continue

        gps = pd.read_csv(gps_file)

        if "timestamp" not in gps.columns:
            continue

        gps = gps.sort_values("timestamp")

        print(
            f"\n{airframe.name} | {attack.name}"
        )

        print(
            f"GPS rows : {len(gps)}"
        )

        for name, topic in TOPICS.items():

            topic_file = find_topic(
                attack,
                topic
            )

            if topic_file is None:

                records.append({

                    "airframe": airframe.name,
                    "attack": attack.name,
                    "topic": name,

                    "gps_rows": len(gps),

                    "topic_rows": 0,

                    "matched_rows": 0,

                    "match_percent": 0,

                    "mean_timestamp_error_us": None,

                    "max_timestamp_error_us": None

                })

                continue

            df = pd.read_csv(topic_file)

            if "timestamp" not in df.columns:

                continue

            df = df.sort_values("timestamp")

            # --------------------------------------
            # Replay merge_asof exactly
            # --------------------------------------

            merged = pd.merge_asof(

                gps,

                df,

                on="timestamp",

                direction="nearest",

                suffixes=("", "_topic")

            )

            # --------------------------------------
            # Estimate timestamp error
            # --------------------------------------

            gps_ts = gps["timestamp"].to_numpy()

            topic_ts = df["timestamp"].to_numpy()

            distances = []

            j = 0

            for t in gps_ts:

                idx = np.searchsorted(topic_ts, t)

                candidates = []

                if idx > 0:
                    candidates.append(abs(t-topic_ts[idx-1]))

                if idx < len(topic_ts):
                    candidates.append(abs(topic_ts[idx]-t))

                if len(candidates):

                    distances.append(min(candidates))

            # --------------------------------------
            # Determine whether merge succeeded
            # --------------------------------------

            non_timestamp = [

                c for c in df.columns

                if c != "timestamp"

            ]

            if len(non_timestamp):

                matched = merged[
                    non_timestamp
                ].notna().any(axis=1).sum()

            else:

                matched = 0

            records.append({

                "airframe": airframe.name,

                "attack": attack.name,

                "topic": name,

                "gps_rows": len(gps),

                "topic_rows": len(df),

                "matched_rows": matched,

                "match_percent":
                    round(
                        matched/len(gps)*100,
                        2
                    ),

                "mean_timestamp_error_us":
                    np.mean(distances),

                "max_timestamp_error_us":
                    np.max(distances)

            })

# ------------------------------------------------------------
# Save
# ------------------------------------------------------------

report = pd.DataFrame(records)

report.to_csv(

    REPORT_DIR / "merge_quality.csv",

    index=False

)

print()

print("="*70)

print("Merge Summary")

print("="*70)

print()

print(report)

print()

print("Saved to")

print(REPORT_DIR)