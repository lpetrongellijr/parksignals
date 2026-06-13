import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("themeparks_wiki", ROOT / "themeparks_wiki.py")
themeparks_wiki = importlib.util.module_from_spec(spec)
spec.loader.exec_module(themeparks_wiki)


class ThemeParksWikiTest(unittest.TestCase):
    def test_status_mapping(self):
        self.assertIs(themeparks_wiki.status_to_is_open("OPERATING"), True)
        self.assertIs(themeparks_wiki.status_to_is_open("DOWN"), False)
        self.assertIs(themeparks_wiki.status_to_is_open("CLOSED"), False)
        self.assertIs(themeparks_wiki.status_to_is_open("REFURBISHMENT"), False)
        self.assertIsNone(themeparks_wiki.status_to_is_open("UNKNOWN"))

    def test_refurbishment_status_creates_planned_closure(self):
        planned = themeparks_wiki.planned_closure_from_status(
            "REFURBISHMENT",
            {"name": "Kali River Rapids"},
        )
        self.assertEqual(planned["reason"], "refurbishment")
        self.assertEqual(planned["source"], "themeparks_wiki_live_status")

    def test_name_normalization_handles_punctuation_and_marks(self):
        self.assertEqual(
            themeparks_wiki.normalize_name("The Twilight Zone™ Tower of Terror"),
            themeparks_wiki.normalize_name("The Twilight Zone Tower of Terror"),
        )
        self.assertEqual(
            themeparks_wiki.normalize_name("Na’vi River Journey"),
            themeparks_wiki.normalize_name("Na'vi River Journey"),
        )

    def test_alias_matching(self):
        park_config = {
            "major_rides": ["Soarin' Across America"],
            "ride_name_aliases": {
                "Soarin' Across America": ["Soarin' Around America"],
            },
        }
        live_by_name = {
            themeparks_wiki.normalize_name("Soarin' Around America"): {
                "id": "abc",
                "name": "Soarin' Around America",
            }
        }
        item, alias = themeparks_wiki.match_live_item(
            "Soarin' Across America",
            park_config,
            live_by_name,
        )
        self.assertEqual(item["id"], "abc")
        self.assertEqual(alias, "Soarin' Around America")


if __name__ == "__main__":
    unittest.main()
