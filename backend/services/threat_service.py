import math
from abc import ABC, abstractmethod
from typing import List, Tuple, Union

class MappingStrategy(ABC):
    """
    Abstract base class for converting a raw float anomaly score [0.0, 1.0]
    into a raw threat score [0.0, 100.0].
    """
    @abstractmethod
    def map_score(self, anomaly_score: float) -> float:
        pass


class PiecewiseLinearStrategy(MappingStrategy):
    """
    Maps anomaly scores to threat scores using piecewise linear interpolation.
    Guarantees exact matches to specific anchor points.
    """
    DEFAULT_POINTS = [
        (0.00, 0.0),
        (0.10, 20.0),
        (0.30, 55.0),
        (0.45, 78.0),
        (0.60, 95.0),
        (1.00, 100.0)
    ]

    def __init__(self, points: List[Tuple[float, float]] = None):
        self.points = sorted(points if points is not None else self.DEFAULT_POINTS, key=lambda p: p[0])
        self._validate_points()

    def _validate_points(self):
        if len(self.points) < 2:
            raise ValueError("Piecewise interpolation requires at least 2 anchor points.")
        
        if not math.isclose(self.points[0][0], 0.0, abs_tol=1e-9):
            raise ValueError("Anchor points must start at anomaly score 0.0")
        if not math.isclose(self.points[-1][0], 1.0, abs_tol=1e-9):
            raise ValueError("Anchor points must end at anomaly score 1.0")

        for i in range(len(self.points) - 1):
            if self.points[i][0] == self.points[i+1][0]:
                raise ValueError("Duplicate anomaly scores in anchor points are not allowed.")
            if self.points[i][1] > self.points[i+1][1]:
                raise ValueError("Threat scores in anchor points must be monotonically non-decreasing.")

    def map_score(self, anomaly_score: float) -> float:
        if anomaly_score <= self.points[0][0]:
            return self.points[0][1]
        if anomaly_score >= self.points[-1][0]:
            return self.points[-1][1]

        for i in range(len(self.points) - 1):
            x1, y1 = self.points[i]
            x2, y2 = self.points[i+1]
            if x1 <= anomaly_score <= x2:
                return y1 + (y2 - y1) * (anomaly_score - x1) / (x2 - x1)
        
        return self.points[-1][1]


class SigmoidStrategy(MappingStrategy):
    """
    Maps anomaly scores using a parameterized Sigmoid (logistic) curve.
    Fitted parameter values: k = 7.90, x0 = 0.28.
    """
    def __init__(self, k: float = 7.90, x0: float = 0.28):
        self.k = k
        self.x0 = x0
        
        self._raw_min = self._raw_sigmoid(0.0)
        self._raw_max = self._raw_sigmoid(1.0)
        self._scale_denominator = self._raw_max - self._raw_min

    def _raw_sigmoid(self, x: float) -> float:
        try:
            return 100.0 / (1.0 + math.exp(-self.k * (x - self.x0)))
        except OverflowError:
            return 100.0 if -self.k * (x - self.x0) < 0 else 0.0

    def map_score(self, anomaly_score: float) -> float:
        raw = self._raw_sigmoid(anomaly_score)
        scaled = 100.0 * (raw - self._raw_min) / self._scale_denominator
        return scaled


class ThreatScoreEngine:
    """
    Standardizes AI anomaly scores to Threat Scores (0 - 100).
    """
    def __init__(self, strategy: MappingStrategy = None):
        self._strategy = strategy if strategy is not None else PiecewiseLinearStrategy()
        if not isinstance(self._strategy, MappingStrategy):
            raise TypeError("strategy must be an instance of MappingStrategy")

    @property
    def strategy(self) -> MappingStrategy:
        return self._strategy

    @strategy.setter
    def strategy(self, strategy: MappingStrategy):
        if not isinstance(strategy, MappingStrategy):
            raise TypeError("strategy must be an instance of MappingStrategy")
        self._strategy = strategy

    def get_threat_score(self, anomaly_score: Union[int, float], round_output: bool = True) -> Union[int, float]:
        """
        Convert an AI anomaly score to a standardized Threat Score (0 - 100).
        """
        self._validate_input(anomaly_score)
        
        raw_score = self._strategy.map_score(float(anomaly_score))
        
        final_score = max(0.0, min(100.0, raw_score))
        
        if round_output:
            return round(final_score)
        
        return final_score

    def _validate_input(self, anomaly_score: Union[int, float]):
        if not isinstance(anomaly_score, (int, float)):
            raise TypeError(
                f"Anomaly score must be a number (float or int), got {type(anomaly_score).__name__}"
            )
        if not (0.0 <= anomaly_score <= 1.0):
            raise ValueError(
                f"Anomaly score must be in the range [0.0, 1.0], got {anomaly_score}"
            )
