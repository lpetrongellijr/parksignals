import argparse
import json
import re
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


THEMEPARKS_DESTINATIONS_URL = "https://api.themeparks.wiki/v1/destinations"
THEMEPARKS_SCHEDULE_URL = "https://api.themeparks.wiki/v1/entity/{entity_id}/schedule"
REGULAR_SCHEDULE_TYPE = "OPERATING"
DISNEY_DAY_URL = "https://disneyworld.disney.go.com/calendars/day/{date}/#/{park_slug}/"
DISNEY_DAY_BASE_URL = "https://disneyworld.disney.go.com/calendars/day/{date}/"
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
PARK_NAME_MATCHES = {
    "magic_kingdom": ["magic kingdom"],
    "epcot": ["epcot"],
    "hollywood_studios": ["hollywood studios"],
    "animal_kingdom": ["animal kingdom"],
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


def get_json(url):
    request = Request(url, headers={"User-Agent": "ParkSignals/1.0"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def calendar_url(target_date, park_key):
    return DISNEY_DAY_URL.format(
        date=target_date.isoformat(),
        park_slug=PARK_SLUGS[park_key],
    )


def base_calendar_url(target_date):
    return DISNEY_DAY_BASE_URL.format(date=target_date.isoformat())


def normalize_park_name(value):
    value = HEADING_PREFIX_RE.sub("", value)
    value = value.replace("Park", "")
    value = value.replace("Theme", "")
    value = value.replace("Disney's", "Disney's")
    return " ".join(value.split()).lower()


def to_24_hour(value):
    return datetime.strptime(value.replace(" ", ""), "%I:%M%p").strftime("%H:%M")


def iso_to_local_hhmm(value, timezone_name="America/New_York"):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(ZoneInfo(timezone_name)).strftime("%H:%M")


def local_date_for_entry(entry):
    opening = entry.get("openingTime")
    if not opening:
        return None
    return datetime.fromisoformat(opening.replace("Z", "+00:00")).astimezone(
        ZoneInfo("America/New_York")
    ).date()


def schedule_entry_summary(entry):
    return {
        "type": entry.get("type"),
        "openingTime": entry.get("openingTime"),
        "closingTime": entry.get("closingTime"),
        "description": entry.get("description"),
    }


def fetch_calendar_html(url):
    request = Request(url, headers={"User-Agent": "ParkSignals/1.0"})
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def rendered_text_from_page(page, url, park_slug=None):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    if park_slug:
        page.evaluate("slug => { window.location.hash = '/' + slug + '/'; }", park_slug)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(5000)
    return page.locator("body").inner_text(timeout=30000)


def render_calendar_texts(target_date, urls):
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError("Playwright is required to render Disney park hours") from exc

    rendered = {}
    errors = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            args=["--disable-http2", "--disable-features=NetworkService"]
        )
        context = browser.new_context(
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        for park_key, url in urls.items():
            page = context.new_page()
            try:
                try:
                    rendered[park_key] = rendered_text_from_page(page, url)
                except Exception:
                    rendered[park_key] = rendered_text_from_page(
                        page,
                        base_calendar_url(target_date),
                        park_slug=PARK_SLUGS[park_key],
                    )
            except Exception as exc:
                errors[park_key] = str(exc)
                print(f"Could not render Disney hours for {park_key}: {exc}")
            finally:
                page.close()
        context.close()
        browser.close()
    return rendered, errors


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
        "selected_schedule_type": REGULAR_SCHEDULE_TYPE,
        "ignored_schedule_entries": [],
        "raw": raw,
    }


def build_api_hours(target_date, schedule_entry, ignored_entries, source="themeparks_wiki"):
    return {
        "date": target_date.isoformat(),
        "source": source,
        "timezone": "America/New_York",
        "opens_at": iso_to_local_hhmm(schedule_entry["openingTime"]),
        "closes_at": iso_to_local_hhmm(schedule_entry["closingTime"]),
        "selected_schedule_type": REGULAR_SCHEDULE_TYPE,
        "ignored_schedule_entries": ignored_entries,
        "raw": schedule_entry,
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


def find_destinations_list(payload):
    if isinstance(payload, list):
        return payload
    for key in ("destinations", "data"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return []


def iter_entities(entity):
    yield entity
    for child_key in ("parks", "children", "entities"):
        for child in entity.get(child_key, []) or []:
            yield from iter_entities(child)


def find_wdw_destination(destinations):
    for destination in destinations:
        name = destination.get("name", "").lower()
        if "walt disney world" in name:
            return destination
    return None


def match_park_entity(park_key, entities):
    matches = PARK_NAME_MATCHES[park_key]
    for entity in entities:
        entity_type = str(entity.get("entityType") or entity.get("type") or "").lower()
        name = entity.get("name", "").lower()
        if entity_type and "park" not in entity_type:
            continue
        if any(match in name for match in matches):
            return entity
    return None


def entries_for_date(schedule_payload, target_date):
    entries = schedule_payload.get("schedule", schedule_payload if isinstance(schedule_payload, list) else [])
    return [entry for entry in entries if local_date_for_entry(entry) == target_date]


def regular_and_ignored_entries_for_date(schedule_payload, target_date):
    regular_entry = None
    ignored_entries = []
    for entry in entries_for_date(schedule_payload, target_date):
        entry_type = entry.get("type")
        if entry_type == REGULAR_SCHEDULE_TYPE and regular_entry is None:
            regular_entry = entry
        else:
            ignored_entries.append(schedule_entry_summary(entry))
    return regular_entry, ignored_entries


def fetch_themeparks_wiki_hours(target_date):
    destinations_payload = get_json(THEMEPARKS_DESTINATIONS_URL)
    destination = find_wdw_destination(find_destinations_list(destinations_payload))
    if not destination:
        raise RuntimeError("ThemeParks.wiki Walt Disney World destination not found")

    entities = list(iter_entities(destination))
    hours = {}
    missing = []
    for park_key in PARK_SLUGS:
        entity = match_park_entity(park_key, entities)
        if not entity or not entity.get("id"):
            missing.append(park_key)
            continue
        schedule = get_json(THEMEPARKS_SCHEDULE_URL.format(entity_id=entity["id"]))
        entry, ignored_entries = regular_and_ignored_entries_for_date(schedule, target_date)
        if entry:
            hours[park_key] = build_api_hours(target_date, entry, ignored_entries)
        else:
            missing.append(park_key)

    if missing:
        print("ThemeParks.wiki missing hours for: " + ", ".join(sorted(missing)))
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
            "Park hours were not fully updated; ParkSignals will use cached "
            "machine-readable hours when valid, otherwise configured fallback hours."
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


def fetch_disney_web_hours(target_date):
    parsed_hours = {}
    samples = []
    errors = {}
    urls = {park_key: calendar_url(target_date, park_key) for park_key in PARK_SLUGS}
    missing_urls = {}

    for park_key, url in urls.items():
        try:
            html = fetch_calendar_html(url)
            parts = extract_text(html)
            samples.extend(parts[:5])
            park_hours = parse_single_park_hours(
                park_key,
                parts,
                target_date,
                source="official_disney_calendar_static",
            )
        except Exception as exc:
            errors[park_key] = str(exc)
            park_hours = None
        if park_hours:
            parsed_hours[park_key] = park_hours
        else:
            missing_urls[park_key] = url

    if missing_urls:
        rendered_texts, render_errors = render_calendar_texts(target_date, missing_urls)
        errors.update(render_errors)
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

    if errors:
        samples.append("render_errors: " + json.dumps(errors, sort_keys=True)[:1000])

    return parsed_hours, ",".join(urls.values()), samples


def fetch_and_parse_hours(target_date):
    samples = []
    parsed_hours = {}
    errors = []

    try:
        parsed_hours.update(fetch_themeparks_wiki_hours(target_date))
    except Exception as exc:
        errors.append("ThemeParks.wiki: " + str(exc))

    missing = set(PARK_SLUGS) - set(parsed_hours)
    if missing:
        try:
            disney_hours, disney_source, disney_samples = fetch_disney_web_hours(target_date)
            samples.extend(disney_samples)
            for park_key in missing:
                if park_key in disney_hours:
                    parsed_hours[park_key] = disney_hours[park_key]
        except Exception as exc:
            errors.append("Disney calendar: " + str(exc))
            disney_source = ",".join(calendar_url(target_date, park_key) for park_key in PARK_SLUGS)
    else:
        disney_source = "not_needed"

    if errors:
        samples.append("source_errors: " + json.dumps(errors)[:1000])

    source_url = THEMEPARKS_DESTINATIONS_URL + " | " + disney_source
    return parsed_hours, source_url, samples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--output", default="park_hours_cache.json")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date)
    output_path = Path(args.output)
    source_url = THEMEPARKS_DESTINATIONS_URL

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
        print(f"Park hours fetch failed; existing cache/fallback hours will be used: {message}")
        return

    missing_parks = sorted(set(PARK_SLUGS) - set(parsed_hours))
    if missing_parks:
        message = "No park hours found for: " + ", ".join(missing_parks)
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

    print(f"Updated park hours for {target_date.isoformat()}")
    for park_key, park_hours in sorted(parsed_hours.items()):
        print(
            f"- {park_key}: {park_hours['opens_at']} to {park_hours['closes_at']} "
            f"({park_hours['source']}, selected {park_hours['selected_schedule_type']}, "
            f"ignored {len(park_hours['ignored_schedule_entries'])})"
        )


if __name__ == "__main__":
    main()
