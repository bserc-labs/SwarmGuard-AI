import os
import pandas as pd
import numpy as np
import joblib
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix

def train_swarmguard_models(
    csv_path="backend/data/swarmguard_training_dataset.csv",
    output_dir="backend/models_ml"
):
    os.makedirs(output_dir, exist_ok=True)

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Dataset not found at {csv_path}. Run generate_dataset.py first.")

    print(f"📦 Loading dataset from {csv_path}...")
    df = pd.read_csv(csv_path)

    feature_cols = [
        "latitude", "longitude", "altitude", "speed", "battery",
        "packet_sequence", "speed_alt_ratio", "battery_drain_rate"
    ]

    X = df[feature_cols].values
    y_anomaly = df["is_anomaly"].values
    y_attack = df["attack_type"].values

    # Train/Test Split
    X_train, X_test, y_anomaly_train, y_anomaly_test, y_attack_train, y_attack_test = train_test_split(
        X, y_anomaly, y_attack, test_size=0.2, random_state=42, stratify=y_attack
    )

    # 1. Fit Feature Scaler
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # 2. Train Isolation Forest for Anomaly Detection (contamination=0.05 as per best practices)
    print("\n🤖 Training Isolation Forest Anomaly Detector...")
    # Train on normal samples in training set for clean baseline
    normal_train_mask = (y_anomaly_train == 0)
    iso_forest = IsolationForest(n_estimators=200, contamination=0.05, random_state=42)
    iso_forest.fit(X_train_scaled[normal_train_mask])

    # Evaluate Isolation Forest on test set
    test_preds = iso_forest.predict(X_test_scaled)
    # Convert (-1: anomaly, 1: normal) to (1: anomaly, 0: normal)
    test_anomaly_preds = np.where(test_preds == -1, 1, 0)
    
    print("\n--- Anomaly Detection Evaluation (Isolation Forest) ---")
    print(classification_report(y_anomaly_test, test_anomaly_preds, target_names=["NORMAL", "ANOMALY"]))

    # 3. Train Random Forest Classifier for Attack Type Classification
    print("🤖 Training Random Forest Attack Classifier...")
    attack_classifier = RandomForestClassifier(n_estimators=100, random_state=42)
    attack_classifier.fit(X_train_scaled, y_attack_train)

    attack_preds = attack_classifier.predict(X_test_scaled)

    print("\n--- Attack Classification Evaluation (Random Forest) ---")
    print(classification_report(y_attack_test, attack_preds))
    print("Confusion Matrix:")
    print(confusion_matrix(y_attack_test, attack_preds))

    # 4. Save Model Artifacts
    scaler_path = os.path.join(output_dir, "scaler.joblib")
    iso_path = os.path.join(output_dir, "isolation_forest.joblib")
    clf_path = os.path.join(output_dir, "attack_classifier.joblib")

    joblib.dump(scaler, scaler_path)
    joblib.dump(iso_forest, iso_path)
    joblib.dump(attack_classifier, clf_path)

    print(f"\n✅ All 3 ML model artifacts saved to {output_dir}/:")
    print(f"   - Scaler: {scaler_path}")
    print(f"   - Anomaly Detector: {iso_path}")
    print(f"   - Attack Classifier: {clf_path}")

if __name__ == "__main__":
    train_swarmguard_models()
