import importlib.util
import sys
import types
import unittest
from pathlib import Path


sys.modules.setdefault("requests", types.SimpleNamespace(get=lambda *args, **kwargs: None))

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

parksignals_spec = importlib.util.spec_from_file_location("parksignals", ROOT / "parksignals.py")
parksignals = importlib.util.module_from_spec(parksignals_spec)
sys.modules["parksignals"] = parksignals
parksignals_spec.loader.exec_module(parksignals)

run_monitor_spec = importlib.util.spec_from_file_location(
    "run_monitor",
    ROOT / "scripts" / "run_monitor.py",
)
run_monitor = importlib.util.module_from_spec(run_monitor_spec)
run_monitor_spec.loader.exec_module(run_monitor)


class ParkCloseStateTest(unittest.TestCase):
    def test_down_ride_is_closed_out_at_park_close(self):
        state = {
            "animal_kingdom": {
                "110": {
                    "id": "110",
                    "name": "Expedition Everest - Legend of the Forbidden Mountain",
                    "is_open": False,
                    "down_since": "2026-06-12T21:00:00Z",
                    "last_seen_at": "2026-06-12T22:00:00Z",
                    "current_down_seconds": 3600,
                    "total_down_seconds": 0,
                    "downtime_events": [],
                }
            }
        }
        park_status = {
            "observed_at_local": "2026-06-12T23:30:00-04:00",
            "hours": {
                "timezone": "America/New_York",
                "opens_at": "08:00",
                "closes_at": "18:00",
                "source": "themeparks_wiki",
            },
        }

        run_monitor.close_active_downtime_at_park_close("animal_kingdom", state, park_status)
        ride_state = state["animal_kingdom"]["110"]

        self.assertIsNone(ride_state["is_open"])
        self.assertIsNone(ride_state["down_since"])
        self.assertEqual(ride_state["current_down_seconds"], 0)
        self.assertEqual(ride_state["downtime_events"][0]["reopened_at"], "2026-06-12T22:00:00Z")
        self.assertEqual(ride_state["downtime_events"][0]["duration_seconds"], 3600)
        self.assertEqual(ride_state["downtime_events"][0]["ended_by"], "park_close")


if __name__ == "__main__":
    unittest.main()
