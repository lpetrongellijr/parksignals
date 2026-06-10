import importlib.util
import json
import sys
import tempfile
import types
import unittest
from datetime import date, datetime, timezone
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

fetch_hours_spec = importlib.util.spec_from_file_location(
    "fetch_park_hours",
    ROOT / "scripts" / "fetch_park_hours.py",
)
fetch_park_hours = importlib.util.module_from_spec(fetch_hours_spec)
fetch_hours_spec.loader.exec_module(fetch_park_hours)


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

        allowed, reason = run_monitor.monitoring_hours_status(
            "magic_kingdom",
            park_config,
            observed,
            {"parks": {}},
        )

        self.assertFalse(allowed)
        self.assertIn("configured_fallback", reason)

    def test_official_hours_override_configured_fallback(self):
        observed = datetime(2026, 6, 10, 1, 30, tzinfo=timezone.utc)
        park_config = {
            "monitoring_hours": {
                "enabled": True,
                "timezone": "America/New_York",
                "opens_at": "08:00",
                "closes_at": "22:00",
            }
        }
        cache = {
            "parks": {
                "magic_kingdom": {
                    "date": "2026-06-09",
                    "source": "official_disney_calendar",
                    "timezone": "America/New_York",
                    "opens_at": "09:00",
                    "closes_at": "23:00",
                }
            }
        }

        allowed, reason = run_monitor.monitoring_hours_status(
            "magic_kingdom",
            park_config,
            observed,
            cache,
        )

        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_fetch_parser_uses_park_hours_not_special_events(self):
        parts = [
            "Magic Kingdom",
            "Mickey's Not-So-Scary Halloween Party 7:00 PM to 12:00 AM",
            "Park Hours 9:00 AM to 6:00 PM",
            "EPCOT",
            "Disney After Hours 10:00 PM to 1:00 AM",
            "Park Hours 9:00 AM to 9:00 PM",
        ]

        parsed = fetch_park_hours.parse_disney_hours(parts, date(2026, 10, 31))

        self.assertEqual(parsed["magic_kingdom"]["opens_at"], "09:00")
        self.assertEqual(parsed["magic_kingdom"]["closes_at"], "18:00")
        self.assertEqual(parsed["epcot"]["closes_at"], "21:00")

    def test_fetch_parser_handles_heading_text_and_split_hours(self):
        parts = [
            "### Magic Kingdom",
            "Early Entry",
            "8:30 AM to 9:00 AM",
            "Park Hours",
            "9:00 AM to 10:00 PM",
            "### Disney's Animal Kingdom",
            "Park Hours 8:00 AM to 6:00 PM",
        ]

        parsed = fetch_park_hours.parse_disney_hours(parts, date(2026, 6, 10))

        self.assertEqual(parsed["magic_kingdom"]["opens_at"], "09:00")
        self.assertEqual(parsed["magic_kingdom"]["closes_at"], "22:00")
        self.assertEqual(parsed["animal_kingdom"]["closes_at"], "18:00")

    def test_write_cache_records_parse_failure_without_removing_existing_hours(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "park_hours_cache.json"
            path.write_text(json.dumps({
                "parks": {
                    "magic_kingdom": {
                        "date": "2026-06-10",
                        "source": "official_disney_calendar",
                        "timezone": "America/New_York",
                        "opens_at": "09:00",
                        "closes_at": "22:00",
                    }
                }
            }))

            fetch_park_hours.write_cache(
                path,
                "https://disneyworld.disney.go.com/calendars/day/",
                {},
                status="parse_failed",
                error="No Disney park hours found",
                text_sample=["unexpected", "response"],
            )

            cache = json.loads(path.read_text())

        self.assertEqual(cache["last_fetch_status"], "parse_failed")
        self.assertIn("magic_kingdom", cache["parks"])
        self.assertEqual(cache["parks"]["magic_kingdom"]["closes_at"], "22:00")

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
