import importlib.util
import sys
import types
import unittest
from pathlib import Path


sys.modules.setdefault("themeparks_wiki", types.SimpleNamespace(fetch_rides=lambda *args, **kwargs: []))

ROOT = Path(__file__).resolve().parents[1]
parksignals_spec = importlib.util.spec_from_file_location("parksignals", ROOT / "parksignals.py")
parksignals = importlib.util.module_from_spec(parksignals_spec)
sys.modules["parksignals"] = parksignals
parksignals_spec.loader.exec_module(parksignals)


class PostTemplateTest(unittest.TestCase):
    def setUp(self):
        self.park_config = {
            "park_name": "Hollywood Studios",
            "resort_name": "Disney World",
            "resort_hashtag": "DisneyWorld",
            "park_hashtag": "HollywoodStudios",
        }
        self.ride = {
            "name": "Tomorrowland Speedway",
            "wait_time": 15,
        }

    def test_closure_post_uses_alert_header(self):
        post = parksignals.build_post(self.park_config, self.ride, reopened=False)

        self.assertIn("ALERT: Hollywood Studios", post)

    def test_reopening_post_uses_alert_header(self):
        post = parksignals.build_post(self.park_config, self.ride, reopened=True)

        self.assertIn("ALERT: Hollywood Studios", post)
        self.assertNotIn("OK Hollywood Studios UPDATE", post)
        self.assertIn("Tomorrowland Speedway has reopened.", post)


if __name__ == "__main__":
    unittest.main()
