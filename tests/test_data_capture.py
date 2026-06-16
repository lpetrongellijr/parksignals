import importlib.util
import json
import sys
import tempfile
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

analytics_spec = importlib.util.spec_from_file_location(
    "parksignals_analytics",
    ROOT / "scripts" / "parksignals_analytics.py",
)
parksignals_analytics = importlib.util.module_from_spec(analytics_spec)
sys.modules["parksignals_analytics"] = parksignals_analytics
analytics_spec.loader.exec_module(parksignals_analytics)

data_capture_spec = importlib.util.spec_from_file_location(
    "data_capture",
    ROOT / "scripts" / "data_capture.py",
)
data_capture = importlib.util.module_from_spec(data_capture_spec)
data_capture_spec.loader.exec_module(data_capture)


class DataCaptureTest(unittest.TestCase):
    def test_update_history_captures_samples_events_downtime_and_waits(self):
        observed_at = datetime(2026, 6, 15, 15, 30, tzinfo=timezone.utc)
        config = {
            "default_parks": ["magic_kingdom"],
            "parks": {
                "magic_kingdom": {
                    "enabled": True,
                    "park_name": "Magic Kingdom",
                }
            },
        }
        state = {
            "magic_kingdom": {
                "pirates": {
                    "name": "Pirates of the Caribbean",
                    "is_open": False,
                    "down_since": "2026-06-15T15:00:00Z",
                    "last_seen_at": "2026-06-15T15:30:00Z",
                    "downtime_events": [],
                },
                "space": {
                    "name": "Space Mountain",
                    "is_open": True,
                    "last_seen_at": "2026-06-15T15:30:00Z",
                    "downtime_events": [],
                },
            }
        }
        summaries = [
            {
                "park_key": "magic_kingdom",
                "park_name": "Magic Kingdom",
                "monitoring_suppressed": False,
                "ride_ids": [
                    {
                        "id": "pirates",
                        "name": "Pirates of the Caribbean",
                        "status": "unavailable",
                        "wait_time": None,
                    },
                    {
                        "id": "space",
                        "name": "Space Mountain",
                        "status": "open",
                        "wait_time": 45,
                    },
                ],
                "transitions": [
                    {
                        "type": "down",
                        "ride_id": "pirates",
                        "ride_name": "Pirates of the Caribbean",
                    }
                ],
            },
            {
                "park_key": "epcot",
                "park_name": "EPCOT",
                "monitoring_suppressed": True,
                "ride_ids": [
                    {
                        "id": "guardians",
                        "name": "Guardians of the Galaxy: Cosmic Rewind",
                        "status": "open",
                        "wait_time": 70,
                    }
                ],
                "transitions": [],
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "analytics_history.json"
            output_dir = Path(temp_dir) / "outputs"
            history = data_capture.update_history(
                state,
                config,
                summaries,
                observed_at,
                path=history_path,
                output_dir=output_dir,
            )

            saved = json.loads(history_path.read_text())
            day = saved["days"]["2026-06-15"]
            rides = day["parks"]["magic_kingdom"]["rides"]

            self.assertEqual(history["runs_captured"], 1)
            self.assertEqual(rides["pirates"]["down_event_count"], 1)
            self.assertEqual(rides["pirates"]["down_samples"], 1)
            self.assertEqual(rides["pirates"]["downtime_seconds"], 1800)
            self.assertEqual(rides["space"]["average_wait_time"], 45.0)
            self.assertNotIn("epcot", day["parks"])
            self.assertTrue((output_dir / "data-capture-summary.txt").exists())
            self.assertTrue((output_dir / "data-capture-summary.json").exists())


if __name__ == "__main__":
    unittest.main()
