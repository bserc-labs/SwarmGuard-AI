from motion_features import add_motion_features
import pandas as pd

df = pd.read_csv("../dataset/raw_dataset.csv")

df = add_motion_features(df)

print(df.columns)

print(df[
    [
        "speed_change",
        "altitude_change",
        "yaw_change",
        "vertical_speed"
    ]
].head(20))