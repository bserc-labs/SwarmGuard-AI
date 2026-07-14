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
        Mock prediction.
        Returns 1 for normal, -1 for anomaly.
        """
        if not self.is_loaded:
            raise ValueError("Model must be loaded before prediction")
        
        # 10% chance of returning anomaly (-1)
        is_anomaly = random.random() < 0.1
        return np.array([-1 if is_anomaly else 1])
        
    def decision_function(self, X: np.ndarray) -> np.ndarray:
        """
        Mock anomaly score.
        Lower score = more anomalous.
        """
        if not self.is_loaded:
            raise ValueError("Model must be loaded before prediction")
            
        # Random score between -0.5 and 0.5
        score = random.uniform(-0.5, 0.5)
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
