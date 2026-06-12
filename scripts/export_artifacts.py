import argparse
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import parksignals
import parksignals_analytics


PARK_TIMEZONE = "America/New_York"
MAX_POST_CHARACTERS = 280
POST_RANKING_LIMIT = 3
POST_DISPLAY_REPLACEMENTS = {
    "Walt Disney World": "Disney World",
    "WDW": "Disney World",
    "Universal Orlando Resort": "Universal Orlando",
    "UOR": "Universal Orlando",
    "Universal Hollywood Resort": "Universal Hollywood",
    "UHR": "Universal Hollywood",
    "DL": "Disneyland",
    "Expedition Everest - Legend of the Forbidden Mountain": "Expedition Everest",
    "The Twilight Zone™ Tower of Terror": "The Twilight Zone Tower of Terror",
    "Star Tours - The Adventures Continue": "Star Tours",
    "Journey Into Imagination With Figment": "Journey Into Imagination",
    "Gran Fiesta Tour Starring The Three Caballeros": "Gran Fiesta Tour",
    "Tomorrowland Transit Authority PeopleMover": "PeopleMover",
    "Rock ’n’ Roller Coaster Starring The Muppets": "Rock ’n’ Roller Coaster",
}
HASHTAG_REPLACEMENTS = {
    "#WaltDisneyWorld": "#DisneyWorld",
    "#WDW": "#DisneyWorld",
    "#UniversalOrlandoResort": "#UniversalOrlando",
    "#UOR": "#UniversalOrlando",
    "#UniversalHollywoodResort": "#UniversalHollywood",
    "#UHR": "#UniversalHollywood",
    "#DL": "#Disneyland",
    "#ExpeditionEverestLegendoftheForbiddenMountain": "#ExpeditionEverest",
    "#StarToursTheAdventuresContinue": "#StarTours",
    "#JourneyIntoImaginationWithFigment": "#JourneyIntoImagination",
    "#GranFiestaTourStarringTheThreeCaballeros": "#GranFiestaTour",
    "#TomorrowlandTransitAuthorityPeopleMover": "#PeopleMover",
    "#RocknRollerCoasterStarringTheMuppets": "#RocknRollerCoaster",
}
REMOVED_HASHTAGS = {
    "#down",
    "#reopened",
    "#opsalert",
    "#dailyops",
    "#analytics",
    "#aiinsight",
    "#operations",
}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
        if not content.endswith("\n"):
            f.write("\n")


def load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def normalize_post_display_text(text):
    normalized = text
    for source, replacement in POST_DISPLAY_REPLACEMENTS.items():
        normalized = normalized.replace(source, replacement)
    return normalized


def display_resort_name(resort_name):
    return normalize_post_display_text(resort_name)


def normalize_hashtag(hashtag):
    return HASHTAG_REPLACEMENTS.get(hashtag, hashtag)


def normalize_post_hashtags(post_text):
    normalized_lines = []
    for line in post_text.splitlines():
        stripped = line.strip()
        if is_hashtag_line(stripped):
            hashtag = normalize_hashtag(stripped)
            if hashtag.lower() in REMOVED_HASHTAGS:
                continue
            normalized_lines.append(hashtag)
        else:
            normalized_lines.append(line)
    return "\n".join(trim_blank_edges(normalized_lines))


def enabled_park_lookup(config):
    lookup = {}
    for park_key, park_config in parksignals.enabled_park_configs(config):
        lookup[park_key] = park_config
        lookup[park_config["park_name"]] = park_config
    return lookup


def tags_for_park(park_config, extras=None):
    extras = extras or []
    resort_hashtag = park_config.get(
        "resort_hashtag",
        parksignals.hashtag(park_config["resort_name"])[1:],
    )
    park_hashtag = park_config.get(
        "park_hashtag",
        parksignals.hashtag(park_config["park_name"])[1:],
    )
    tags = [normalize_hashtag(f"#{resort_hashtag}"), f"#{park_hashtag}"]
    tags.extend(normalize_hashtag(tag) for tag in extras)
    return "\n".join(tag for tag in tags if tag.lower() not in REMOVED_HASHTAGS)


def is_hashtag_line(line):
    stripped = line.strip()
    return stripped.startswith("#") and " " not in stripped and len(stripped) > 1


def trim_blank_edges(lines):
    trimmed = list(lines)
    while trimmed and trimmed[0] == "":
        trimmed.pop(0)
    while trimmed and trimmed[-1] == "":
        trimmed.pop()
    return trimmed


def trim_post_hashtags(post_text, max_characters=MAX_POST_CHARACTERS):
    lines = post_text.splitlines()
    hashtag_indices = [index for index, line in enumerate(lines) if is_hashtag_line(line)]
    if len(post_text) <= max_characters or len(hashtag_indices) <= 1:
        return post_text

    protected_hashtag_index = hashtag_indices[0]
    removable_indices = [index for index in hashtag_indices if index != protected_hashtag_index]
    remaining_lines = list(lines)

    for index in reversed(removable_indices):
        remaining_lines.pop(index)
        candidate = "\n".join(trim_blank_edges(remaining_lines))
        if len(candidate) <= max_characters:
            return candidate

    return "\n".join(trim_blank_edges(remaining_lines))


def add_priority_hashtags(lines, hashtags, max_characters=MAX_POST_CHARACTERS):
    body = "\n".join(lines).rstrip()
    return trim_post_hashtags(body + "\n\n" + "\n".join(hashtags), max_characters)


def metric_line(metric, include_park=True):
    name = metric["ride_name"]
    if include_park:
        name = f"{name} ({metric['park_name']})"
    return f"{name} - {parksignals.format_duration(metric['downtime_seconds'])}"
