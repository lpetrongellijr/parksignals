import importlib.util
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path


sys.modules.setdefault("requests", types.SimpleNamespace(get=lambda *args, **kwargs: None))

ROOT = Path(__file__).resolve().parents[1]
parksignals_spec = importlib.util.spec_from_file_location("parksignals", ROOT / "parksignals.py")
parksignals = importlib.util.module_from_spec(parksignals_spec)
sys.modules["parksignals"] = parksignals
parksignals_spec.loader.exec_module(parksignals)


class FirstSampleTransitionTest(unittest.TestCase):
    def test_first_unavailable_sample_creates_down_transition(self):
        observed_at = datetime(2026, 6, 16, 13, 15, tzinfo=timezone.utc)
        ride_state = parksignals.normalize_ride_state(None, observed_at)
        ride = {
            "id": "rise",
            "name": "Star Wars: Rise of the Resistance",
            "is_open": False,
            "wait_time": None,
        }

        transition = parksignals.update_ride_state(ride_state, ride, observed_at)

        self.assertEqual(transition, "down")
        self.assertEqual(ride_state["down_since"], "2026-06-16T13:15:00Z")
        self.assertEqual(ride_state["last_down_at"], "2026-06-16T13:15:00Z")
        self.assertEqual(ride_state["current_down_seconds"], 0)

    def test_first_open_sample_still_initializes_quietly(self):
        observed_at = datetime(2026, 6, 16, 13, 15, tzinfo=timezone.utc)
        ride_state = parksignals.normalize_ride_state(None, observed_at)
        ride = {
            "id": "runaway_railway",
            "name": "Mickey & Minnie's Runaway Railway",
            "is_open": True,
            "wait_time": 35,
        }

        transition = parksignals.update_ride_state(ride_state, ride, observed_at)

        self.assertIsNone(transition)
        self.assertIsNone(ride_state["down_since"])
        self.assertEqual(ride_state["current_down_seconds"], 0)

    def test_planned_closure_first_sample_does_not_create_down_transition(self):
        observed_at = datetime(2026, 6, 16, 13, 15, tzinfo=timezone.utc)
        ride_state = parksignals.normalize_ride_state(None, observed_at)
        ride = {
            "id": "planned",
            "name": "Planned Refurb Ride",
            "is_open": False,
            "wait_time": None,
        }

        transition = parksignals.update_ride_state(
            ride_state,
            ride,
            observed_at,
            planned_closure={"reason": "refurbishment", "source": "manual"},
        )

        self.assertIsNone(transition)
        self.assertTrue(ride_state["planned_closure_active"])
        self.assertIsNone(ride_state["down_since"])


if __name__ == "__main__":
    unittest.main()
