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


class AnalyticsHoursTest(unittest.TestCase):
    def test_active_downtime_stops_at_last_observed_time(self):
        observed = datetime(2026, 6, 13, 3, 30, tzinfo=timezone.utc)
        config = {
            "default_parks": ["animal_kingdom"],
            "parks": {
                "animal_kingdom": {
                    "enabled": True,
                    "park_name": "Animal Kingdom",
                    "major_rides": ["Expedition Everest - Legend of the Forbidden Mountain"],
                }
            },
        }
        state = {
            "animal_kingdom": {
                "110": {
                    "id": "110",
                    "name": "Expedition Everest - Legend of the Forbidden Mountain",
                    "is_open": False,
                    "down_since": "2026-06-12T21:00:00Z",
                    "last_seen_at": "2026-06-12T22:00:00Z",
                    "last_changed_at": "2026-06-12T21:00:00Z",
                    "current_down_seconds": 3600,
                    "downtime_events": [],
                }
            }
        }

        summary = parksignals_analytics.collect_content_pillar_summary(state, config, observed)

        self.assertEqual(summary["daily_top"][0]["downtime_seconds"], 3600)
        self.assertEqual(summary["daily_top"][0]["current_down_seconds"], 3600)


if __name__ == "__main__":
    unittest.main()
