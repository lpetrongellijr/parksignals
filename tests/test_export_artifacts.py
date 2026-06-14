import importlib.util
import sys
import types
import unittest
from pathlib import Path


sys.modules.setdefault("requests", types.SimpleNamespace(get=lambda *args, **kwargs: None))

ROOT = Path(__file__).resolve().parents[1]
parksignals_spec = importlib.util.spec_from_file_location("parksignals", ROOT / "parksignals.py")
parksignals = importlib.util.module_from_spec(parksignals_spec)
sys.modules["parksignals"] = parksignals
parksignals_spec.loader.exec_module(parksignals)

analytics_module = types.SimpleNamespace(collect_content_pillar_summary=lambda *args, **kwargs: {})
sys.modules.setdefault("parksignals_analytics", analytics_module)

export_spec = importlib.util.spec_from_file_location(
    "export_artifacts",
    ROOT / "scripts" / "export_artifacts.py",
)
export_artifacts = importlib.util.module_from_spec(export_spec)
export_spec.loader.exec_module(export_artifacts)


class ExportArtifactsTest(unittest.TestCase):
    def test_multi_ride_closure_suppresses_overlapping_single_closures(self):
        config = {
            "default_parks": ["magic_kingdom"],
            "parks": {
                "magic_kingdom": {
                    "enabled": True,
                    "park_name": "Magic Kingdom",
                    "resort_name": "Walt Disney World",
                    "resort_hashtag": "WaltDisneyWorld",
                    "park_hashtag": "MagicKingdom",
                }
            },
        }
        last_run = {
            "run_summaries": [
                {
                    "park_key": "magic_kingdom",
                    "park_name": "Magic Kingdom",
                    "ride_ids": [
                        {"id": "pirates", "name": "Pirates of the Caribbean", "wait_time": None},
                        {"id": "small-world", "name": "\"it's a small world\"", "wait_time": None},
                    ],
                    "transitions": [
                        {"type": "down", "ride_id": "pirates", "ride_name": "Pirates of the Caribbean"},
                        {"type": "down", "ride_id": "small-world", "ride_name": "\"it's a small world\""},
                    ],
                }
            ]
        }
        summary = {
            "daily_top": [],
            "active_multi_ride_alerts": [],
            "monthly_reliability_ready": False,
            "trend_insights_ready": False,
            "elevated_trends": [],
            "active_projections": [],
        }

        candidates = export_artifacts.build_post_candidates(
            summary,
            config,
            last_run,
            "2026-06-14T15:15:00Z",
        )

        self.assertEqual(candidates["single_ride_closures"], [])
        self.assertEqual(len(candidates["multi_ride_closures"]), 1)
        self.assertEqual(
            candidates["multi_ride_closures"][0]["rides"],
            ["Pirates of the Caribbean", "\"it's a small world\""],
        )

    def test_single_closure_remains_when_no_multi_ride_closure_exists(self):
        config = {
            "default_parks": ["magic_kingdom"],
            "parks": {
                "magic_kingdom": {
                    "enabled": True,
                    "park_name": "Magic Kingdom",
                    "resort_name": "Walt Disney World",
                    "resort_hashtag": "WaltDisneyWorld",
                    "park_hashtag": "MagicKingdom",
                }
            },
        }
        last_run = {
            "run_summaries": [
                {
                    "park_key": "magic_kingdom",
                    "park_name": "Magic Kingdom",
                    "ride_ids": [
                        {"id": "pirates", "name": "Pirates of the Caribbean", "wait_time": None},
                    ],
                    "transitions": [
                        {"type": "down", "ride_id": "pirates", "ride_name": "Pirates of the Caribbean"},
                    ],
                }
            ]
        }
        summary = {
            "daily_top": [],
            "active_multi_ride_alerts": [],
            "monthly_reliability_ready": False,
            "trend_insights_ready": False,
            "elevated_trends": [],
            "active_projections": [],
        }

        candidates = export_artifacts.build_post_candidates(
            summary,
            config,
            last_run,
            "2026-06-14T15:15:00Z",
        )

        self.assertEqual(len(candidates["single_ride_closures"]), 1)
        self.assertEqual(candidates["multi_ride_closures"], [])


if __name__ == "__main__":
    unittest.main()
