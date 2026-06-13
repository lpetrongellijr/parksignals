import json
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

import themeparks_wiki


CONFIG_FILE = "parks_config.json"
STATE_FILE = "state.json"
DEFAULT_PARK_KEY = "magic_kingdom"
PARKS_ENV_VAR = "PARKSIGNALS_PARKS"
MAX_DOWNTIME_EVENTS_PER_RIDE = 120
DOWNTIME_EVENT_RETENTION_DAYS = 45
ANALYTICS_LOOKBACK_DAYS = 30
TREND_LOOKBACK_DAYS = 7
DEFAULT_PARK_TIMEZONE = "America/New_York"
PLANNED_EVENT_END_REASONS = {
    "planned_closure_start",
    "planned_closure",
    "refurbishment",
}


def utc_now():
    return datetime.now(timezone.utc)


def isoformat(dt):
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_timestamp(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def elapsed_seconds(started_at, ended_at):
    start = parse_timestamp(started_at)
    if start is None:
        return None
    return max(0, int((ended_at - start).total_seconds()))


def overlap_seconds(started_at, ended_at, window_start, window_end):
    start = parse_timestamp(started_at)
    end = parse_timestamp(ended_at) if ended_at else window_end
    if start is None or end is None:
        return 0
    overlap_start = max(start, window_start)
    overlap_end = min(end, window_end)
    if overlap_end <= overlap_start:
        return 0
    return int((overlap_end - overlap_start).total_seconds())


def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def selected_park_keys(config):
    requested_parks = os.getenv(PARKS_ENV_VAR)
    if requested_parks:
        return [park_key.strip() for park_key in requested_parks.split(",") if park_key.strip()]
    return config.get("default_parks", [DEFAULT_PARK_KEY])


def enabled_park_configs(config):
    parks = config.get("parks", {})
    for park_key in selected_park_keys(config):
        park_config = parks.get(park_key)
        if park_config is None:
            raise ValueError(f"Unknown park configured: {park_key}")
        if park_config.get("enabled", False):
            yield park_key, park_config


def fetch_queue_times_rides(park_config):
    url = f"https://queue-times.com/parks/{park_config['park_id']}/queue_times.json"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()
    rides = []
    for land in data.get("lands", []):
        for ride in land.get("rides", []):
            rides.append({
                "id": str(ride.get("id")),
                "name": ride.get("name"),
                "is_open": ride.get("is_open"),
                "wait_time": ride.get("wait_time"),
                "source": "queue_times",
                "source_status": None,
                "planned_closure": None,
            })
    return rides


def fetch_rides(park_config, park_key=None):
    if park_config.get("data_source") == "themeparks_wiki":
        resolved_park_key = park_key or park_config.get("park_key")
        if not resolved_park_key:
            raise ValueError("park_key is required for ThemeParks Wiki live data")
        return themeparks_wiki.fetch_rides(resolved_park_key, park_config)
    return fetch_queue_times_rides(park_config)


def status_label(is_open):
    if is_open is True:
        return "open"
    if is_open is False:
        return "unavailable"
    return "unknown"


def format_duration(seconds):
    minutes = int(seconds // 60)
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def event_is_planned(event):
    return bool(event.get("planned_closure")) or event.get("ended_by") in PLANNED_EVENT_END_REASONS


def events_in_window(ride_state, window_start, window_end):
    events = []
    for event in ride_state.get("downtime_events", []):
        if event_is_planned(event):
            continue
        duration = overlap_seconds(event.get("down_at"), event.get("reopened_at"), window_start, window_end)
        if duration > 0:
            events.append({
                "down_at": event.get("down_at"),
                "reopened_at": event.get("reopened_at"),
                "duration_seconds": duration,
            })
    if ride_state.get("is_open") is False and not ride_state.get("planned_closure_active"):
        duration = overlap_seconds(ride_state.get("down_since"), None, window_start, window_end)
        if duration > 0:
            events.append({"down_at": ride_state.get("down_since"), "reopened_at": None, "duration_seconds": duration})
    return events


def downtime_seconds_in_window(ride_state, window_start, window_end):
    return sum(event["duration_seconds"] for event in events_in_window(ride_state, window_start, window_end))


def average_completed_downtime_seconds(ride_state, window_start, window_end):
    durations = []
    for event in ride_state.get("downtime_events", []):
        if event_is_planned(event):
            continue
        reopened_at = parse_timestamp(event.get("reopened_at"))
        if reopened_at is None or reopened_at < window_start or reopened_at > window_end:
            continue
        duration = int(event.get("duration_seconds") or 0)
        if duration > 0:
            durations.append(duration)
    return int(sum(durations) / len(durations)) if durations else None


def prune_downtime_events(ride_state, observed_at):
    cutoff = observed_at - timedelta(days=DOWNTIME_EVENT_RETENTION_DAYS)
    retained_events = []
    for event in ride_state.get("downtime_events", []):
        reopened_at = parse_timestamp(event.get("reopened_at"))
        if reopened_at is None or reopened_at >= cutoff:
            retained_events.append(event)
    ride_state["downtime_events"] = retained_events[-MAX_DOWNTIME_EVENTS_PER_RIDE:]


def hashtag(value):
    return "#" + "".join(character for character in value if character.isalnum())


def ride_hashtag(ride_name):
    return hashtag(ride_name.replace("&", "and"))


def build_post(park_config, ride, reopened=False):
    park_name = park_config["park_name"]
    resort_name = park_config["resort_name"]
    resort_hashtag = park_config.get("resort_hashtag", hashtag(resort_name)[1:])
    park_tag = park_config.get("park_hashtag", hashtag(park_name)[1:])
    tags = f"#{resort_hashtag}\n#{park_tag}\n{ride_hashtag(ride['name'])}"
    if reopened:
        return (
            f"PARKSIGNALS // {resort_name}\n\n"
            f"OK {park_name} UPDATE\n\n"
            f"{ride['name']} has reopened.\n\n"
            f"Posted wait: {ride['wait_time']} minutes\n\n"
            f"{tags}\n#Reopened"
        )
    return (
        f"PARKSIGNALS // {resort_name}\n\n"
        f"ALERT: {park_name}\n\n"
        f"{ride['name']} is temporarily unavailable.\n\n"
        f"{tags}\n#Down"
    )


def normalize_ride_state(raw_state, observed_at):
    if isinstance(raw_state, dict):
        raw_state.setdefault("id", None)
        raw_state.setdefault("is_open", None)
        raw_state.setdefault("name", None)
        raw_state.setdefault("last_seen_at", None)
        raw_state.setdefault("last_changed_at", None)
        raw_state.setdefault("down_since", None)
        raw_state.setdefault("last_down_at", None)
        raw_state.setdefault("last_reopened_at", None)
        raw_state.setdefault("current_down_seconds", 0)
        raw_state.setdefault("total_down_seconds", 0)
        raw_state.setdefault("downtime_events", [])
        raw_state.setdefault("planned_closure_active", False)
        raw_state.setdefault("planned_closure", None)
        raw_state.setdefault("source", None)
        raw_state.setdefault("source_status", None)
        return raw_state
    if isinstance(raw_state, bool):
        return {
            "id": None,
            "is_open": raw_state,
            "name": None,
            "last_seen_at": isoformat(observed_at),
            "last_changed_at": None,
            "down_since": None if raw_state else isoformat(observed_at),
            "last_down_at": None if raw_state else isoformat(observed_at),
            "last_reopened_at": None,
            "current_down_seconds": 0,
            "total_down_seconds": 0,
            "downtime_events": [],
            "planned_closure_active": False,
            "planned_closure": None,
            "source": None,
            "source_status": None,
        }
    return {
        "id": None,
        "is_open": None,
        "name": None,
        "last_seen_at": None,
        "last_changed_at": None,
        "down_since": None,
        "last_down_at": None,
        "last_reopened_at": None,
        "current_down_seconds": 0,
        "total_down_seconds": 0,
        "downtime_events": [],
        "planned_closure_active": False,
        "planned_closure": None,
        "source": None,
        "source_status": None,
    }


def ride_names_for_planned_closure(entry):
    names = []
    if entry.get("ride_name"):
        names.append(entry["ride_name"])
    for field in ("ride_names", "rides"):
        names.extend(entry.get(field, []))
    return set(names)


def configured_planned_closure_for_ride(park_config, ride, observed_at):
    ride_name = ride.get("name")
    ride_id = str(ride.get("id"))
    for entry in park_config.get("planned_closures", []):
        names = ride_names_for_planned_closure(entry)
        ids = {str(value) for value in entry.get("ride_ids", [])}
        if ride_name not in names and ride_id not in ids:
            continue
        timezone_name = entry.get("timezone", DEFAULT_PARK_TIMEZONE)
        local_date = observed_at.astimezone(ZoneInfo(timezone_name)).date()
        starts_on = parse_date(entry.get("starts_on") or entry.get("start_date"))
        ends_on = parse_date(entry.get("ends_on") or entry.get("end_date"))
        if starts_on and local_date < starts_on:
            continue
        if ends_on and local_date > ends_on:
            continue
        return {
            "ride_name": ride_name,
            "starts_on": starts_on.isoformat() if starts_on else None,
            "ends_on": ends_on.isoformat() if ends_on else None,
            "reason": entry.get("reason", "planned closure"),
            "source": entry.get("source"),
        }
    return None


def planned_closure_for_ride(park_config, ride, observed_at):
    return ride.get("planned_closure") or configured_planned_closure_for_ride(park_config, ride, observed_at)


def close_operational_downtime(ride_state, ended_at, ended_by):
    down_since = ride_state.get("down_since")
    duration_seconds = elapsed_seconds(down_since, ended_at) or 0
    if duration_seconds > 0:
        ride_state["total_down_seconds"] = int(ride_state.get("total_down_seconds", 0) or 0) + duration_seconds
        ride_state.setdefault("downtime_events", []).append({
            "down_at": down_since,
            "reopened_at": isoformat(ended_at),
            "duration_seconds": duration_seconds,
            "ended_by": ended_by,
        })
        ride_state["downtime_events"] = ride_state["downtime_events"][-MAX_DOWNTIME_EVENTS_PER_RIDE:]


def mark_planned_closure(ride_state, ride, observed_at, planned_closure):
    observed_at_text = isoformat(observed_at)
    if ride_state.get("is_open") is False and ride_state.get("down_since"):
        close_operational_downtime(ride_state, observed_at, "planned_closure_start")
    ride_state["id"] = ride["id"]
    ride_state["name"] = ride["name"]
    ride_state["is_open"] = None
    ride_state["last_seen_at"] = observed_at_text
    ride_state["last_changed_at"] = ride_state.get("last_changed_at") or observed_at_text
    ride_state["down_since"] = None
    ride_state["current_down_seconds"] = 0
    ride_state["planned_closure_active"] = True
    ride_state["planned_closure"] = planned_closure
    ride_state["source"] = ride.get("source")
    ride_state["source_status"] = ride.get("source_status")
    return None


def update_ride_state(ride_state, ride, observed_at, planned_closure=None):
    if planned_closure and ride["is_open"] is False:
        return mark_planned_closure(ride_state, ride, observed_at, planned_closure)
    observed_at_text = isoformat(observed_at)
    current_status = ride["is_open"]
    previous_status = ride_state.get("is_open")
    ride_state["id"] = ride["id"]
    ride_state["name"] = ride["name"]
    ride_state["is_open"] = current_status
    ride_state["last_seen_at"] = observed_at_text
    ride_state["planned_closure_active"] = False
    ride_state["planned_closure"] = None
    ride_state["source"] = ride.get("source")
    ride_state["source_status"] = ride.get("source_status")
    if previous_status is None:
        ride_state["last_changed_at"] = observed_at_text
        if current_status is False:
            ride_state["down_since"] = observed_at_text
            ride_state["last_down_at"] = observed_at_text
        else:
            ride_state["down_since"] = None
            ride_state["current_down_seconds"] = 0
        return None
    if previous_status == current_status:
        if current_status is False:
            ride_state["current_down_seconds"] = elapsed_seconds(ride_state.get("down_since"), observed_at) or 0
        else:
            ride_state["current_down_seconds"] = 0
        return None
    ride_state["last_changed_at"] = observed_at_text
    if current_status is False:
        ride_state["down_since"] = observed_at_text
        ride_state["last_down_at"] = observed_at_text
        ride_state["current_down_seconds"] = 0
        return "down"
    close_operational_downtime(ride_state, observed_at, "reopened")
    ride_state["down_since"] = None
    ride_state["last_reopened_at"] = observed_at_text
    ride_state["current_down_seconds"] = 0
    return "reopened"


def ride_metric(park_key, park_name, ride_id, ride_state, window_start, window_end):
    return {
        "park_key": park_key,
        "park_name": park_name,
        "ride_id": ride_id,
        "ride_name": ride_state.get("name") or ride_id,
        "is_open": ride_state.get("is_open"),
        "downtime_seconds": downtime_seconds_in_window(ride_state, window_start, window_end),
        "event_count": len(events_in_window(ride_state, window_start, window_end)),
        "average_completed_downtime_seconds": average_completed_downtime_seconds(ride_state, window_start, window_end),
        "current_down_seconds": int(ride_state.get("current_down_seconds", 0) or 0),
    }


def top_downtime(metrics, limit=3):
    return [metric for metric in sorted(metrics, key=lambda item: item["downtime_seconds"], reverse=True) if metric["downtime_seconds"] > 0][:limit]


def monitor_park(park_key, park_config, state, observed_at):
    major_rides = set(themeparks_wiki.configured_ride_names(park_config))
    park_state = state.setdefault(park_key, {})
    rides = fetch_rides(park_config, park_key=park_key)
    matched_ride_names = set()
    summary = {
        "park_name": park_config["park_name"],
        "data_source": park_config.get("data_source", "queue_times"),
        "configured_count": len(major_rides),
        "fetched_count": len(rides),
        "monitored_count": 0,
        "open_count": 0,
        "down_count": 0,
        "planned_closure_count": 0,
        "ride_ids": [],
        "down_rides": [],
        "planned_closures": [],
        "transitions": [],
        "missing_configured_rides": [],
    }
    for ride in rides:
        if ride["name"] not in major_rides:
            continue
        matched_ride_names.add(ride["name"])
        ride_id = ride["id"]
        planned_closure = planned_closure_for_ride(park_config, ride, observed_at)
        planned_unavailable = planned_closure and ride["is_open"] is False
        summary["monitored_count"] += 1
        if planned_unavailable:
            summary["planned_closure_count"] += 1
            ride_status = "planned closure"
        elif ride["is_open"] is False:
            summary["down_count"] += 1
            ride_status = status_label(ride["is_open"])
        elif ride["is_open"] is True:
            summary["open_count"] += 1
            ride_status = status_label(ride["is_open"])
        else:
            ride_status = status_label(ride["is_open"])
        summary["ride_ids"].append({
            "id": ride_id,
            "name": ride["name"],
            "source_name": ride.get("source_name"),
            "source_status": ride.get("source_status"),
            "status": ride_status,
            "wait_time": ride["wait_time"],
            "planned_closure": planned_closure if planned_unavailable else None,
        })
        park_state[ride_id] = normalize_ride_state(park_state.get(ride_id), observed_at)
        transition = update_ride_state(park_state[ride_id], ride, observed_at, planned_closure=planned_closure)
        if planned_unavailable:
            summary["planned_closures"].append({
                "name": ride["name"],
                "reason": planned_closure.get("reason"),
                "source": planned_closure.get("source"),
                "starts_on": planned_closure.get("starts_on"),
                "ends_on": planned_closure.get("ends_on"),
            })
        elif ride["is_open"] is False:
            summary["down_rides"].append({"name": ride["name"], "duration_seconds": park_state[ride_id].get("current_down_seconds", 0)})
        if transition is not None:
            summary["transitions"].append({"type": transition, "ride_id": ride_id, "ride_name": ride["name"]})
            print(build_post(park_config, ride, reopened=transition == "reopened"))
            print("-" * 50)
    summary["missing_configured_rides"] = sorted(major_rides - matched_ride_names)
    return summary


def print_run_summary(summaries, observed_at):
    print(f"ParkSignals monitor summary at {isoformat(observed_at)}")
    for summary in summaries:
        print("")
        print(f"{summary['park_name']} ({summary.get('data_source', 'queue_times')}): {summary['monitored_count']}/{summary['configured_count']} configured rides matched from {summary['fetched_count']} fetched rides")
        print(f"Status: {summary['open_count']} open, {summary['down_count']} unavailable, {summary.get('planned_closure_count', 0)} planned")
        if summary["down_rides"]:
            print("Currently unavailable:")
            for ride in summary["down_rides"]:
                print(f"  - {ride['name']} ({format_duration(ride['duration_seconds'])})")
        if summary.get("planned_closures"):
            print("Planned closures/refurbishments:")
            for ride in summary["planned_closures"]:
                detail = ride.get("source") or ride.get("reason")
                print(f"  - {ride['name']} ({detail})")
        print("Ride ID map:")
        for ride in summary["ride_ids"]:
            wait_time = ride["wait_time"]
            wait_text = "n/a" if wait_time is None else f"{wait_time} min"
            source_status = f", source {ride['source_status']}" if ride.get("source_status") else ""
            print(f"  {ride['id']}: {ride['name']} ({ride['status']}, wait {wait_text}{source_status})")
        if summary["transitions"]:
            print("Status changes detected:")
            for transition in summary["transitions"]:
                print(f"  - {transition['ride_name']} ({transition['ride_id']}) -> {transition['type']}")
        else:
            print("No status changes detected.")
        if summary["missing_configured_rides"]:
            print("Configured rides not found in live response:")
            for ride_name in summary["missing_configured_rides"]:
                print(f"  - {ride_name}")


def main():
    config = load_config()
    state = load_state()
    observed_at = utc_now()
    summaries = []
    for park_key, park_config in enabled_park_configs(config):
        summaries.append(monitor_park(park_key, park_config, state, observed_at))
    save_state(state)
    print_run_summary(summaries, observed_at)


if __name__ == "__main__":
    print(f"Running ParkSignals check at {datetime.now()}")
    main()
