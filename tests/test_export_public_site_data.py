import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("export_public_site_data", ROOT / "scripts" / "export_public_site_data.py")
export_public_site_data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export_public_site_data)


class ExportPublicSiteDataTests(unittest.TestCase):
    def test_closing_grace_exports_open_rides_until_regular_close(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            original_cwd = Path.cwd()
            os.chdir(temp_path)
            try:
                Path("outputs").mkdir()
                Path("public/data").mkdir(parents=True)
                Path("parks_config.json").write_text(json.dumps({
                    "default_parks": ["epcot"],
                    "parks": {
                        "epcot": {
                            "park_name": "EPCOT",
                        }
                    },
                }))
                Path("state.json").write_text(json.dumps({
                    "epcot": {
                        "spaceship_earth": {
                            "name": "Spaceship Earth",
                            "is_open": True,
                            "planned_closure_active": False,
                            "current_down_seconds": 0,
                        }
                    }
                }))
                Path("outputs/last-run-summary.json").write_text(json.dumps({
                    "observed_at": "2026-07-11T00:58:00Z",
                    "park_statuses": [
                        {
                            "park_key": "epcot",
                            "operating_status": "closing_grace",
                            "monitoring_allowed": False,
                            "hours": {
                                "timezone": "America/New_York",
                                "opens_at": "09:00",
                                "closes_at": "21:00",
                            },
                        }
                    ],
                    "run_summaries": [
                        {
                            "park_key": "epcot",
                            "ride_ids": [
                                {
                                    "id": "spaceship_earth",
                                    "wait_time": 10,
                                }
                            ],
                        }
                    ],
                }))

                export_public_site_data.export_snapshot()
                payload = json.loads(Path("public/data/latest.json").read_text())
                park = payload["parks"][0]
                ride = park["rides"][0]

                self.assertEqual("open", ride["status"])
                self.assertEqual(1, park["open_ride_count"])
                self.assertEqual(10, park["average_wait_minutes"])
            finally:
                os.chdir(original_cwd)

    def test_planned_closure_exports_as_closed_not_unknown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            original_cwd = Path.cwd()
            os.chdir(temp_path)
            try:
                Path("outputs").mkdir()
                Path("public/data").mkdir(parents=True)
                Path("parks_config.json").write_text(json.dumps({
                    "default_parks": ["magic_kingdom"],
                    "parks": {
                        "magic_kingdom": {
                            "park_name": "Magic Kingdom",
                        }
                    },
                }))
                Path("state.json").write_text(json.dumps({
                    "magic_kingdom": {
                        "railroad": {
                            "name": "Walt Disney World Railroad",
                            "is_open": False,
                            "planned_closure_active": True,
                            "current_down_seconds": 0,
                        }
                    }
                }))
                Path("outputs/last-run-summary.json").write_text(json.dumps({
                    "observed_at": "2026-07-10T20:00:00Z",
                    "park_statuses": [
                        {
                            "park_key": "magic_kingdom",
                            "operating_status": "open",
                            "monitoring_allowed": True,
                        }
                    ],
                }))

                export_public_site_data.export_snapshot()
                payload = json.loads(Path("public/data/latest.json").read_text())
                park = payload["parks"][0]
                ride = park["rides"][0]

                self.assertEqual("closed", ride["status"])
                self.assertTrue(ride["planned_closure"])
                self.assertEqual(0, park["unavailable_ride_count"])
                self.assertEqual([], payload["closures"])
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
