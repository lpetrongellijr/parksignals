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

run_monitor_spec = importlib.util.spec_from_file_location(
    "run_monitor",
    ROOT / "scripts" / "run_monitor.py",
)
run_monitor = importlib.util.module_from_spec(run_monitor_spec)
run_monitor_spec.loader.exec_module(run_monitor)


class RunMonitorTest(unittest.TestCase):
    def test_monitoring_hours_suppress_after_close(self):
        observed = datetime(2026, 6, 10, 3, 0, tzinfo=timezone.utc)
        park_config = {
            "monitoring_hours": {
                "enabled": True,
                "timezone": "America/New_York",
                "opens_at": "08:00",
                "closes_at": "22:00",
            }
        }

        allowed, reason = run_monitor.monitoring_hours_status(park_config, observed)

        self.assertFalse(allowed)
        self.assertIn("outside configured monitoring hours", reason)

    def test_suppressed_summary_does_not_touch_state(self):
        observed = datetime(2026, 6, 10, 3, 0, tzinfo=timezone.utc)
        park_config = {
            "park_name": "Magic Kingdom",
            "park_id": 6,
            "major_rides": ["Space Mountain"],
        }
        original_fetch_rides = parksignals.fetch_rides
        parksignals.fetch_rides = lambda _park_config: [
            {"id": "1", "name": "Space Mountain", "is_open": False, "wait_time": 0}
        ]

        try:
            summary = run_monitor.build_suppressed_summary(
                "magic_kingdom",
                park_config,
                observed,
                "outside configured monitoring hours",
            )
        finally:
            parksignals.fetch_rides = original_fetch_rides

        self.assertTrue(summary["monitoring_suppressed"])
        self.assertEqual(summary["transitions"], [])
        self.assertEqual(summary["ride_ids"][0]["name"], "Space Mountain")


if __name__ == "__main__":
    unittest.main()
