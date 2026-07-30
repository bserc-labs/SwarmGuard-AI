import math
from typing import List, Dict, Tuple
from sqlalchemy.orm import Session
import models
from utils.logger import logger

class GeofenceEngine:
    @staticmethod
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate the great circle distance in meters between two points
        on the earth (specified in decimal degrees)
        """
        R = 6371000  # radius of Earth in meters
        
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        
        a = math.sin(delta_phi / 2.0) ** 2 + \
            math.cos(phi1) * math.cos(phi2) * \
            math.sin(delta_lambda / 2.0) ** 2
            
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        distance = R * c
        
        return distance

    @staticmethod
    def is_point_in_polygon(lat: float, lon: float, polygon: List[List[float]]) -> bool:
        """
        Ray-casting algorithm to determine if a point is inside a polygon.
        polygon is a list of [lat, lng] points.
        """
        inside = False
        n = len(polygon)
        if n < 3:
            return False
            
        p1lat, p1lon = polygon[0]
        for i in range(n + 1):
            p2lat, p2lon = polygon[i % n]
            if lon > min(p1lon, p2lon):
                if lon <= max(p1lon, p2lon):
                    if lat <= max(p1lat, p2lat):
                        if p1lon != p2lon:
                            xinters = (lon - p1lon) * (p2lat - p1lat) / (p2lon - p1lon) + p1lat
                        if p1lat == p2lat or lat <= xinters:
                            inside = not inside
            p1lat, p1lon = p2lat, p2lon
            
        return inside

    @staticmethod
    def check_geofence_violations(db: Session, lat: float, lon: float) -> List[models.GeofenceZone]:
        """
        Check if a given lat/lon violates any active restricted zones.
        Returns a list of violated zones.
        """
        violated_zones = []
        active_zones = db.query(models.GeofenceZone).filter(models.GeofenceZone.is_active == True).all()
        
        for zone in active_zones:
            try:
                if zone.zone_type == "POLYGON":
                    # coordinates is a list of [lat, lng]
                    if GeofenceEngine.is_point_in_polygon(lat, lon, zone.coordinates):
                        violated_zones.append(zone)
                        
                elif zone.zone_type == "CIRCLE":
                    # coordinates is {"center": [lat, lng], "radius": radius_in_meters}
                    center = zone.coordinates.get("center", [0, 0])
                    radius = zone.coordinates.get("radius", 0)
                    distance = GeofenceEngine.haversine_distance(lat, lon, center[0], center[1])
                    if distance <= radius:
                        violated_zones.append(zone)
            except Exception as e:
                logger.error(f"Error evaluating geofence zone {zone.name}: {e}")
                
        return violated_zones
