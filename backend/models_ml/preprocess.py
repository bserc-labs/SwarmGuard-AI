import numpy as np
import pandas as pd

from config import get_settings

settings = get_settings()

EARTH_RADIUS_M = 6371000.0


def haversine_vectorized(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres between consecutive fixes.

    Identical to the implementation in model_train/scripts/feature_engineering.py.
    The two must not drift: any difference here is train/serve skew, and it
    shows up as a model that scores well offline and misbehaves on the live
    feed for reasons nothing in the logs explains.
    """
    lat1, lon1 = np.radians(lat1), np.radians(lon1)
    lat2, lon2 = np.radians(lat2), np.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return EARTH_RADIUS_M * c


def angle_difference(series: pd.Series) -> pd.Series:
    """Signed shortest-arc difference in degrees, wrapped to (-180, 180].

    A plain .diff() on a compass heading reports 359 -> 1 as -358 rather than
    +2, which reads as a violent yaw event on every wrap-around.
    """
    diff = series.diff()
    return (diff + 180) % 360 - 180


class FeatureEngineer:
    """Builds the model's feature vector from a window of telemetry packets.

    Serves two feature families:

    * **v1 (synthetic)** -- rolling-window statistics over the original
      generated dataset. Retained so `MODEL_VERSION=v1` keeps working.
    * **v2 (deployable)** -- per-flight kinematic deltas and haversine GPS
      consistency features, matching the definitions used to train against the
      real PX4 ULog flights in model_train/.

    Which family is returned is driven by `settings.FEATURE_LIST`; both are
    computed, and `get_feature_columns()` selects. Computing both is cheap
    relative to a DB round trip and keeps a version switch from needing a code
    change.
    """

    def __init__(self, window_size=None, feature_columns: list[str] | None = None):
        self.window_size = window_size or settings.WINDOW_SIZE

        # The model's own metadata is the authority on what it was trained on.
        # settings.FEATURE_LIST is the fallback for callers that have no model
        # in hand. Deriving this from config alone meant switching
        # MODEL_VERSION without also editing FEATURE_LIST fed the new model the
        # old model's columns -- same shape, different meaning, no error.
        if feature_columns:
            self.feature_columns = list(feature_columns)
        else:
            self.feature_columns = [f.strip() for f in settings.FEATURE_LIST.split(",") if f.strip()]

        # Mapping engineered features back to raw telemetry sources
        self.feature_mapping = {
            # v1 synthetic family
            "speed_variance": ["speed"],
            "gps_drift": ["latitude", "longitude"],
            "altitude_deviation": ["altitude"],
            "battery_discharge_rate": ["battery"],
            "heading_deviation": ["heading"],
            "flight_mode_transitions": ["flight_mode"],
            "satellite_variation": ["satellites"],
            "velocity_consistency": ["speed"],
            # v2 deployable family
            "altitude": ["altitude"],
            "yaw": ["heading"],
            "speed_change": ["speed"],
            "yaw_change": ["heading"],
            "time_delta": ["created_at"],
            "vertical_speed": ["altitude", "created_at"],
            "gps_acceleration": ["latitude", "longitude", "created_at"],
            "gps_speed_error_abs": ["latitude", "longitude", "speed", "created_at"],
            "gps_speed_error_ratio": ["latitude", "longitude", "speed", "created_at"],
        }

    def get_feature_mapping(self) -> dict:
        """Returns the mapping of engineered features to raw fields for Explainable AI (SHAP) readiness."""
        return self.feature_mapping

    def _v1_features(self, group: pd.DataFrame) -> pd.DataFrame:
        """Rolling-window statistics. Original synthetic-dataset feature family."""
        group['speed_variance'] = group['speed'].rolling(window=self.window_size, min_periods=1).var().fillna(0)

        lat_diff = group['latitude'].diff().fillna(0)
        lon_diff = group['longitude'].diff().fillna(0)
        gps_step_size = np.sqrt(lat_diff**2 + lon_diff**2)
        group['gps_drift'] = gps_step_size.rolling(window=self.window_size, min_periods=1).std().fillna(0)

        alt_mean = group['altitude'].rolling(window=self.window_size, min_periods=1).mean()
        group['altitude_deviation'] = abs(group['altitude'] - alt_mean).fillna(0)

        batt_diff = group['battery'].diff().fillna(0)
        group['battery_discharge_rate'] = (-batt_diff).rolling(window=self.window_size, min_periods=1).mean().fillna(0)

        heading_mean = group['heading'].rolling(window=self.window_size, min_periods=1).mean()
        group['heading_deviation'] = abs(group['heading'] - heading_mean).fillna(0)

        mode_codes = group['flight_mode'].astype('category').cat.codes
        mode_changed = mode_codes.diff().fillna(0) != 0
        group['flight_mode_transitions'] = mode_changed.rolling(window=self.window_size, min_periods=1).sum().fillna(0)

        group['satellite_variation'] = group['satellites'].rolling(window=self.window_size, min_periods=1).std().fillna(0)
        group['velocity_consistency'] = group['speed'].rolling(window=self.window_size, min_periods=1).std().fillna(0)

        return group

    def _v2_features(self, group: pd.DataFrame) -> pd.DataFrame:
        """Kinematic deltas and GPS consistency. Mirrors the training pipeline.

        The core idea of the GPS features: derive ground speed from successive
        position fixes and compare it against the speed the airframe reports.
        A spoofed position jumps, so the derived speed diverges sharply from
        the reported one while the reported one stays plausible -- which is
        what `gps_speed_error_*` measures.
        """
        # Seconds between fixes. Zero deltas would make every rate feature
        # infinite, so they are nulled the same way the training pipeline does.
        if 'created_at' in group.columns:
            ts = pd.to_datetime(group['created_at'])
            dt = ts.diff().dt.total_seconds()
        else:
            dt = pd.Series(np.nan, index=group.index)
        dt = dt.replace(0, np.nan)
        group['time_delta'] = dt

        group['yaw'] = group['heading']
        group['speed_change'] = group['speed'].diff()
        group['altitude_change'] = group['altitude'].diff()
        group['yaw_change'] = angle_difference(group['heading'])
        group['vertical_speed'] = group['altitude_change'] / dt

        prev_lat = group['latitude'].shift(1)
        prev_lon = group['longitude'].shift(1)
        group['gps_jump_distance'] = haversine_vectorized(
            prev_lat, prev_lon, group['latitude'], group['longitude']
        )

        gps_speed = group['gps_jump_distance'] / dt
        gps_speed = gps_speed.where(dt > 0, np.nan)
        group['gps_speed'] = gps_speed

        group['gps_acceleration'] = gps_speed.diff() / dt

        gps_speed_error = gps_speed - group['speed']
        group['gps_speed_error_abs'] = gps_speed_error.abs()
        group['gps_speed_error_ratio'] = group['gps_speed_error_abs'] / (
            group['speed'].abs() + 1e-6
        )

        return group

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Engineers features for the given dataframe.
        Expects a dataframe sorted by time/sequence.
        This exact logic is used in both training and real-time inference.
        """
        df = df.copy()

        def extract_group_features(group):
            group = self._v1_features(group)
            group = self._v2_features(group)
            return group

        df = df.groupby('drone_id', group_keys=False).apply(extract_group_features)

        # Ensure only requested features are returned, avoiding missing columns
        for col in self.feature_columns:
            if col not in df.columns:
                df[col] = 0.0

        return df

    def get_feature_columns(self) -> list[str]:
        return self.feature_columns
