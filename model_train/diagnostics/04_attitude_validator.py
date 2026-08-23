from pathlib import Path
import pandas as pd

MODEL_ROOT = Path(__file__).resolve().parent.parent
SIM_ROOT = MODEL_ROOT / "dataset" / "Simulated - OTU Survey"

records = []

for airframe in SIM_ROOT.iterdir():

    if not airframe.is_dir():
        continue

    for attack in airframe.iterdir():

        if not attack.is_dir():
            continue

        attitude_files = list(attack.glob("*vehicle_attitude*.csv"))

        for file in attitude_files:

            df = pd.read_csv(file)

            records.append({

                "airframe": airframe.name,
                "attack": attack.name,
                "file": file.name,
                "rows": len(df),

                "columns": len(df.columns),

                "has_roll": "roll" in df.columns,

                "has_pitch": "pitch" in df.columns,

                "has_yaw": "yaw" in df.columns,

                "missing_roll": df["roll"].isna().sum()
                    if "roll" in df.columns else None,

                "missing_pitch": df["pitch"].isna().sum()
                    if "pitch" in df.columns else None,

                "missing_yaw": df["yaw"].isna().sum()
                    if "yaw" in df.columns else None

            })

pd.DataFrame(records).to_csv(
    MODEL_ROOT /
    "reports" /
    "attitude_validation.csv",
    index=False
)