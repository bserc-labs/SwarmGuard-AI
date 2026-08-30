from pathlib import Path
import pandas as pd

MODEL_ROOT = Path(__file__).resolve().parent.parent
SIM_ROOT = MODEL_ROOT / "dataset" / "Simulated - OTU Survey"
REPORT_DIR = MODEL_ROOT / "reports" / "gps_validation"

REPORT_DIR.mkdir(parents=True, exist_ok=True)

records = []

for airframe in SIM_ROOT.iterdir():

    if not airframe.is_dir():
        continue

    for attack in airframe.iterdir():

        if not attack.is_dir():
            continue

        gps_files = list(attack.glob("*vehicle_gps_position*.csv"))

        for gps in gps_files:

            try:
                df = pd.read_csv(gps)
            except Exception as e:
                print(f"Failed: {gps}")
                continue

            cols = df.columns

            def unique(col):
                if col not in cols:
                    return None
                return df[col].nunique(dropna=False)

            def minimum(col):
                if col not in cols:
                    return None
                return df[col].min()

            def maximum(col):
                if col not in cols:
                    return None
                return df[col].max()

            records.append({

                "airframe": airframe.name,
                "attack": attack.name,
                "file": gps.name,

                "rows": len(df),

                "sat_unique": unique("satellites_used"),
                "fix_unique": unique("fix_type"),
                "eph_unique": unique("eph"),
                "epv_unique": unique("epv"),

                "sat_min": minimum("satellites_used"),
                "sat_max": maximum("satellites_used"),

                "fix_min": minimum("fix_type"),
                "fix_max": maximum("fix_type"),

                "eph_min": minimum("eph"),
                "eph_max": maximum("eph"),

                "epv_min": minimum("epv"),
                "epv_max": maximum("epv")

            })

report = pd.DataFrame(records)

report.to_csv(
    REPORT_DIR / "gps_topic_report.csv",
    index=False
)

print(report)

print("\nSaved to")

print(REPORT_DIR)