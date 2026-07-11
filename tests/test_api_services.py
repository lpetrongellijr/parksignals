import json
import tempfile
import unittest
from pathlib import Path

from api.services import NotFoundError, ParkSignalsDataService


class ParkSignalsDataServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        latest = {
            "generated_at": "2026-07-11T01:40:34Z",
            "timezone": "America/New_York",
            "source": "ParkSignals monitoring data",
            "parks": [
                {
                    "id": "magic_kingdom",
                    "slug": "magic-kingdom",
                    "name": "Magic Kingdom",
                    "status": "open",
                    "hours": {
                        "source": "themeparks_wiki",
                        "timezone": "America/New_York",
                        "opens_at": "09:00",
                        "closes_at": "23:00",
                    },
                    "tracked_ride_count": 1,
                    "open_ride_count": 1,
                    "unavailable_ride_count": 0,
                    "average_wait_minutes": 30,
                    "rides": [
                        {
                            "id": "ride-1",
                            "name": "Space Mountain",
                            "status": "open",
                            "wait_time_minutes": 35,
                            "downtime_today_seconds": 0,
                            "current_downtime_seconds": 0,
                            "planned_closure": False,
                            "last_seen_at": "2026-07-11T01:40:34Z",
                            "park_id": "magic_kingdom",
                            "park_name": "Magic Kingdom",
                            "park_slug": "magic-kingdom",
                        }
                    ],
                }
            ],
            "closures": [],
            "latest_updates": [],
            "downtime_today": [],
        }
        history = {
            "days": [
                {
                    "date": "2026-07-10",
                    "rides": [
                        {
                            "ride_id": "ride-1",
                            "ride_name": "Space Mountain",
                            "average_wait_minutes": 32,
                        }
                    ],
                }
            ]
        }
        intraday = {
            "samples": [
                {
                    "observed_at": "2026-07-11T01:40:34Z",
                    "ride_id": "ride-1",
                    "ride_name": "Space Mountain",
                    "wait_time_minutes": 35,
                }
            ]
        }
        (self.data_dir / "latest.json").write_text(json.dumps(latest))
        (self.data_dir / "history.json").write_text(json.dumps(history))
        (self.data_dir / "intraday.json").write_text(json.dumps(intraday))
        archive_dir = self.data_dir / "archive"
        archive_dir.mkdir()
        (archive_dir / "wait-samples.jsonl").write_text(json.dumps({
            "observed_at": "2026-07-11T01:40:34Z",
            "ride_id": "ride-1",
            "ride_name": "Space Mountain",
            "park_id": "magic_kingdom",
            "park_name": "Magic Kingdom",
            "park_slug": "magic-kingdom",
            "wait_time_minutes": 35,
            "status": "open",
        }) + "\n")
        (archive_dir / "ride-events.jsonl").write_text(json.dumps({
            "observed_at": "2026-07-11T01:35:34Z",
            "event_type": "reopened",
            "ride_id": "ride-1",
            "ride_name": "Space Mountain",
            "park_id": "magic_kingdom",
            "park_name": "Magic Kingdom",
            "park_slug": "magic-kingdom",
        }) + "\n")
        (archive_dir / "park-hours.jsonl").write_text(json.dumps({
            "date": "2026-07-10",
            "park_id": "magic_kingdom",
            "park_name": "Magic Kingdom",
            "park_slug": "magic-kingdom",
            "timezone": "America/New_York",
            "opens_at": "09:00",
            "closes_at": "23:00",
            "source": "themeparks_wiki",
            "last_observed_at": "2026-07-11T01:40:34Z",
        }) + "\n")
        (archive_dir / "daily-ride-metrics.json").write_text(json.dumps(history))
        self.service = ParkSignalsDataService(data_dir=self.data_dir, cache_ttl_seconds=60)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_park_summary_uses_public_slug_id(self):
        park = self.service.resolve_park("magic-kingdom")
        summary = self.service.park_summary(park)

        self.assertEqual("magic-kingdom", summary["id"])
        self.assertEqual("Magic Kingdom", summary["name"])
        self.assertEqual("open", summary["status"])
        self.assertEqual(40, summary["crowdScore"])
        self.assertEqual("23:00", summary["operatingHours"]["closesAt"])

    def test_ride_detail_includes_history_and_intraday_samples(self):
        detail = self.service.ride_detail(self.service.resolve_ride("space-mountain"))

        self.assertEqual("ride-1", detail["id"])
        self.assertEqual("Space Mountain", detail["name"])
        self.assertEqual(35, detail["currentWait"])
        self.assertEqual(1, len(detail["history"]))
        self.assertEqual(1, len(detail["intradaySamples"]))

    def test_waits_can_filter_by_park(self):
        waits = self.service.waits("magic-kingdom")

        self.assertEqual(1, len(waits))
        self.assertEqual("ride-1", waits[0]["rideId"])

    def test_missing_park_raises_not_found(self):
        with self.assertRaises(NotFoundError):
            self.service.resolve_park("not-a-park")

    def test_archive_wait_samples_can_filter_by_ride(self):
        samples = self.service.wait_samples(ride_id="space-mountain")

        self.assertEqual(1, len(samples))
        self.assertEqual(35, samples[0]["wait_time_minutes"])

    def test_archive_ride_events_can_filter_by_park(self):
        events = self.service.ride_events(park_id="magic-kingdom")

        self.assertEqual(1, len(events))
        self.assertEqual("reopened", events[0]["event_type"])

    def test_archive_park_hours_can_filter_by_date(self):
        hours = self.service.park_hours_history(park_id="magic-kingdom", start_date="2026-07-10", end_date="2026-07-10")

        self.assertEqual(1, len(hours))
        self.assertEqual("23:00", hours[0]["closes_at"])


if __name__ == "__main__":
    unittest.main()
