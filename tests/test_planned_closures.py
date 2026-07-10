import importlib.util
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path


sys.modules.setdefault("requests", types.SimpleNamespace(get=lambda *args, **kwargs: None))

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

parksignals_spec = importlib.util.spec_from_file_location("parksignals", ROOT / "parksignals.py")
parksignals = importlib.util.module_from_spec(parksignals_spec)
parksignals_spec.loader.exec_module(parksignals)
sys.modules["parksignals"] = parksignals

analytics_spec = importlib.util.spec_from_file_location(
    "parksignals_analytics",
    ROOT / "scripts" / "parksignals_analytics.py",
)
parksignals_analytics = importlib.util.module_from_spec(analytics_spec)
analytics_spec.loader.exec_module(parksignals_analytics)


class PlannedClosureTest(unittest.TestCase):
    def test_planned_closure_is_tracked_without_alert_transition(self):
        observed = datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc)
        park_config = {
            "enabled": True,
            "park_id": 8,
            "park_name": "Animal Kingdom",
            "resort_name": "Walt Disney World",
            "major_rides": ["Kali River Rapids"],
            "planned_closures": [
                {
                    "ride_name": "Kali River Rapids",
                    "starts_on": "2026-06-13",
                    "ends_on": "2026-06-30",
                    "reason": "refurbishment",
                }
            ],
        }
        state = {
            "animal_kingdom": {
                "123": {
                    "id": "123",
                    "name": "Kali River Rapids",
                    "is_open": True,
                    "last_seen_at": "2026-06-13T13:45:00Z",
                    "current_down_seconds": 0,
                    "downtime_events": [],
                }
            }
        }
        original_fetch_rides = parksignals.fetch_rides
        parksignals.fetch_rides = lambda config, park_key=None: [
            {
                "id": "123",
                "name": "Kali River Rapids",
                "is_open": False,
                "wait_time": 0,
            }
        ]
        try:
            summary = parksignals.monitor_park(
                "animal_kingdom",
                park_config,
                state,
                observed,
            )
        finally:
            parksignals.fetch_rides = original_fetch_rides

        ride_state = state["animal_kingdom"]["123"]
        self.assertEqual(summary["down_count"], 0)
        self.assertEqual(summary["planned_closure_count"], 1)
        self.assertEqual(summary["transitions"], [])
        self.assertIsNone(ride_state["is_open"])
        self.assertTrue(ride_state["planned_closure_active"])
        self.assertIsNone(ride_state["down_since"])

    def test_planned_closure_history_is_excluded_from_analytics(self):
        observed = datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc)
        config = {
            "default_parks": ["animal_kingdom"],
            "parks": {
                "animal_kingdom": {
                    "enabled": True,
                    "park_name": "Animal Kingdom",
                    "major_rides": ["Kali River Rapids"],
                }
            },
        }
        state = {
            "animal_kingdom": {
                "123": {
                    "id": "123",
                    "name": "Kali River Rapids",
                    "is_open": None,
                    "down_since": None,
                    "last_seen_at": "2026-06-13T14:00:00Z",
                    "planned_closure_active": True,
                    "planned_closure": {"reason": "refurbishment"},
                    "current_down_seconds": 0,
                    "downtime_events": [
                        {
                            "down_at": "2026-06-13T12:00:00Z",
                            "reopened_at": "2026-06-13T14:00:00Z",
                            "duration_seconds": 7200,
                            "ended_by": "planned_closure_start",
                        }
                    ],
                }
            }
        }

        summary = parksignals_analytics.collect_content_pillar_summary(
            state,
            config,
            observed,
        )

        self.assertEqual(summary["daily_top"], [])
        self.assertEqual(summary["active_multi_ride_alerts"], [])

    def test_scheduled_ride_closure_does_not_count_as_downtime(self):
        observed = datetime(2026, 7, 10, 21, 0, tzinfo=timezone.utc)
        park_config = {
            "enabled": True,
            "park_name": "Animal Kingdom",
            "major_rides": ["Wildlife Express Train"],
            "ride_operating_hours": [
                {
                    "ride_name": "Wildlife Express Train",
                    "opens_at": "09:30",
                    "closes_at": "16:30",
                    "timezone": "America/New_York",
                    "reason": "scheduled ride operating hours",
                }
            ],
        }
        state = {
            "animal_kingdom": {
                "wildlife": {
                    "id": "wildlife",
                    "name": "Wildlife Express Train",
                    "is_open": True,
                    "last_seen_at": "2026-07-10T20:15:00Z",
                    "current_down_seconds": 0,
                    "downtime_events": [],
                }
            }
        }
        original_fetch_rides = parksignals.fetch_rides
        parksignals.fetch_rides = lambda config, park_key=None: [
            {
                "id": "wildlife",
                "name": "Wildlife Express Train",
                "is_open": False,
                "wait_time": None,
            }
        ]
        try:
            summary = parksignals.monitor_park("animal_kingdom", park_config, state, observed)
        finally:
            parksignals.fetch_rides = original_fetch_rides

        ride_state = state["animal_kingdom"]["wildlife"]
        self.assertEqual(summary["down_count"], 0)
        self.assertEqual(summary["planned_closure_count"], 1)
        self.assertEqual(summary["transitions"], [])
        self.assertTrue(ride_state["planned_closure_active"])
        self.assertEqual(ride_state["planned_closure"]["source"], "configured_ride_operating_hours")
        self.assertIsNone(ride_state["down_since"])

    def test_scheduled_ride_closure_stops_active_downtime_at_ride_close(self):
        observed = datetime(2026, 7, 10, 21, 0, tzinfo=timezone.utc)
        park_config = {
            "enabled": True,
            "park_name": "Animal Kingdom",
            "major_rides": ["Wildlife Express Train"],
            "ride_operating_hours": [
                {
                    "ride_name": "Wildlife Express Train",
                    "opens_at": "09:30",
                    "closes_at": "16:30",
                    "timezone": "America/New_York",
                    "reason": "scheduled ride operating hours",
                }
            ],
        }
        state = {
            "animal_kingdom": {
                "wildlife": {
                    "id": "wildlife",
                    "name": "Wildlife Express Train",
                    "is_open": False,
                    "down_since": "2026-07-10T20:00:00Z",
                    "last_seen_at": "2026-07-10T20:15:00Z",
                    "current_down_seconds": 900,
                    "total_down_seconds": 0,
                    "downtime_events": [],
                }
            }
        }
        original_fetch_rides = parksignals.fetch_rides
        parksignals.fetch_rides = lambda config, park_key=None: [
            {
                "id": "wildlife",
                "name": "Wildlife Express Train",
                "is_open": False,
                "wait_time": None,
            }
        ]
        try:
            parksignals.monitor_park("animal_kingdom", park_config, state, observed)
        finally:
            parksignals.fetch_rides = original_fetch_rides

        ride_state = state["animal_kingdom"]["wildlife"]
        self.assertEqual(ride_state["downtime_events"][0]["reopened_at"], "2026-07-10T20:30:00Z")
        self.assertEqual(ride_state["downtime_events"][0]["duration_seconds"], 1800)
        self.assertTrue(ride_state["planned_closure_active"])


if __name__ == "__main__":
    unittest.main()
