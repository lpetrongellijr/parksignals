import argparse
import json
import re
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen


DISNEY_DAY_URL = "https://disneyworld.disney.go.com/calendars/day/{date}/#/{park_slug}/"
PARK_LABELS = {
    "magic_kingdom": "Magic Kingdom",
    "epcot": "EPCOT",
    "hollywood_studios": "Disney's Hollywood Studios",
    "animal_kingdom": "Disney's Animal Kingdom",
}
PARK_SLUGS = {
    "magic_kingdom": "magic-kingdom",
    "epcot": "epcot",
    "hollywood_studios": "hollywood-studios",
    "animal_kingdom": "animal-kingdom",
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


def calendar_url(target_date, park_key):
    return DISNEY_DAY_URL.format(
        date=target_date.isoformat(),
        park_slug=PARK_SLUGS[park_key],
    )


def normalize_park_name(value):
    value = HEADING_PREFIX_RE.sub("", value)
    value = value.replace("Park", "")
    value = value.replace("Theme", "")
    value = value.replace("Disney's", "Disney's")
    return " ".join(value.split()).lower()


def to_24_hour(value):
    return datetime.strptime(value.replace(" ", ""), "%I:%M%p").strftime("%H:%M")


def fetch_calendar_html(url):
    request = Request(url, headers={"User-Agent": "ParkSignals/1.0"})
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def render_calendar_texts(urls):
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError("Playwright is required to render Disney park hours") from exc

    rendered = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for park_key, url in urls.items():
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)
            rendered[park_key] = page.locator("body").inner_text(timeout=30000)
            page.close()
        browser.close()
    return rendered


def extract_text(html):
    parser = TextExtractor()
    parser.feed(html)
    return parser.parts


def extract_text_lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


def matching_park_key(part, normalized_labels):
    normalized_part = normalize_park_name(part)
    for candidate_key, label in normalized_labels.items():
        if normalized_part == label:
            return candidate_key
    return None


def build_hours(target_date, match, raw, source="official_disney_calendar"):
    return {
        "date": target_date.isoformat(),
        "source": source,
        "timezone": "America/New_York",
        "opens_at": to_24_hour(match.group(1)),
        "closes_at": to_24_hour(match.group(2)),
        "raw": raw,
    }


def parse_summary_hours(parts, target_date, normalized_labels, source="official_disney_calendar"):
    hours = {}
    summary_start = None
    for index, part in enumerate(parts):
        if part.startswith("Park Hours for"):
            summary_start = index
            break
    if summary_start is None:
        return hours

    for index in range(summary_start + 1, min(summary_start + 40, len(parts))):
        park_key = matching_park_key(parts[index], normalized_labels)
        if park_key is None or park_key in hours:
            continue
        for offset in range(1, 4):
            candidate = parts[index + offset] if index + offset < len(parts) else ""
            match = TIME_RANGE_RE.search(candidate)
            if match:
                hours[park_key] = build_hours(target_date, match, candidate, source=source)
                break
    return hours


def parse_time_range_after_park(parts, start_index):
    for offset in range(1, 24):
        next_part = parts[start_index + offset] if start_index + offset < len(parts) else ""
        following_part = parts[start_index + offset + 1] if start_index + offset + 1 < len(parts) else ""
        combined_part = f"{next_part} {following_part}".strip()
        if not next_part.startswith("Park Hours"):
            continue
        return TIME_RANGE_RE.search(combined_part), combined_part
    return None, None


def parse_detail_hours(parts, target_date, normalized_labels, source="official_disney_calendar"):
    hours = {}
    for index, part in enumerate(parts):
        park_key = matching_park_key(part, normalized_labels)
        if park_key is None or park_key in hours:
            continue

        match, raw = parse_time_range_after_park(parts, index)
        if not match:
            continue
        hours[park_key] = build_hours(target_date, match, raw, source=source)
    return hours


def parse_disney_hours(parts, target_date, source="official_disney_calendar"):
    normalized_labels = {
        park_key: normalize_park_name(label)
        for park_key, label in PARK_LABELS.items()
    }
    summary_hours = parse_summary_hours(parts, target_date, normalized_labels, source=source)
    detail_hours = parse_detail_hours(parts, target_date, normalized_labels, source=source)
    return {**summary_hours, **detail_hours}


def parse_single_park_hours(park_key, parts, target_date, source):
    parsed = parse_disney_hours(parts, target_date, source=source)
    return parsed.get(park_key)


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


def fetch_and_parse_hours(target_date):
    parsed_hours = {}
    samples = []
    urls = {park_key: calendar_url(target_date, park_key) for park_key in PARK_SLUGS}
    missing_urls = {}

    for park_key, url in urls.items():
        html = fetch_calendar_html(url)
        parts = extract_text(html)
        samples.extend(parts[:5])
        park_hours = parse_single_park_hours(
            park_key,
            parts,
            target_date,
            source="official_disney_calendar_static",
        )
        if park_hours:
            parsed_hours[park_key] = park_hours
        else:
            missing_urls[park_key] = url

    if missing_urls:
        rendered_texts = render_calendar_texts(missing_urls)
        for park_key, rendered_text in rendered_texts.items():
            parts = extract_text_lines(rendered_text)
            samples.extend(parts[:5])
            park_hours = parse_single_park_hours(
                park_key,
                parts,
                target_date,
                source="official_disney_calendar_rendered",
            )
            if park_hours:
                parsed_hours[park_key] = park_hours

    return parsed_hours, ",".join(urls.values()), samples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--output", default="park_hours_cache.json")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date)
    output_path = Path(args.output)
    source_url = ",".join(calendar_url(target_date, park_key) for park_key in PARK_SLUGS)

    try:
        parsed_hours, source_url, parts = fetch_and_parse_hours(target_date)
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

    missing_parks = sorted(set(PARK_SLUGS) - set(parsed_hours))
    if missing_parks:
        message = "No Disney park hours found for: " + ", ".join(missing_parks)
        if args.strict:
            raise RuntimeError(message)
        write_cache(
            output_path,
            source_url,
            parsed_hours,
            status="partial" if parsed_hours else "parse_failed",
            error=message,
            text_sample=parts,
        )
        github_notice(message)
        print(f"{message}; cached/fallback hours will be used for missing parks")
        return

    write_cache(output_path, source_url, parsed_hours)

    print(f"Updated Disney park hours for {target_date.isoformat()}")
    for park_key, park_hours in sorted(parsed_hours.items()):
        print(f"- {park_key}: {park_hours['opens_at']} to {park_hours['closes_at']} ({park_hours['source']})")


if __name__ == "__main__":
    main()
