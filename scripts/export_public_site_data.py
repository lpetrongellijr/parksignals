"""Export a safe, public ParkSignals snapshot for the website."""

import json
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


OUTPUT_FILE = Path("public") / "data" / "latest.json"
HISTORY_OUTPUT_FILE = Path("public") / "data" / "history.json"
INTRADAY_OUTPUT_FILE = Path("public") / "data" / "intraday.json"
PARK_TIMEZONE = ZoneInfo("America/New_York")
PARK_SLUGS = {
    "magic_kingdom": "magic-kingdom",
    "epcot": "epcot",
    "hollywood_studios": "hollywood-studios",
    "animal_kingdom": "animal-kingdom",
}
DISPLAY_NAMES = {
    "Big Thunder Mountain Railroad": "Big Thunder Mountain",
    "Expedition Everest - Legend of the Forbidden Mountain": "Expedition Everest",
    "The Twilight Zone Tower of Terror": "Tower of Terror",
    "Star Tours - The Adventures Continue": "Star Tours",
    "Journey Into Imagination With Figment": "Journey Into Imagination",
    "Gran Fiesta Tour Starring The Three Caballeros": "Gran Fiesta Tour",
    "Tomorrowland Transit Authority PeopleMover": "PeopleMover",
    "Rock 'n' Roller Coaster Starring The Muppets": "Rock 'n' Roller Coaster",
    "Walt Disney's Carousel of Progress": "Carousel of Progress",
}


def load_json(path, default):
    try:
        with open(path, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def parse_timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def iso_timestamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_local_time(value):
    if not value or not isinstance(value, str):
        return None
    try:
        hour, minute = value.split(":", 1)
        return time(int(hour), int(minute))
    except ValueError:
        return None


def within_regular_hours(hours, observed_at):
    if not isinstance(hours, dict):
        return None
    timezone_name = hours.get("timezone") or "America/New_York"
    opens_at = parse_local_time(hours.get("opens_at"))
    closes_at = parse_local_time(hours.get("closes_at"))
    if not opens_at or not closes_at:
        return None
    local_time = observed_at.astimezone(ZoneInfo(timezone_name)).time()
    if opens_at == closes_at:
        return True
    if opens_at < closes_at:
        return opens_at <= local_time < closes_at
    return local_time >= opens_at or local_time < closes_at


def display_name(name):
    return DISPLAY_NAMES.get(name, name)


def overlap_seconds(start, end, window_start, window_end):
    if start is None or end is None:
        return 0
    return max(0, int((min(end, window_end) - max(start, window_start)).total_seconds()))


def downtime_today(ride_state, observed_at):
    local = observed_at.astimezone(PARK_TIMEZONE)
    start = datetime.combine(local.date(), time.min, tzinfo=PARK_TIMEZONE).astimezone(timezone.utc)
    end = datetime.combine(local.date(), time.max, tzinfo=PARK_TIMEZONE).astimezone(timezone.utc)
    total = sum(
        overlap_seconds(
            parse_timestamp(event.get("down_at")),
            parse_timestamp(event.get("reopened_at")),
            start,
            end,
        )
        for event in ride_state.get("downtime_events", [])
    )
    if ride_state.get("is_open") is False:
        total += overlap_seconds(parse_timestamp(ride_state.get("down_since")), observed_at, start, end)
    return total


def latest_ride_details(last_run):
    return {
        summary.get("park_key"): {
            str(ride.get("id")): {"wait_time_minutes": ride.get("wait_time")}
            for ride in summary.get("ride_ids", [])
        }
        for summary in last_run.get("run_summaries", [])
    }


def export_intraday_samples(last_run, config, observed_at, output_path=INTRADAY_OUTPUT_FILE):
    local_date = observed_at.astimezone(PARK_TIMEZONE).date().isoformat()
    existing = load_json(output_path, {})
    if existing.get("date") != local_date:
        existing = {"schema_version": 1, "date": local_date, "timezone": "America/New_York", "samples": []}

    samples = existing.setdefault("samples", [])
    seen = {
        (sample.get("observed_at"), sample.get("ride_id"))
        for sample in samples
    }
    observed_at_text = iso_timestamp(observed_at)
    for summary in last_run.get("run_summaries", []):
        if summary.get("monitoring_suppressed"):
            continue
        park_key = summary.get("park_key")
        if not park_key:
            continue
        park_config = config.get("parks", {}).get(park_key, {})
        for ride in summary.get("ride_ids", []):
            wait_time = ride.get("wait_time")
            if not isinstance(wait_time, int):
                continue
            ride_id = str(ride.get("id"))
            key = (observed_at_text, ride_id)
            if key in seen:
                continue
            samples.append({
                "observed_at": observed_at_text,
                "ride_id": ride_id,
                "ride_name": display_name(ride.get("name") or ride_id),
                "park_id": park_key,
                "park_name": park_config.get("park_name", park_key.replace("_", " ").title()),
                "park_slug": PARK_SLUGS.get(park_key, park_key.replace("_", "-")),
                "wait_time_minutes": wait_time,
            })
            seen.add(key)

    existing["generated_at"] = observed_at_text
    existing["samples"] = sorted(samples, key=lambda sample: (sample["observed_at"], sample["park_slug"], sample["ride_name"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as file:
        json.dump(existing, file, indent=2)
        file.write("\n")
    print(f"Wrote public website intraday samples to {output_path}")



def latest_updates(last_run, state, config, observed_at):
    updates = []
    for summary in last_run.get("run_summaries", []):
        park_key = summary.get("park_key")
        park_config = config.get("parks", {}).get(park_key, {})
        for transition in summary.get("transitions", []):
            ride_id = str(transition.get("ride_id"))
            ride_state = state.get(park_key, {}).get(ride_id, {})
            transition_type = transition.get("type")
            timestamp_key = "last_reopened_at" if transition_type == "reopened" else "last_down_at"
            updates.append({
                "type": transition_type,
                "ride_id": ride_id,
                "ride_name": display_name(transition.get("ride_name") or ride_id),
                "park_id": park_key,
                "park_name": park_config.get("park_name", park_key.replace("_", " ").title()),
                "park_slug": PARK_SLUGS.get(park_key, park_key.replace("_", "-")),
                "observed_at": ride_state.get(timestamp_key) or iso_timestamp(observed_at),
            })
    return sorted(updates, key=lambda update: update["observed_at"], reverse=True)[:12]


def export_snapshot(output_path=OUTPUT_FILE):
    config = load_json(Path("parks_config.json"), {})
    state = load_json(Path("state.json"), {})
    last_run = load_json(Path("outputs") / "last-run-summary.json", {})
    observed_at = parse_timestamp(last_run.get("observed_at")) or datetime.now(timezone.utc)
    status_by_key = {
        item.get("park_key"): item for item in last_run.get("park_statuses", [])
        if item.get("park_key")
    }
    ride_details = latest_ride_details(last_run)
    parks, all_rides = [], []

    for park_key in config.get("default_parks", []):
        park_config = config.get("parks", {}).get(park_key, {})
        park_status = status_by_key.get(park_key, {})
        operating_status = park_status.get("operating_status", "unknown")
        hours_are_open = within_regular_hours(park_status.get("hours"), observed_at)
        park_is_open = hours_are_open if hours_are_open is not None else operating_status == "open"
        rides = []
        for ride_id, ride_state in state.get(park_key, {}).items():
            if not isinstance(ride_state, dict):
                continue
            is_open = ride_state.get("is_open")
            planned_closure = bool(ride_state.get("planned_closure_active"))
            status = "park_closed" if not park_is_open else (
                "closed" if planned_closure else "open" if is_open is True else "unavailable" if is_open is False else "unknown"
            )
            ride = {
                "id": ride_id,
                "name": display_name(ride_state.get("name") or ride_id),
                "status": status,
                "wait_time_minutes": ride_details.get(park_key, {}).get(ride_id, {}).get("wait_time_minutes"),
                "downtime_today_seconds": downtime_today(ride_state, observed_at),
                "current_downtime_seconds": int(ride_state.get("current_down_seconds") or 0),
                "planned_closure": planned_closure,
                "last_seen_at": ride_state.get("last_seen_at"),
                "park_id": park_key,
                "park_name": park_config.get("park_name", park_key.replace("_", " ").title()),
                "park_slug": PARK_SLUGS.get(park_key, park_key.replace("_", "-")),
            }
            rides.append(ride)
            all_rides.append(ride)
        rides.sort(key=lambda ride: ride["name"].lower())
        waits = [ride["wait_time_minutes"] for ride in rides if ride["status"] == "open" and isinstance(ride["wait_time_minutes"], int)]
        parks.append({
            "id": park_key,
            "slug": PARK_SLUGS.get(park_key, park_key.replace("_", "-")),
            "name": park_config.get("park_name", park_key.replace("_", " ").title()),
            "status": operating_status,
            "monitoring_active": bool(park_status.get("monitoring_allowed")),
            "hours": park_status.get("hours"),
            "tracked_ride_count": len(rides),
            "open_ride_count": sum(ride["status"] == "open" for ride in rides),
            "unavailable_ride_count": sum(ride["status"] == "unavailable" and not ride["planned_closure"] for ride in rides),
            "average_wait_minutes": round(sum(waits) / len(waits)) if waits else None,
            "rides": rides,
        })

    closures = [ride for ride in all_rides if ride["status"] == "unavailable" and not ride["planned_closure"]]
    closures.sort(key=lambda ride: ride["current_downtime_seconds"], reverse=True)
    downtime = [ride for ride in all_rides if ride["downtime_today_seconds"] > 0]
    downtime.sort(key=lambda ride: ride["downtime_today_seconds"], reverse=True)
    payload = {
        "schema_version": 1,
        "generated_at": iso_timestamp(observed_at),
        "timezone": "America/New_York",
        "source": "ParkSignals monitoring data",
        "parks": parks,
        "closures": closures,
        "latest_updates": latest_updates(last_run, state, config, observed_at),
        "downtime_today": downtime,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as file:
        json.dump(payload, file, indent=2)
        file.write("\n")
    print(f"Wrote public website snapshot to {output_path}")
    export_intraday_samples(last_run, config, observed_at)


def public_history(output_path=HISTORY_OUTPUT_FILE):
    history = load_json(Path("analytics_history.json"), {})
    generated_at = parse_timestamp(history.get("last_observed_at")) or datetime.now(timezone.utc)
    days = []

    for date, day in sorted(history.get("days", {}).items()):
        rides = []
        for park_key, park in day.get("parks", {}).items():
            for ride_id, ride in park.get("rides", {}).items():
                average_wait = ride.get("average_wait_time")
                max_wait = ride.get("max_wait_time") or 0
                busyness_score = None
                if isinstance(average_wait, (int, float)) and max_wait:
                    busyness_score = min(100, round((average_wait / max_wait) * 100))
                rides.append({
                    "date": date,
                    "ride_id": str(ride_id),
                    "ride_name": display_name(ride.get("ride_name") or str(ride_id)),
                    "park_id": park_key,
                    "park_name": park.get("park_name", park_key.replace("_", " ").title()),
                    "park_slug": PARK_SLUGS.get(park_key, park_key.replace("_", "-")),
                    "samples": int(ride.get("samples") or 0),
                    "open_samples": int(ride.get("open_samples") or 0),
                    "down_event_count": int(ride.get("down_event_count") or 0),
                    "downtime_seconds": int(ride.get("downtime_seconds") or 0),
                    "average_wait_minutes": round(average_wait) if isinstance(average_wait, (int, float)) else None,
                    "min_wait_minutes": ride.get("min_wait_time"),
                    "max_wait_minutes": ride.get("max_wait_time"),
                    "busyness_score": busyness_score,
                })
        days.append({
            "date": date,
            "last_observed_at": day.get("last_observed_at"),
            "rides": sorted(rides, key=lambda ride: (ride["park_name"], ride["ride_name"])),
        })

    payload = {
        "schema_version": 1,
        "generated_at": iso_timestamp(generated_at),
        "timezone": "America/New_York",
        "source": "ParkSignals daily analytics history",
        "days": days,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as file:
        json.dump(payload, file, indent=2)
        file.write("\n")
    print(f"Wrote public website history to {output_path}")


if __name__ == "__main__":
    export_snapshot()
    public_history()
