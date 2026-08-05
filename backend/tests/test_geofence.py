import sys
import os

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from services.geofence_service import GeofenceEngine

def test_haversine_distance_calculation():
    # Known distance between LA City Hall and LA Airport (~19.3 km = 19300m)
    p1 = (34.0537, -118.2427)
    p2 = (33.9416, -118.4085)
    dist = GeofenceEngine.haversine_distance(p1[0], p1[1], p2[0], p2[1])
    assert 18000 < dist < 21000

def test_point_in_circle_geofence():
    center = [34.0522, -118.2437]
    radius = 1000.0 # 1 km
    
    inside_point = [34.0530, -118.2430] # ~100m away
    outside_point = [34.1000, -118.3000] # ~7km away

    dist_inside = GeofenceEngine.haversine_distance(inside_point[0], inside_point[1], center[0], center[1])
    dist_outside = GeofenceEngine.haversine_distance(outside_point[0], outside_point[1], center[0], center[1])

    assert (dist_inside <= radius) == True
    assert (dist_outside <= radius) == False

def test_point_in_polygon_geofence():
    polygon = [
        [34.00, -118.30],
        [34.10, -118.30],
        [34.10, -118.20],
        [34.00, -118.20]
    ]
    inside_point = [34.05, -118.25]
    outside_point = [34.15, -118.25]

    assert GeofenceEngine.is_point_in_polygon(inside_point[0], inside_point[1], polygon) == True
    assert GeofenceEngine.is_point_in_polygon(outside_point[0], outside_point[1], polygon) == False

