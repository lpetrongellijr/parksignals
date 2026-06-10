import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


sys.modules.setdefault("requests", types.SimpleNamespace(get=lambda *args, **kwargs: None))

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("parksignals", ROOT / "parksignals.py")
parksignals = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parksignals)

export_spec = importlib.util.spec_from_file_location(
    "export_artifacts",
    ROOT / "scripts" / "export_artifacts.py",
)
export_artifacts = importlib.util.module_from_spec(export_spec)
sys.modules["parksignals"] = parksignals
export_spec.loader.exec_module(export_artifacts)


class ParkSignalsSupportTest(unittest.TestCase):
    def test_state_transition_tracks_duration(self):
        observed = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
        state = parksignals.normalize_ride_state(True, observed)
        ride = {"id": "1", "name": "Space Mountain", "is_open": False, "wait_time": 0}

        self.assertEqual(
            parksignals.update_ride_state(state, ride, observed + timedelta(minutes=15)),
            "down",
        )
        ride["is_open"] = True
        self.assertEqual(
            parksignals.update_ride_state(state, ride, observed + timedelta(minutes=45)),
            "reopened",
        )

        self.assertEqual(state["total_down_seconds"], 1800)
        self.assertEqual(state["downtime_events"][0]["duration_seconds"], 1800)

    def test_content_summary_supports_daily_monthly_and_trends(self):
        observed = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
        config = {
            "default_parks": ["magic_kingdom"],
            "parks": {
                "magic_kingdom": {
                    "enabled": True,
                    "park_name": "Magic Kingdom",
                    "major_rides": ["Space Mountain"],
                }
            },
        }
        state = {
            "magic_kingdom": {
                "1": {
                    "id": "1",
                    "name": "Space Mountain",
                    "is_open": True,
                    "current_down_seconds": 0,
                    "downtime_events": [
                        {
                            "down_at": "2026-06-09T08:00:00Z",
                            "reopened_at": "2026-06-09T09:00:00Z",
                            "duration_seconds": 3600,
                        },
                        {
                            "down_at": "2026-06-08T08:00:00Z",
                            "reopened_at": "2026-06-08T09:00:00Z",
                            "duration_seconds": 3600,
                        },
                    ],
                }
            }
        }

        summary = parksignals.collect_content_pillar_summary(state, config, observed)

        self.assertEqual(summary["daily_top"][0]["downtime_seconds"], 3600)
        self.assertEqual(summary["thirty_day_top"][0]["downtime_seconds"], 7200)
        self.assertEqual(summary["elevated_trends"][0]["event_count"], 2)

    def test_export_helpers_write_readable_outputs(self):
        state = {
            "magic_kingdom": {
                "1": {
                    "id": "1",
                    "name": "Space Mountain",
                    "is_open": True,
                    "downtime_events": [],
                }
            }
        }
        summary = {
            "daily_top": [],
            "thirty_day_top": [],
            "stable_park": ("Magic Kingdom", 0),
            "active_multi_ride_alerts": [],
            "elevated_trends": [],
            "active_projections": [],
        }

        self.assertIn("Most stable park", export_artifacts.build_daily_summary(summary))
        self.assertFalse(export_artifacts.build_post_candidates(summary)["posting_connected"])
        ride_map = export_artifacts.build_ride_id_map(state)
        self.assertEqual(ride_map["magic_kingdom"][0]["name"], "Space Mountain")


if __name__ == "__main__":
    unittest.main()
