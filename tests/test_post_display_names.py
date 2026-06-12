import importlib.util
import sys
import types
import unittest
from pathlib import Path


sys.modules.setdefault("requests", types.SimpleNamespace(get=lambda *args, **kwargs: None))

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

parksignals_spec = importlib.util.spec_from_file_location("parksignals", ROOT / "parksignals.py")
parksignals = importlib.util.module_from_spec(parksignals_spec)
parksignals_spec.loader.exec_module(parksignals)
sys.modules["parksignals"] = parksignals

export_spec = importlib.util.spec_from_file_location(
    "export_artifacts",
    ROOT / "scripts" / "export_artifacts.py",
)
export_artifacts = importlib.util.module_from_spec(export_spec)
export_spec.loader.exec_module(export_artifacts)


class PostDisplayNameTest(unittest.TestCase):
    def test_post_text_uses_short_everest_and_no_tower_tm(self):
        post = "\n".join([
            "PARKSIGNALS // Disney World",
            "",
            "1. Expedition Everest - Legend of the Forbidden Mountain (Animal Kingdom) - 20m",
            "2. The Twilight Zone™ Tower of Terror (Hollywood Studios) - 15m",
            "",
            "#DisneyWorld",
            "#ExpeditionEverestLegendoftheForbiddenMountain",
        ])

        normalized = export_artifacts.normalize_post_hashtags(
            export_artifacts.normalize_post_display_text(post)
        )

        self.assertIn("Expedition Everest (Animal Kingdom)", normalized)
        self.assertIn("The Twilight Zone Tower of Terror", normalized)
        self.assertIn("#ExpeditionEverest", normalized)
        self.assertNotIn("Expedition Everest - Legend of the Forbidden Mountain", normalized)
        self.assertNotIn("™", normalized)
        self.assertNotIn("#ExpeditionEverestLegendoftheForbiddenMountain", normalized)

    def test_post_text_uses_shortened_names_for_common_long_titles(self):
        post = "\n".join([
            "Star Tours - The Adventures Continue",
            "Journey Into Imagination With Figment",
            "Gran Fiesta Tour Starring The Three Caballeros",
            "Tomorrowland Transit Authority PeopleMover",
            "Rock ’n’ Roller Coaster Starring The Muppets",
            "Walt Disney’s Carousel of Progress",
            "Walt Disney's Carousel of Progress",
            "#StarToursTheAdventuresContinue",
            "#JourneyIntoImaginationWithFigment",
            "#GranFiestaTourStarringTheThreeCaballeros",
            "#TomorrowlandTransitAuthorityPeopleMover",
            "#RocknRollerCoasterStarringTheMuppets",
            "#WaltDisneysCarouselofProgress",
        ])

        normalized = export_artifacts.normalize_post_hashtags(
            export_artifacts.normalize_post_display_text(post)
        )

        self.assertIn("Star Tours", normalized)
        self.assertIn("Journey Into Imagination", normalized)
        self.assertIn("Gran Fiesta Tour", normalized)
        self.assertIn("PeopleMover", normalized)
        self.assertIn("Rock ’n’ Roller Coaster", normalized)
        self.assertEqual(normalized.count("Carousel of Progress"), 2)
        self.assertIn("#StarTours", normalized)
        self.assertIn("#JourneyIntoImagination", normalized)
        self.assertIn("#GranFiestaTour", normalized)
        self.assertIn("#PeopleMover", normalized)
        self.assertIn("#RocknRollerCoaster", normalized)
        self.assertIn("#CarouselofProgress", normalized)
        self.assertNotIn("Star Tours - The Adventures Continue", normalized)
        self.assertNotIn("Journey Into Imagination With Figment", normalized)
        self.assertNotIn("Gran Fiesta Tour Starring The Three Caballeros", normalized)
        self.assertNotIn("Tomorrowland Transit Authority PeopleMover", normalized)
        self.assertNotIn("Rock ’n’ Roller Coaster Starring The Muppets", normalized)
        self.assertNotIn("Walt Disney’s Carousel of Progress", normalized)
        self.assertNotIn("Walt Disney's Carousel of Progress", normalized)


if __name__ == "__main__":
    unittest.main()
