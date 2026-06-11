import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


sys.modules.setdefault("requests", types.SimpleNamespace(get=lambda *args, **kwargs: None))

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

spec = importlib.util.spec_from_file_location("parksignals", ROOT / "parksignals.py")
parksignals = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parksignals)
sys.modules["parksignals"] = parksignals

analytics_spec = importlib.util.spec_from_file_location(
    "parksignals_analytics",
    ROOT / "scripts" / "parksignals_analytics.py",
)
parksignals_analytics = importlib.util.module_from_spec(analytics_spec)
analytics_spec.loader.exec_module(parksignals_analytics)
sys.modules["parksignals_analytics"] = parksignals_analytics

export_spec = importlib.util.spec_from_file_location(
    "export_artifacts",
    ROOT / "scripts" / "export_artifacts.py",
)
export_artifacts = importlib.util.module_from_spec(export_spec)
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

        summary = parksignals_analytics.collect_content_pillar_summary(state, config, observed)

        self.assertEqual(summary["daily_top"][0]["downtime_seconds"], 3600)
        self.assertEqual(summary["thirty_day_top"][0]["downtime_seconds"], 7200)
        self.assertEqual(summary["elevated_trends"][0]["event_count"], 2)

    def test_daily_summary_uses_eastern_park_day_after_utc_midnight(self):
        observed = datetime(2026, 6, 11, 0, 5, 5, tzinfo=timezone.utc)
        config = {
            "default_parks": ["hollywood_studios"],
            "parks": {
                "hollywood_studios": {
                    "enabled": True,
                    "park_name": "Hollywood Studios",
                    "major_rides": ["Rock ’n’ Roller Coaster Starring The Muppets"],
                }
            },
        }
        state = {
            "hollywood_studios": {
                "80010190": {
                    "id": "80010190",
                    "name": "Rock ’n’ Roller Coaster Starring The Muppets",
                    "is_open": True,
                    "current_down_seconds": 0,
                    "downtime_events": [
                        {
                            "down_at": "2026-06-10T22:21:15Z",
                            "reopened_at": "2026-06-11T00:05:05Z",
                            "duration_seconds": 6230,
                        }
                    ],
                }
            }
        }

        summary = parksignals_analytics.collect_content_pillar_summary(state, config, observed)

        self.assertEqual(summary["daily_window_timezone"], "America/New_York")
        self.assertEqual(summary["daily_window_start"], "2026-06-10T04:00:00Z")
        self.assertEqual(summary["daily_top"][0]["downtime_seconds"], 6230)
        self.assertEqual(summary["thirty_day_top"][0]["downtime_seconds"], 6230)

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
        config = {
            "default_parks": ["magic_kingdom"],
            "parks": {
                "magic_kingdom": {
                    "enabled": True,
                    "park_name": "Magic Kingdom",
                    "resort_name": "Walt Disney World",
                    "major_rides": ["Space Mountain"],
                }
            },
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
        candidates = export_artifacts.build_post_candidates(
            summary,
            config,
            {"run_summaries": []},
            "2026-06-09T12:00:00Z",
        )
        self.assertFalse(candidates["posting_connected"])
        ride_map = export_artifacts.build_ride_id_map(state)
        self.assertEqual(ride_map["magic_kingdom"][0]["name"], "Space Mountain")


if __name__ == "__main__":
    unittest.main()
