class RecommendationService:
    def __init__(self):
        # Keyed on the short attack labels the explanation layer emits
        # (see AIExplanationService._ATTACK_FAMILIES). The previous keys were
        # prose ("GPS Spoofing"), which never matched an incident's actual
        # attack_type, so every incident fell through to the generic text.
        self.rules = {
            "GPS_SPOOFING": "Verify GNSS integrity. Cross-check position against INS/visual odometry before trusting any waypoint command.",
            "SIGNAL_JAMMING": "Switch to failsafe. Assume the link is contested and prepare for autonomous return.",
            "POWER_ANOMALY": "Land safely. Rapid discharge may indicate physical payload interference.",
            "FLIGHT_INSTABILITY": "Return to Base. Check for adverse wind or autopilot malfunction.",
            "CONTROL_ANOMALY": "Review command history for unauthorised mode changes.",
        }

        # Legacy prose labels, retained so incidents written before the short
        # labels existed still resolve to a recommendation.
        self.legacy_rules = {
            "GPS Spoofing": "Verify GNSS integrity",
            "Battery Attack": "Land safely",
            "Navigation Anomaly": "Return to Base",
            "Communication Loss": "Switch to failsafe",
        }

    def generate_recommendation(self, attack_type: str, explanation_summary: dict | None = None) -> str:
        """
        Generates a human-readable recommendation for SOC analysts.
        Falls back to a generic investigation recommendation if no exact match is found.
        """
        if attack_type in self.rules:
            return self.rules[attack_type]
        if attack_type in self.legacy_rules:
            return self.legacy_rules[attack_type]

        # Fallback heuristic parsing from the explanation summary.
        #
        # The summary arrives with title-cased keys ("Primary Cause") because
        # that is what _generate_analyst_summary produces. This previously read
        # "primary_cause", so the lookup always returned "" and no heuristic
        # ever fired. Both spellings are accepted now.
        if explanation_summary:
            primary_cause = (
                explanation_summary.get("Primary Cause")
                or explanation_summary.get("primary_cause")
                or ""
            ).lower()
            if "gps" in primary_cause or "satellite" in primary_cause:
                return "Verify GNSS integrity"
            if "battery" in primary_cause:
                return "Land safely"
            if "heading" in primary_cause or "speed" in primary_cause or "altitude" in primary_cause:
                return "Return to Base"

        return "Investigate telemetry logs manually."


recommendation_service = RecommendationService()
