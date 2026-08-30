"""
==========================================================

Topic Audit

Purpose:

Inspect EVERY original CSV before merging.

==========================================================
"""

from pathlib import Path
import pandas as pd
import re

# ==========================================================
# PATHS
# ==========================================================

MODEL_ROOT = Path(__file__).resolve().parent.parent

SIM_ROOT = MODEL_ROOT / "dataset" / "Simulated - OTU Survey"

REPORT_DIR = MODEL_ROOT / "reports" / "topic_audit"

REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ==========================================================
# Utilities
# ==========================================================

def get_prefix(filename: str):

    """
    Extract

    log_6_2020-8-1-21-26-31

    from

    log_6_2020-8-1-21-26-31_vehicle_attitude_0.csv
    """

    m = re.match(r"(log_\d+_[\d\-]+)", filename)

    if m:
        return m.group(1)

    return None


def get_topic(filename: str):

    """
    Extract

    vehicle_attitude

    from

    log_6_2020...vehicle_attitude_0.csv
    """

    prefix = get_prefix(filename)

    if prefix is None:
        return None

    topic = filename.replace(prefix + "_", "")

    topic = re.sub(r"_\d+\.csv$", "", topic)

    return topic


# ==========================================================
# Scan Dataset
# ==========================================================

records = []

print("=" * 70)
print("Scanning Dataset")
print("=" * 70)

for airframe in sorted(SIM_ROOT.iterdir()):

    if not airframe.is_dir():
        continue

    print(f"\n{airframe.name}")

    for attack in sorted(airframe.iterdir()):

        if not attack.is_dir():
            continue

        csvs = list(attack.glob("*.csv"))

        flights = {}

        for csv in csvs:

            prefix = get_prefix(csv.name)

            topic = get_topic(csv.name)

            if prefix is None:
                continue

            if prefix not in flights:
                flights[prefix] = []

            flights[prefix].append((topic, csv))

        print(
            f"    {attack.name:<20}"
            f"Flights : {len(flights)}"
        )

        for flight in flights:

            for topic, csv in flights[flight]:

                try:

                    rows = len(pd.read_csv(csv))

                except Exception:

                    rows = -1

                records.append({

                    "airframe": airframe.name,

                    "attack": attack.name,

                    "flight": flight,

                    "topic": topic,

                    "rows": rows,

                    "filename": csv.name

                })

# ==========================================================
# Save Inventory
# ==========================================================

inventory = pd.DataFrame(records)

inventory.to_csv(

    REPORT_DIR / "topic_inventory.csv",

    index=False

)

# ==========================================================
# Flight Summary
# ==========================================================

summary = (

    inventory

    .groupby(

        [

            "airframe",

            "attack",

            "flight"

        ]

    )

    .agg(

        Topics=("topic","count"),

        TotalRows=("rows","sum")

    )

    .reset_index()

)

summary.to_csv(

    REPORT_DIR / "flight_summary.csv",

    index=False

)

# ==========================================================
# Topic Presence Matrix
# ==========================================================

presence = (

    inventory

    .pivot_table(

        index=[

            "airframe",

            "attack",

            "flight"

        ],

        columns="topic",

        values="rows",

        aggfunc="first"

    )

)

presence.to_csv(

    REPORT_DIR / "topic_presence.csv"

)

# ==========================================================
# Topic Statistics
# ==========================================================

topic_stats = (

    inventory

    .groupby("topic")

    .agg(

        Flights=("flight","count"),

        AvgRows=("rows","mean"),

        MinRows=("rows","min"),

        MaxRows=("rows","max")

    )

)

topic_stats.to_csv(

    REPORT_DIR / "topic_statistics.csv"

)

# ==========================================================
# Missing Topics
# ==========================================================

missing = presence.isna().sum()

missing.to_csv(

    REPORT_DIR / "missing_topics.csv"

)

# ==========================================================
# Console
# ==========================================================

print()

print("="*70)

print("Topic Audit Complete")

print("="*70)

print()

print("Unique Flights :",inventory["flight"].nunique())

print("Unique Topics  :",inventory["topic"].nunique())

print()

print("Topics")

for t in sorted(inventory["topic"].unique()):

    print("   ",t)

print()

print("Reports saved to")

print(REPORT_DIR)