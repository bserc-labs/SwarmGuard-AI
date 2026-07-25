import numpy as np
import random

class DummyIsolationForest:
    def __init__(self):
        self.is_loaded = False
        
    def load(self, model_path: str = None):
        """Mock method to load a trained model."""
        self.is_loaded = True
        return self
        
    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        Rule-based dummy prediction for predictable demo telemetry.
        Returns 1 for normal, -1 for anomaly.
        Features expected: [lat, lng, alt, speed, battery, seq]
        """
        if not self.is_loaded:
            raise ValueError("Model must be loaded before prediction")
        
        # Check rule thresholds (e.g. speed > 45 m/s, altitude < 25m, or battery < 15%)
        features = X[0]
        alt = features[2] if len(features) > 2 else 50.0
        speed = features[3] if len(features) > 3 else 15.0
        battery = features[4] if len(features) > 4 else 80.0

        is_anomaly = (speed > 45.0) or (alt < 25.0) or (battery < 15.0)
        return np.array([-1 if is_anomaly else 1])
        
    def decision_function(self, X: np.ndarray) -> np.ndarray:
        """
        Rule-based anomaly score.
        Lower score = more anomalous.
        """
        if not self.is_loaded:
            raise ValueError("Model must be loaded before prediction")
            
        features = X[0]
        alt = features[2] if len(features) > 2 else 50.0
        speed = features[3] if len(features) > 3 else 15.0
        battery = features[4] if len(features) > 4 else 80.0

        if (speed > 45.0) or (alt < 25.0) or (battery < 15.0):
            # High anomaly -> negative score
            score = -0.45
        else:
            # Normal -> positive score
            score = 0.35

        return np.array([score])

class DummyClassifier:
    def __init__(self):
        self.is_loaded = False
        self.attack_types = ["GPS_SPOOFING", "JAMMING", "REPLAY_ATTACK", "DOS"]
        
    def load(self, model_path: str = None):
        self.is_loaded = True
        return self
        
    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self.is_loaded:
            raise ValueError("Model must be loaded before prediction")
        
        # Return a random attack type
        return np.array([random.choice(self.attack_types)])
