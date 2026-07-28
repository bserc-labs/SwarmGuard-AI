from typing import Union

def map_severity(threat_score: Union[int, float]) -> str:
    """
    Maps a Threat Score (0-100) into one of four severity levels:
    - LOW: 0 to 25
    - MEDIUM: 26 to 50
    - HIGH: 51 to 75
    - CRITICAL: 76 to 100

    Args:
        threat_score (Union[int, float]): Threat score in the range [0, 100].

    Returns:
        str: Severity tier ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL').

    Raises:
        ValueError: If threat_score is outside [0, 100].
        TypeError: If threat_score is not a float or integer.
    """
    if not isinstance(threat_score, (int, float)):
        raise TypeError(f"Threat score must be a number, got {type(threat_score).__name__}")

    if not (0 <= threat_score <= 100):
        raise ValueError(f"Threat score must be in the range [0, 100], got {threat_score}")

    # Map intervals
    if threat_score <= 25:
        return "LOW"
    elif threat_score <= 50:
        return "MEDIUM"
    elif threat_score <= 75:
        return "HIGH"
    else:
        return "CRITICAL"
