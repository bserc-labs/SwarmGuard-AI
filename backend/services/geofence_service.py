"""Tier 1b: restricted-airspace breach detection.

Runs inside the same detection pipeline as the kinematic guard and emits the
same detection shape, so a breach becomes an incident through the existing
IncidentEngine -- with the same suppression, prioritisation and audit path --
rather than through a second, parallel mechanism.

Two properties matter:

* **Server-side only.** The console draws zones and evaluates them in the
  browser for immediate feedback, but a breach claim from a client is not
  evidence. The incident is raised from the position the aircraft reported to
  the ingest endpoint, evaluated here.

* **Ordered after the kinematic guard, deliberately.** A geofence check is only
  as trustworthy as the position it is given. When the guard has just found the
  reported position to be physically impossible, that position is the thing
  under attack -- raising a breach from it would report a location the aircraft
  is probably not at. See `detection_pipeline._run_detectors`.
"""

import math
from typing import Any

from sqlalchemy.orm import Session

import models
from utils.logger import logger

# Zones carry the operator's own severity vocabulary; incidents carry the
# system's. A restricted-airspace breach is serious by construction, so the
# quieter zone level still maps above the middle of the incident scale.
ZONE_SEVERITY_TO_INCIDENT = {
    "CRITICAL": "CRITICAL",
    "WARNING": "HIGH",
}

# Threat scores per band, on the 0-100 scale the rest of the system uses. These
# feed priority calculation; the severity itself is declared, not derived.
ZONE_SEVERITY_TO_SCORE = {
    "CRITICAL": 95.0,
    "WARNING": 70.0,
}


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
    def is_point_in_polygon(lat: float, lon: float, polygon: list[list[float]]) -> bool:
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
    def check_geofence_violations(
        db: Session,
        lat: float,
        lon: float,
        *,
        organization_id: int,
    ) -> list[models.GeofenceZone]:
        """
        Check if a given lat/lon violates any of this organization's active zones.

        `organization_id` is required and keyword-only. This query previously
        selected every active zone in the database regardless of owner, so a
        drone would have been evaluated against other tenants' restricted
        airspace and the resulting incident would have named a zone its own
        organization cannot see. Nothing called it, so the leak never shipped --
        but it had to be closed before anything did.
        """
        if organization_id is None:
            raise ValueError("organization_id is required to evaluate geofence zones")

        violated_zones = []
        active_zones = (
            db.query(models.GeofenceZone)
            .filter(
                models.GeofenceZone.organization_id == organization_id,
                models.GeofenceZone.is_active == True,  # noqa: E712 - SQL boolean
            )
            .all()
        )

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

    @staticmethod
    def _describe(zone: models.GeofenceZone, lat: float, lon: float) -> str:
        """Prose an analyst can act on: which zone, and where the aircraft is."""
        if zone.zone_type == "CIRCLE":
            try:
                center = zone.coordinates.get("center", [0, 0])
                radius = float(zone.coordinates.get("radius", 0))
                distance = GeofenceEngine.haversine_distance(
                    lat, lon, center[0], center[1]
                )
                return (
                    f"Position {lat:.5f}, {lon:.5f} is {distance:,.0f} m from the centre "
                    f"of restricted zone '{zone.name}', inside its {radius:,.0f} m radius."
                )
            except (AttributeError, TypeError, ValueError, IndexError):
                pass
        return (
            f"Position {lat:.5f}, {lon:.5f} lies inside restricted zone "
            f"'{zone.name}'."
        )

    @classmethod
    def evaluate(
        cls,
        db: Session,
        drone_id: str,
        lat: float,
        lon: float,
        *,
        organization_id: int,
    ) -> dict[str, Any] | None:
        """Detection dict for a breach, or None. Mirrors GuardVerdict.to_detection.

        Emitting the same shape as the kinematic guard is what lets a breach go
        through IncidentEngine untouched -- inheriting suppression, priority,
        recommendations and the audit trail rather than reimplementing them.
        """
        if lat is None or lon is None:
            return None

        zones = cls.check_geofence_violations(
            db, lat, lon, organization_id=organization_id
        )
        if not zones:
            return None

        # Worst zone leads. A drone can sit inside a warning zone and a critical
        # one at once, and the incident should be filed as the critical breach.
        zones.sort(
            key=lambda z: ZONE_SEVERITY_TO_SCORE.get((z.severity or "").upper(), 50.0),
            reverse=True,
        )
        primary = zones[0]
        band = (primary.severity or "CRITICAL").upper()
        severity = ZONE_SEVERITY_TO_INCIDENT.get(band, "HIGH")
        threat_score = ZONE_SEVERITY_TO_SCORE.get(band, 70.0)

        ranked = [
            {
                "feature": "geofence_breach",
                # A breach is binary -- the aircraft is inside the zone or it is
                # not -- so there is no exceedance to report. The magnitude is
                # the declared seriousness of the zone, which is what ranks
                # multiple simultaneous breaches against each other.
                "shap_value": ZONE_SEVERITY_TO_SCORE.get(
                    (zone.severity or "").upper(), 50.0
                ),
                "magnitude": ZONE_SEVERITY_TO_SCORE.get(
                    (zone.severity or "").upper(), 50.0
                ),
                "zone": zone.name,
                "zone_type": zone.zone_type,
                "zone_severity": zone.severity,
            }
            for zone in zones
        ]

        return {
            "drone_id": drone_id,
            "prediction": {
                "is_anomaly": True,
                "anomaly_score": threat_score,
                "threat_score": threat_score,
                "threat_level": severity,
                # Declared by the operator on the zone, not derived from a
                # score. IncidentEngine takes the more serious of this and the
                # organization's configured bands.
                "severity": severity,
            },
            "explanation": {
                "ranked_features": ranked,
                "summary": {
                    "Attack Type": "GEOFENCE_BREACH",
                    "Primary Cause": cls._describe(primary, lat, lon),
                    "Secondary Cause": (
                        cls._describe(zones[1], lat, lon) if len(zones) > 1 else "None"
                    ),
                    "Supporting Indicators": (
                        ", ".join(z.name for z in zones[2:5]) or "None"
                    ),
                    "Detector": "geofence",
                },
                "metadata": {
                    "detector": "geofence",
                    "model_version": "geofence-v1",
                    "feature_engineering_version": "geofence-v1",
                    "deterministic": True,
                    "explanation_confidence_percent": 100.0,
                    "zones": [
                        {
                            "id": z.id,
                            "name": z.name,
                            "zone_type": z.zone_type,
                            "severity": z.severity,
                        }
                        for z in zones
                    ],
                    "position": {"latitude": lat, "longitude": lon},
                },
            },
        }


geofence_engine = GeofenceEngine()
