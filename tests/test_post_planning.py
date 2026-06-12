import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

parksignals_spec = importlib.util.spec_from_file_location("parksignals", ROOT / "parksignals.py")
parksignals = importlib.util.module_from_spec(parksignals_spec)
parksignals_spec.loader.exec_module(parksignals)
sys.modules["parksignals"] = parksignals

sys.modules.setdefault(
    "x_integration",
    types.SimpleNamespace(
        posting_enabled=lambda: False,
        connection_status=lambda: {"ready_for_manual_connection_test": True},
    ),
)

plan_spec = importlib.util.spec_from_file_location(
    "plan_posts",
    ROOT / "scripts" / "plan_posts.py",
)
plan_posts = importlib.util.module_from_spec(plan_spec)
plan_spec.loader.exec_module(plan_posts)


class PostPlanningTest(unittest.TestCase):
    def test_monitor_context_blocks_daily_summary_candidate(self):
        policy = {
            "dry_run": True,
            "max_post_characters": 280,
            "require_x_credentials": True,
            "pillars": {
                "daily_operations_summary": {
                    "enabled": True,
                    "types": {"wdw_daily_summary": True},
                },
            },
            "rules": {
                "block_daily_summary_outside_daily_workflow": True,
                "block_empty_daily_summary": True,
            },
        }
        candidates = {
            "observed_at": "2026-06-12T17:00:22Z",
            "daily_summaries": [
                {
                    "pillar": "daily_operations_summary",
                    "type": "wdw_daily_summary",
                    "preview_text": "PARKSIGNALS // Disney World\n\nDisney World Summary - June 12, 2026",
                    "metrics": [{"ride_name": "Frozen Ever After"}],
                },
            ],
        }
        x_status = {"ready_for_manual_connection_test": True}

        monitor_plan = plan_posts.build_plan(
            candidates,
            policy,
            x_status,
            {"posted_keys": [], "decisions": []},
            {},
            post_context=plan_posts.POST_CONTEXT_MONITOR,
        )
        daily_plan = plan_posts.build_plan(
            candidates,
            policy,
            x_status,
            {"posted_keys": [], "decisions": []},
            {},
            post_context=plan_posts.POST_CONTEXT_DAILY_SUMMARY,
        )

        self.assertEqual(monitor_plan["items"][0]["decision"], "skip")
        self.assertIn("daily_summary_not_in_daily_workflow", monitor_plan["items"][0]["reasons"])
        self.assertEqual(daily_plan["items"][0]["decision"], "would_post")

    def test_multi_ride_alert_keys_are_stable_for_the_day(self):
        candidate_a = {
            "pillar": "real_time_alert",
            "type": "multi_ride_closure",
            "park_name": "EPCOT",
            "rides": ["Frozen Ever After", "Journey Into Imagination With Figment"],
            "preview_text": "PARKSIGNALS // Disney World",
        }
        candidate_b = {
            **candidate_a,
            "rides": ["Journey Into Imagination With Figment", "Frozen Ever After"],
        }

        first_key = plan_posts.candidate_key(candidate_a, "2026-06-12T17:00:22Z")
        second_key = plan_posts.candidate_key(candidate_b, "2026-06-12T17:15:20Z")
        next_day_key = plan_posts.candidate_key(candidate_a, "2026-06-13T17:00:22Z")

        self.assertEqual(first_key, second_key)
        self.assertNotEqual(first_key, next_day_key)
        self.assertNotIn("17:00:22Z", first_key)

    def test_multi_ride_reopening_candidates_are_ignored_but_single_reopenings_remain(self):
        candidates = {
            "single_ride_reopenings": [
                {"park_name": "EPCOT", "ride_name": "Frozen Ever After"},
                {"park_name": "EPCOT", "ride_name": "Journey Into Imagination With Figment"},
                {"park_name": "Hollywood Studios", "ride_name": "Slinky Dog Dash"},
            ],
            "multi_ride_reopenings": [
                {
                    "park_name": "EPCOT",
                    "rides": ["Frozen Ever After", "Journey Into Imagination With Figment"],
                },
            ],
        }

        grouped = list(plan_posts.candidate_groups(candidates))
        single_reopenings = [item for group, item in grouped if group == "single_ride_reopenings"]
        multi_reopenings = [item for group, item in grouped if group == "multi_ride_reopenings"]

        self.assertEqual(len(single_reopenings), 3)
        self.assertEqual(len(multi_reopenings), 0)


if __name__ == "__main__":
    unittest.main()
