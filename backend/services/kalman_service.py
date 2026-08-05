import numpy as np
from typing import Dict, Tuple

class KalmanTrajectoryFilter:
    """
    Linear 2D/3D Kalman Filter for Drone Trajectory Estimation and Anomaly Detection.
    State Vector: X = [lat, lon, vx, vy]^T
    """
    def __init__(self, dt: float = 1.0):
        self.dt = dt
        
        # State transition matrix (Constant Velocity model)
        self.F = np.array([
            [1.0, 0.0, self.dt, 0.0],
            [0.0, 1.0, 0.0, self.dt],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0]
        ])
        
        # Measurement matrix (observing lat, lon)
        self.H = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0]
        ])
        
        # Process noise covariance
        self.Q = np.eye(4) * 0.0001
        
        # Measurement noise covariance
        self.R = np.eye(2) * 0.001
        
        # Drone track histories: drone_id -> state vector X
        self.tracks: Dict[str, np.ndarray] = {}
        # Drone error covariances: drone_id -> P matrix
        self.covariances: Dict[str, np.ndarray] = {}

    def predict_and_update(self, drone_id: str, lat: float, lon: float) -> Tuple[float, float, float, bool]:
        """
        Runs Kalman prediction and measurement update.
        Returns: (predicted_lat, predicted_lon, deviation_distance_meters, is_trajectory_anomaly)
        """
        z = np.array([lat, lon])
        
        if drone_id not in self.tracks:
            # Initialize track
            x_init = np.array([lat, lon, 0.0, 0.0])
            self.tracks[drone_id] = x_init
            self.covariances[drone_id] = np.eye(4) * 1.0
            return lat, lon, 0.0, False
            
        x_prev = self.tracks[drone_id]
        P_prev = self.covariances[drone_id]
        
        # 1. Prediction Step
        x_pred = self.F @ x_prev
        P_pred = self.F @ P_prev @ self.F.T + self.Q
        
        # 2. Compute Innovation / Measurement Residual
        z_pred = self.H @ x_pred
        y_residual = z - z_pred
        
        # Estimate deviation in approximate meters (1 deg ~ 111,000 m)
        dev_lat_m = y_residual[0] * 111000.0
        dev_lon_m = y_residual[1] * 111000.0
        deviation_m = float(np.sqrt(dev_lat_m**2 + dev_lon_m**2))
        
        # 3. Kalman Gain & Update Step
        S = self.H @ P_pred @ self.H.T + self.R
        K = P_pred @ self.H.T @ np.linalg.inv(S)
        
        x_updated = x_pred + K @ y_residual
        P_updated = (np.eye(4) - K @ self.H) @ P_pred
        
        self.tracks[drone_id] = x_updated
        self.covariances[drone_id] = P_updated
        
        # Anomaly threshold: > 150 meters sudden deviation or impossible jump
        is_anomaly = deviation_m > 150.0
        
        return float(x_pred[0]), float(x_pred[1]), round(deviation_m, 2), is_anomaly

kalman_filter = KalmanTrajectoryFilter()
