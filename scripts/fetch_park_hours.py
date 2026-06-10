import argparse
import json
import re
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen


DISNEY_CALENDAR_URL = "https://disneyworld.disney.go.com/calendars/day/"
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
HEADING_PREFIX_RE = re.compile(r"^[#\s]+")


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def github_notice(message):
    print(f"::notice title=Park hours fallback::{message}")


def normalize_park_name(value):
    value = HEADING_PREFIX_RE.sub("", value)
    value = value.replace("Park", "")
    value = value.replace("Theme", "")
    value = value.replace("Disney's", "Disney's")
    return " ".join(value.split()).lower()


def to_24_hour(value):
    return datetime.strptime(value.replace(" ", ""), "%I:%M%p").strftime("%H:%M")


def fetch_calendar_html(_target_date):
    request = Request(DISNEY_CALENDAR_URL, headers={"User-Agent": "ParkSignals/1.0"})
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace"), DISNEY_CALENDAR_URL


def extract_text(html):
    parser = TextExtractor()
    parser.feed(html)
    return parser.parts


def matching_park_key(part, normalized_labels):
    normalized_part = normalize_park_name(part)
    for candidate_key, label in normalized_labels.items():
        if normalized_part == label:
            return candidate_key
    return None


def parse_time_range_after_park(parts, start_index):
    for offset in range(1, 24):
        next_part = parts[start_index + offset] if start_index + offset < len(parts) else ""
        following_part = parts[start_index + offset + 1] if start_index + offset + 1 < len(parts) else ""
        combined_part = f"{next_part} {following_part}".strip()
        if not next_part.startswith("Park Hours"):
            continue
        return TIME_RANGE_RE.search(combined_part), combined_part
    return None, None


def parse_disney_hours(parts, target_date):
    hours = {}
    normalized_labels = {
        park_key: normalize_park_name(label)
        for park_key, label in PARK_LABELS.items()
    }

    for index, part in enumerate(parts):
        park_key = matching_park_key(part, normalized_labels)
        if park_key is None or park_key in hours:
            continue

        match, raw = parse_time_range_after_park(parts, index)
        if not match:
            continue
        hours[park_key] = {
            "date": target_date.isoformat(),
            "source": "official_disney_calendar",
            "timezone": "America/New_York",
            "opens_at": to_24_hour(match.group(1)),
            "closes_at": to_24_hour(match.group(2)),
            "raw": raw,
        }

    return hours


def load_existing(path):
    if not path.exists():
        return {"parks": {}}
    with open(path, "r") as f:
        return json.load(f)


def fallback_notice(status, error):
    return {
        "status": status,
        "message": (
            "Official Disney park hours were not updated; "
            "ParkSignals will use cached official hours when valid, otherwise configured fallback hours."
        ),
        "error": error,
    }


def write_cache(path, source_url, parsed_hours, status="ok", error=None, text_sample=None):
    cache = load_existing(path)
    cache.update({
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "source_url": source_url,
        "timezone": "America/New_York",
        "special_events_extend_monitoring": False,
        "last_fetch_status": status,
    })
    if error:
        cache["last_fetch_error"] = error
        cache["fallback_notice"] = fallback_notice(status, error)
    else:
        cache.pop("last_fetch_error", None)
        cache.pop("fallback_notice", None)
    if text_sample:
        cache["last_fetch_text_sample"] = text_sample[:20]
    else:
        cache.pop("last_fetch_text_sample", None)

    if parsed_hours:
        cache.setdefault("parks", {}).update(parsed_hours)

    with open(path, "w") as f:
        json.dump(cache, f, indent=2)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--output", default="park_hours_cache.json")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date)
    output_path = Path(args.output)
    source_url = DISNEY_CALENDAR_URL

    try:
        html, source_url = fetch_calendar_html(target_date)
        parts = extract_text(html)
        parsed_hours = parse_disney_hours(parts, target_date)
    except Exception as exc:
        if args.strict:
            raise
        message = str(exc)
        write_cache(
            output_path,
            source_url,
            {},
            status="fetch_failed",
            error=message,
        )
        github_notice(message)
        print(f"Disney park hours fetch failed; existing cache/fallback hours will be used: {message}")
        return

    if not parsed_hours:
        message = "No Disney park hours found in official calendar response"
        if args.strict:
            raise RuntimeError(message)
        write_cache(
            output_path,
            source_url,
            {},
            status="parse_failed",
            error=message,
            text_sample=parts,
        )
        github_notice(message)
        print(f"{message}; existing cache/fallback hours will be used")
        return

    write_cache(output_path, source_url, parsed_hours)

    print(f"Updated Disney park hours for {target_date.isoformat()} from {source_url}")
    for park_key, park_hours in sorted(parsed_hours.items()):
        print(f"- {park_key}: {park_hours['opens_at']} to {park_hours['closes_at']}")


if __name__ == "__main__":
    main()
