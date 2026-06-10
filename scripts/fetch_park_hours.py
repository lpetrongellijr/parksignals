import argparse
import json
import re
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen


DISNEY_CALENDAR_URL = "https://disneyworld.disney.go.com/calendars/day/{date}/"
PARK_LABELS = {
    "magic_kingdom": "Magic Kingdom",
    "epcot": "EPCOT",
    "hollywood_studios": "Disney's Hollywood Studios",
    "animal_kingdom": "Disney's Animal Kingdom",
}
TIME_RANGE_RE = re.compile(
    r"(\d{1,2}:\d{2}\s*[AP]M)\s+to\s+(\d{1,2}:\d{2}\s*[AP]M)",
    re.IGNORECASE,
)


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def normalize_park_name(value):
    return " ".join(value.replace("Park", "").split()).lower()


def to_24_hour(value):
    return datetime.strptime(value.replace(" ", ""), "%I:%M%p").strftime("%H:%M")


def fetch_calendar_html(target_date):
    url = DISNEY_CALENDAR_URL.format(date=target_date.isoformat())
    request = Request(url, headers={"User-Agent": "ParkSignals/1.0"})
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace"), url


def extract_text(html):
    parser = TextExtractor()
    parser.feed(html)
    return parser.parts


def parse_disney_hours(parts, target_date):
    hours = {}
    normalized_labels = {
        park_key: normalize_park_name(label)
        for park_key, label in PARK_LABELS.items()
    }

    for index, part in enumerate(parts):
        normalized_part = normalize_park_name(part)
        park_key = None
        for candidate_key, label in normalized_labels.items():
            if normalized_part == label:
                park_key = candidate_key
                break
        if park_key is None or park_key in hours:
            continue

        for next_part in parts[index + 1:index + 20]:
            if not next_part.startswith("Park Hours"):
                continue
            match = TIME_RANGE_RE.search(next_part)
            if not match:
                continue
            hours[park_key] = {
                "date": target_date.isoformat(),
                "source": "official_disney_calendar",
                "timezone": "America/New_York",
                "opens_at": to_24_hour(match.group(1)),
                "closes_at": to_24_hour(match.group(2)),
                "raw": next_part,
            }
            break

    return hours


def load_existing(path):
    if not path.exists():
        return {"parks": {}}
    with open(path, "r") as f:
        return json.load(f)


def write_cache(path, source_url, parsed_hours):
    cache = load_existing(path)
    cache.update({
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "source_url": source_url,
        "timezone": "America/New_York",
        "special_events_extend_monitoring": False,
    })
    cache.setdefault("parks", {}).update(parsed_hours)

    with open(path, "w") as f:
        json.dump(cache, f, indent=2)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--output", default="park_hours_cache.json")
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date)
    html, source_url = fetch_calendar_html(target_date)
    parsed_hours = parse_disney_hours(extract_text(html), target_date)
    if not parsed_hours:
        raise RuntimeError("No Disney park hours found in official calendar response")

    write_cache(Path(args.output), source_url, parsed_hours)

    print(f"Updated Disney park hours for {target_date.isoformat()} from {source_url}")
    for park_key, park_hours in sorted(parsed_hours.items()):
        print(f"- {park_key}: {park_hours['opens_at']} to {park_hours['closes_at']}")


if __name__ == "__main__":
    main()
