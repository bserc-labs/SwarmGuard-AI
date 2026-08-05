import math
from typing import List, Dict, Any, Tuple, Optional

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two lat/lng points using Haversine formula."""
    R = 6371000  # Earth radius in meters
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * Math_atan2_sqrt(a)
    return R * c

def Math_atan2_sqrt(a: float) -> float:
    a = min(1.0, max(0.0, a))
    return math.atan2(math.sqrt(a), math.sqrt(1 - a))

def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate compass bearing in degrees between two coordinates."""
    dlon = math.radians(lon2 - lon1)
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    
    x = math.sin(dlon) * math.cos(lat2_rad)
    y = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)
    initial_bearing = math.atan2(x, y)
    initial_bearing = math.degrees(initial_bearing)
    compass_bearing = (initial_bearing + 360) % 360
    return compass_bearing


class SwarmFormationDetector:
    """
    Analyzes spatial geometry across active drone telemetry to classify
    swarm formations (V-Shape, Grid Encircle, Leader-Follower, or Dispersed).
    """

    def analyze_swarm(self, drone_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        valid_drones = [
            d for d in drone_list
            if isinstance(d.get("latitude"), (int, float)) and isinstance(d.get("longitude"), (int, float))
        ]

        if len(valid_drones) < 2:
            return {
                "formation_type": "DISPERSED",
                "confidence": 0.0,
                "active_swarm_count": len(valid_drones),
                "cluster_drone_ids": [d.get("drone_id") for d in valid_drones],
                "centroid": None,
                "formation_lines": [],
                "description": "Insufficient drone count for swarm cluster analysis."
            }

        # Calculate Centroid
        avg_lat = sum(d["latitude"] for d in valid_drones) / len(valid_drones)
        avg_lng = sum(d["longitude"] for d in valid_drones) / len(valid_drones)
        centroid = {"lat": round(avg_lat, 6), "lng": round(avg_lng, 6)}

        # Pairwise distance matrix
        n = len(valid_drones)
        distances = []
        lines = []

        for i in range(n):
            for j in range(i + 1, n):
                d1 = valid_drones[i]
                d2 = valid_drones[j]
                dist = haversine_distance(d1["latitude"], d1["longitude"], d2["latitude"], d2["longitude"])
                distances.append(dist)
                
                # Draw connecting lines for drones within 1500m proximity cluster
                if dist <= 1500:
                    lines.append([
                        [d1["latitude"], d1["longitude"]],
                        [d2["latitude"], d2["longitude"]]
                    ])

        avg_dist = sum(distances) / len(distances) if distances else 0.0
        max_dist_to_centroid = max(
            haversine_distance(avg_lat, avg_lng, d["latitude"], d["longitude"])
            for d in valid_drones
        )

        # Classification logic based on spatial spread & count
        formation_type = "DISPERSED"
        confidence = 0.5
        description = "Standard operational flight spacing."

        # Case 1: Grid Encircle (Drones tightly clustered around centroid < 1000m)
        if max_dist_to_centroid <= 1000 and len(valid_drones) >= 3:
            formation_type = "GRID_ENCIRCLE"
            confidence = round(min(0.98, 0.70 + (0.05 * len(valid_drones))), 2)
            description = f"Synchronized circular perimeter pattern detected around target sector ({len(valid_drones)} units)."

        # Case 2: V-Shape Military Wedge Formation
        elif len(valid_drones) >= 3 and avg_dist <= 2500:
            # Check bearing symmetry relative to lead drone
            sorted_drones = sorted(valid_drones, key=lambda d: d["latitude"], reverse=True)
            leader = sorted_drones[0]
            bearings = [
                calculate_bearing(leader["latitude"], leader["longitude"], follower["latitude"], follower["longitude"])
                for follower in sorted_drones[1:]
            ]
            has_left_wing = any(180 <= b <= 270 for b in bearings)
            has_right_wing = any(90 <= b <= 180 for b in bearings)

            if has_left_wing and has_right_wing:
                formation_type = "V_SHAPE"
                confidence = 0.92
                description = "Tactical V-Shape wedge formation detected heading north/south vector."
            else:
                formation_type = "LEADER_FOLLOWER"
                confidence = 0.85
                description = "Single-file tactical leader-follower column formation."

        elif len(valid_drones) >= 2 and avg_dist <= 2000:
            formation_type = "LEADER_FOLLOWER"
            confidence = 0.80
            description = "Paired tactical leader-follower flight path."

        return {
            "formation_type": formation_type,
            "confidence": confidence,
            "active_swarm_count": len(valid_drones),
            "cluster_drone_ids": [d.get("drone_id") for d in valid_drones],
            "centroid": centroid,
            "formation_lines": lines,
            "description": description
        }


swarm_service = SwarmFormationDetector()
