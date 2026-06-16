import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import x_integration


ROOT = Path(__file__).resolve().parents[1]
DISPATCH_SPEC = importlib.util.spec_from_file_location(
    "dispatch_posts",
    ROOT / "scripts" / "dispatch_posts.py",
)
dispatch_posts = importlib.util.module_from_spec(DISPATCH_SPEC)
sys.modules["dispatch_posts"] = dispatch_posts
DISPATCH_SPEC.loader.exec_module(dispatch_posts)

TEST_ENV = {
    "X_API_KEY": "api-key",
    "X_API_SECRET": "api-secret",
    "X_ACCESS_TOKEN": "access-token",
    "X_ACCESS_TOKEN_SECRET": "access-token-secret",
}


class XIntegrationTest(unittest.TestCase):
    def test_connection_status_reports_missing_credentials_without_values(self):
        with patch.dict(os.environ, {}, clear=True):
            status = x_integration.connection_status()

        self.assertFalse(status["ready_for_manual_connection_test"])
        self.assertIsNone(status["posting_connected"])
        self.assertIsNone(status["connection_test_passed"])
        self.assertEqual(status["missing_required_credentials"], x_integration.REQUIRED_SECRET_NAMES)
        self.assertNotIn("api-key", x_integration.connection_status_text(status))

    def test_connection_status_text_shows_live_posting_when_enabled(self):
        env = {**TEST_ENV, "PARKSIGNALS_X_POSTING_ENABLED": "true"}
        with patch.dict(os.environ, env, clear=True):
            status = x_integration.connection_status()
            text = x_integration.connection_status_text(status)

        self.assertIsNone(status["posting_connected"])
        self.assertEqual(status["connection_test_status"], "not_run")
        self.assertIn("Posting connected: not tested", text)
        self.assertIn("Posting enabled: true", text)
        self.assertIn("Connection test status: not_run", text)
        self.assertIn("Connection test passed: not tested", text)
        self.assertIn("Live posting is enabled", text)
        self.assertNotIn("No posts can be sent while PARKSIGNALS_X_POSTING_ENABLED is not true", text)

    def test_publish_post_is_blocked_when_safety_switch_is_off(self):
        with patch.dict(os.environ, TEST_ENV, clear=True):
            with self.assertRaises(x_integration.XIntegrationError) as raised:
                x_integration.publish_post("PARKSIGNALS // Test")

        self.assertIn("posting is disabled", str(raised.exception))

    @patch("x_integration.requests.get")
    def test_verify_connection_uses_credentials_without_posting(self, mock_get):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "id_str": "12345",
            "screen_name": "ParkSignals",
            "name": "ParkSignals",
        }
        mock_get.return_value = response

        with patch.dict(os.environ, TEST_ENV, clear=True):
            status = x_integration.verify_connection()

        self.assertTrue(status["connection_test_passed"])
        self.assertTrue(status["posting_connected"])
        self.assertFalse(status["posting_enabled"])
        self.assertEqual(status["connection_test_status"], "passed")
        self.assertEqual(status["authenticated_user"]["username"], "ParkSignals")
        mock_get.assert_called_once()

    @patch("x_integration.requests.post")
    def test_publish_post_sends_only_when_safety_switch_is_on(self, mock_post):
        response = Mock()
        response.status_code = 201
        response.json.return_value = {"data": {"id": "999", "text": "PARKSIGNALS // Test"}}
        mock_post.return_value = response

        env = {**TEST_ENV, "PARKSIGNALS_X_POSTING_ENABLED": "true"}
        with patch.dict(os.environ, env, clear=True):
            result = x_integration.publish_post("PARKSIGNALS // Test")

        self.assertTrue(result["posted"])
        self.assertEqual(result["tweet_id"], "999")
        mock_post.assert_called_once()

    @patch("x_integration.publish_post")
    def test_dispatch_prioritizes_realtime_posts_and_posts_one_at_a_time(self, mock_publish):
        mock_publish.side_effect = [
            {"tweet_id": "1"},
            {"tweet_id": "2"},
            {"tweet_id": "3"},
            {"tweet_id": "4"},
        ]
        sleep_calls = []
        plan = {
            "items": [
                self.ready_item("daily_operations_summary", "wdw_daily_summary", "daily"),
                self.ready_item("insights_predictions", "trend_detection", "trend"),
                self.ready_item("real_time_alert", "down", "single down"),
                self.ready_item("real_time_alert", "multi_ride_closure", "multi down"),
            ]
        }

        results = dispatch_posts.dispatch_ready_posts(
            plan,
            batch_size=1,
            batch_delay_seconds=60,
            sleep=sleep_calls.append,
        )

        self.assertEqual(
            [result["type"] for result in results],
            [
                "down",
                "multi_ride_closure",
                "wdw_daily_summary",
                "trend_detection",
            ],
        )
        self.assertEqual([result["batch_number"] for result in results], [1, 2, 3, 4])
        self.assertEqual(sleep_calls, [60, 60, 60])
        self.assertEqual(mock_publish.call_count, 4)

    @patch("x_integration.publish_post")
    def test_dispatch_failure_is_reported_in_results_text(self, mock_publish):
        mock_publish.side_effect = x_integration.XIntegrationError("HTTP 401 Unauthorized")
        plan = {"items": [self.ready_item("real_time_alert", "reopened", "Kali River Rapids")]}

        results = dispatch_posts.dispatch_ready_posts(plan, batch_size=1, batch_delay_seconds=60)
        text = dispatch_posts.build_results_text(results)

        self.assertEqual(results[0]["status"], "failed")
        self.assertIn("failed", text)
        self.assertIn("HTTP 401 Unauthorized", text)

    def ready_item(self, pillar, post_type, text):
        return {
            "dedupe_key": f"{pillar}:{post_type}:{text}",
            "pillar": pillar,
            "type": post_type,
            "decision": "post",
            "status": "ready_to_post",
            "preview_text": f"PARKSIGNALS // {text}",
        }


if __name__ == "__main__":
    unittest.main()
