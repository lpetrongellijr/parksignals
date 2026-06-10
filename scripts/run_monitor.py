import json
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import parksignals


PARK_HOURS_CACHE_FILE = "park_hours_cache.json"


def parse_local_time(value):
    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute))


def is_time_in_window(current_time, opens_at, closes_at):
    if opens_at <= closes_at:
        return opens_at <= current_time < closes_at
    return current_time >= opens_at or current_time < closes_at


def load_park_hours_cache(path=PARK_HOURS_CACHE_FILE):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"parks": {}, "last_fetch_status": "missing_or_invalid_cache"}


def official_hours_for_park(park_key, observed_at, cache):
    park_hours = cache.get("parks", {}).get(park_key)
    if not park_hours:
        return None

    timezone_name = park_hours.get("timezone") or cache.get("timezone", "America/New_York")
    local_date = observed_at.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    if park_hours.get("date") != local_date:
        return None

    return {
        "source": park_hours.get("source", "official_disney_calendar"),
        "timezone": timezone_name,
        "opens_at": park_hours["opens_at"],
        "closes_at": park_hours["closes_at"],
    }


def configured_hours_for_park(park_config):
    hours = park_config.get("monitoring_hours")
    if not hours or hours.get("enabled") is False:
        return None

    return {
        "source": "configured_fallback",
        "timezone": hours.get("timezone", "America/New_York"),
        "opens_at": hours["opens_at"],
        "closes_at": hours["closes_at"],
    }


def resolved_monitoring_hours(park_key, park_config, observed_at, cache):
    return (
        official_hours_for_park(park_key, observed_at, cache)
        or configured_hours_for_park(park_config)
    )


def monitoring_hours_status(park_key, park_config, observed_at, cache=None):
    cache = cache or {"parks": {}}
    hours = resolved_monitoring_hours(park_key, park_config, observed_at, cache)
    if not hours:
        return True, None

    timezone_name = hours["timezone"]
    local_observed_at = observed_at.astimezone(ZoneInfo(timezone_name))
    opens_at = parse_local_time(hours["opens_at"])
    closes_at = parse_local_time(hours["closes_at"])
    if is_time_in_window(local_observed_at.time(), opens_at, closes_at):
        return True, None

    return False, (
        f"outside {hours['source']} monitoring hours "
        f"({local_observed_at.strftime('%H:%M')} {timezone_name}; "
        f"window {hours['opens_at']}-{hours['closes_at']})"
    )


def build_suppressed_summary(park_key, park_config, observed_at, reason):
    major_rides = set(park_config.get("major_rides", []))
    rides = parksignals.fetch_rides(park_config)
    matched_ride_names = set()
    summary = {
        "park_name": park_config["park_name"],
        "configured_count": len(major_rides),
        "fetched_count": len(rides),
        "monitored_count": 0,
        "open_count": 0,
        "down_count": 0,
        "ride_ids": [],
        "down_rides": [],
        "transitions": [],
        "missing_configured_rides": [],
        "monitoring_suppressed": True,
        "suppression_reason": reason,
    }

    for ride in rides:
        if ride["name"] not in major_rides:
            continue

        matched_ride_names.add(ride["name"])
        summary["monitored_count"] += 1
        if ride["is_open"] is False:
            summary["down_count"] += 1
        elif ride["is_open"] is True:
            summary["open_count"] += 1
        summary["ride_ids"].append({
            "id": ride["id"],
            "name": ride["name"],
            "status": parksignals.status_label(ride["is_open"]),
            "wait_time": ride["wait_time"],
        })

    summary["missing_configured_rides"] = sorted(major_rides - matched_ride_names)
    return summary


def print_hours_source_notes(config, observed_at, cache):
    print("")
    print("Park hours source")
    fallback_parks = []
    for park_key, park_config in parksignals.enabled_park_configs(config):
        hours = resolved_monitoring_hours(park_key, park_config, observed_at, cache)
        if not hours:
            print(f"- {park_config['park_name']}: no monitoring-hours guard configured")
            continue
        print(
            f"- {park_config['park_name']}: {hours['source']} "
            f"{hours['opens_at']}-{hours['closes_at']} {hours['timezone']}"
        )
        if hours["source"] == "configured_fallback":
            fallback_parks.append(park_config["park_name"])

    if fallback_parks:
        print("")
        print("Park hours fallback notice")
        print(
            "Official Disney hours were not available for: "
            + ", ".join(fallback_parks)
        )
        print("Using configured fallback hours from parks_config.json.")
        if cache.get("last_fetch_status") and cache.get("last_fetch_status") != "ok":
            print(f"Last official-hours fetch status: {cache['last_fetch_status']}")
        if cache.get("last_fetch_error"):
            print(f"Last official-hours fetch error: {cache['last_fetch_error']}")


def print_suppression_notes(summaries):
    suppressed = [summary for summary in summaries if summary.get("monitoring_suppressed")]
    if not suppressed:
        return

    print("")
    print("Downtime tracking suppressed")
    for summary in suppressed:
        print(f"- {summary['park_name']}: {summary['suppression_reason']}")


def run():
    config = parksignals.load_config()
    state = parksignals.load_state()
    observed_at = parksignals.utc_now()
    hours_cache = load_park_hours_cache()
    summaries = []

    for park_key, park_config in parksignals.enabled_park_configs(config):
        monitoring_allowed, reason = monitoring_hours_status(
            park_key,
            park_config,
            observed_at,
            hours_cache,
        )
        if monitoring_allowed:
            summaries.append(parksignals.monitor_park(park_key, park_config, state, observed_at))
        else:
            summaries.append(build_suppressed_summary(park_key, park_config, observed_at, reason))

    pillar_summary = parksignals.collect_content_pillar_summary(state, config, observed_at)
    parksignals.save_state(state)
    parksignals.print_run_summary(summaries, observed_at)
    print_hours_source_notes(config, observed_at, hours_cache)
    print_suppression_notes(summaries)
    parksignals.print_content_pillar_summary(pillar_summary, summaries)


if __name__ == "__main__":
    print(f"Running ParkSignals check at {datetime.now()}")
    run()
