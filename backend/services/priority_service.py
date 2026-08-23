from config import get_settings

settings = get_settings()

class PriorityService:
    def __init__(self):
        # Base multipliers for mission criticality
        self.mission_multipliers = {
            "LOW": 0.5,
            "NORMAL": 1.0,
            "HIGH": 1.5,
            "CRITICAL": 2.0
        }

    def calculate_priority(
        self, 
        threat_score: float, 
        anomaly_score: float, 
        repeat_incidents_count: int, 
        mission_criticality: str | None = None
    ) -> int:
        """
        Calculates a numeric priority (0-100+) based on threat data and mission criticality.
        Higher is more critical.
        """
        # Default to configured fallback if not provided
        criticality = mission_criticality or settings.DEFAULT_MISSION_CRITICALITY
        multiplier = self.mission_multipliers.get(criticality.upper(), 1.0)
        
        # Base score derived from threat and anomaly scores (assumed 0-100 scale)
        base_score = (threat_score * 0.7) + (anomaly_score * 0.3)
        
        # Add penalty for repeat offenses
        repeat_penalty = repeat_incidents_count * 5.0
        
        # Apply multiplier
        priority_raw = (base_score + repeat_penalty) * multiplier
        
        # Cap at 100 or allow unbounded? Standardizing to 0-100 scale for ease, but keeping it an integer
        return int(min(max(priority_raw, 0), 100))

priority_service = PriorityService()
