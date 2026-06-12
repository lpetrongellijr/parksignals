import os
import unittest
from unittest.mock import Mock, patch

import x_integration


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
        self.assertEqual(status["missing_required_credentials"], x_integration.REQUIRED_SECRET_NAMES)
        self.assertNotIn("api-key", x_integration.connection_status_text(status))

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


if __name__ == "__main__":
    unittest.main()
