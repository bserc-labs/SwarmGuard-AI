import pandas as pd

df = pd.read_csv("dataset/feature_dataset.csv")

print()

print("Yaw > 90 degrees")

print((df["yaw_change"].abs() > 90).sum())

print()

print("Yaw > 45 degrees")

print((df["yaw_change"].abs() > 45).sum())

print()

print("Yaw > 10 degrees")

print((df["yaw_change"].abs() > 10).sum())