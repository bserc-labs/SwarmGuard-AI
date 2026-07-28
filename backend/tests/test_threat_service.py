 import os
import unittest
from datetime import datetime

# Resolve sys.path to allow running this test file standalone
import sys
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(TEST_DIR, "..", ".."))
sys.path.append(PROJECT_ROOT)

from backend.services.threat_service import ThreatScoreEngine, PiecewiseLinearStrategy, SigmoidStrategy
from backend.utils.severity_mapper import map_severity
from backend.utils.recommendation_engine import RecommendationEngine
from backend.utils.incident_generator import IncidentGenerator

DATA_DIR = os.path.normpath(os.path.join(TEST_DIR, "..", "data"))


class TestThreatScoreEngine(unittest.TestCase):
    def setUp(self):
        self.engine = ThreatScoreEngine(PiecewiseLinearStrategy())

    def test_exact_anchors(self):
        """Verify the Piecewise strategy maps exact anchor points correctly."""
        self.assertEqual(self.engine.get_threat_score(0.10), 20)
        self.assertEqual(self.engine.get_threat_score(0.30), 55)
        self.assertEqual(self.engine.get_threat_score(0.45), 78)
        self.assertEqual(self.engine.get_threat_score(0.60), 95)

    def test_boundaries(self):
        """Verify boundaries map to 0 and 100 exactly."""
        self.assertEqual(self.engine.get_threat_score(0.00), 0)
        self.assertEqual(self.engine.get_threat_score(1.00), 100)

    def test_interpolation(self):
        """Verify value interpolation between anchors."""
        # Midpoint of 0.00 and 0.10: should map to 10
        self.assertEqual(self.engine.get_threat_score(0.05), 10)
        # Verify unrounded float returns
        raw_val = self.engine.get_threat_score(0.05, round_output=False)
        self.assertAlmostEqual(raw_val, 10.0)

    def test_invalid_inputs(self):
        """Verify validation errors are thrown for out-of-bounds or invalid types."""
        with self.assertRaises(ValueError):
            self.engine.get_threat_score(-0.01)
        with self.assertRaises(ValueError):
            self.engine.get_threat_score(1.01)
        with self.assertRaises(TypeError):
            self.engine.get_threat_score("0.30")

    def test_sigmoid_strategy(self):
        """Verify SigmoidStrategy functions correctly and clamps boundaries."""
        sigmoid_engine = ThreatScoreEngine(SigmoidStrategy())
        self.assertEqual(sigmoid_engine.get_threat_score(0.00), 0)
        self.assertEqual(sigmoid_engine.get_threat_score(1.00), 100)
        # Sigmoid 0.30 should produce a mid-range score (near 54)
        score = sigmoid_engine.get_threat_score(0.30)
        self.assertTrue(30 <= score <= 70)


class TestSeverityMapper(unittest.TestCase):
    def test_map_severity_boundaries(self):
        """Verify severity classifications match the standard tiers."""
        # LOW (0-25)
        self.assertEqual(map_severity(0), "LOW")
        self.assertEqual(map_severity(25), "LOW")

        # MEDIUM (26-50)
        self.assertEqual(map_severity(26), "MEDIUM")
        self.assertEqual(map_severity(50), "MEDIUM")

        # HIGH (51-75)
        self.assertEqual(map_severity(51), "HIGH")
        self.assertEqual(map_severity(75), "HIGH")

        # CRITICAL (76-100)
        self.assertEqual(map_severity(76), "CRITICAL")
        self.assertEqual(map_severity(100), "CRITICAL")

    def test_invalid_scores(self):
        """Verify severity mapper checks input boundaries."""
        with self.assertRaises(ValueError):
            map_severity(-1)
        with self.assertRaises(ValueError):
            map_severity(101)
        with self.assertRaises(TypeError):
            map_severity("high")


class TestRecommendationEngine(unittest.TestCase):
    def setUp(self):
        self.engine = RecommendationEngine(data_dir=DATA_DIR)

    def test_critical_mitigation(self):
        """Verify CRITICAL severity recommendations include failsafes."""
        recs = self.engine.generate_recommendations("gps_spoofing", 80, "CRITICAL")
        self.assertTrue(any("Return-To-Home" in r or "failsafe" in r.lower() for r in recs))
        self.assertTrue(any("operator" in r.lower() or "alert" in r.lower() for r in recs))

    def test_low_mitigation(self):
        """Verify LOW severity recommendations are less intrusive."""
        recs = self.engine.generate_recommendations("signal_loss", 15, "LOW")
        self.assertTrue(any("log" in r.lower() for r in recs))
        self.assertFalse(any("Return-To-Home" in r and "EMERGENCY" in r for r in recs))


class TestIncidentGenerator(unittest.TestCase):
    def setUp(self):
        self.generator = IncidentGenerator(data_dir=DATA_DIR)

    def test_generate_incident(self):
        """Verify complete incident payload contains all necessary properties."""
        incident = self.generator.generate_incident(
            drone_id="drone_alpha",
            attack_type="gps_spoofing",
            anomaly_score=0.45
        )
        
        self.assertIn("incident_id", incident)
        self.assertTrue(incident["incident_id"].startswith("INC-"))
        self.assertEqual(incident["drone_id"], "drone_alpha")
        self.assertEqual(incident["attack_type"], "gps_spoofing")
        self.assertEqual(incident["threat_score"], 78) # 0.45 -> 78
        self.assertEqual(incident["severity"], "CRITICAL") # 78 is CRITICAL (>75)
        self.assertEqual(incident["status"], "Active")
        self.assertIn("explanation", incident)
        self.assertIn("recommendation", incident)
        self.assertIsInstance(incident["recommendation"], list)
        self.assertTrue(len(incident["recommendation"]) > 0)

    def test_prepare_timeline(self):
        """Verify the timeline aggregation sorts and groups incidents."""
        incidents = [
            {
                "incident_id": "INC-1",
                "drone_id": "D1",
                "attack_type": "dos",
                "threat_score": 90,
                "severity": "CRITICAL",
                "timestamp": "2026-07-25T12:00:00Z",
                "status": "Active"
            },
            {
                "incident_id": "INC-2",
                "drone_id": "D1",
                "attack_type": "signal_loss",
                "threat_score": 10,
                "severity": "LOW",
                "timestamp": "2026-07-25T11:00:00Z",
                "status": "Resolved"
            },
            {
                "incident_id": "INC-3",
                "drone_id": "D2",
                "attack_type": "gps_jamming",
                "threat_score": 40,
                "severity": "MEDIUM",
                "timestamp": "2026-07-25T13:00:00Z",
                "status": "False Positive"
            }
        ]

        result = IncidentGenerator.prepare_timeline(incidents)
        summary = result["summary"]
        timeline = result["timeline"]

        self.assertEqual(summary["total_incidents"], 3)
        self.assertEqual(summary["active_count"], 1)
        self.assertEqual(summary["resolved_count"], 1)
        self.assertEqual(summary["false_positive_count"], 1)

        # Timeline grouped list checks
        self.assertEqual(len(timeline["active"]), 1)
        self.assertEqual(timeline["active"][0]["incident_id"], "INC-1")

        self.assertEqual(len(timeline["resolved"]), 1)
        self.assertEqual(timeline["resolved"][0]["incident_id"], "INC-2")

        self.assertEqual(len(timeline["false_positive"]), 1)
        self.assertEqual(timeline["false_positive"][0]["incident_id"], "INC-3")

        # Severity count checks
        self.assertEqual(summary["severity_distribution"]["CRITICAL"], 1)
        self.assertEqual(summary["severity_distribution"]["LOW"], 1)
        self.assertEqual(summary["severity_distribution"]["MEDIUM"], 1)


if __name__ == "__main__":
    unittest.main()
