import json
import os
from datetime import datetime, timezone

import requests


CONFIG_FILE = "parks_config.json"
STATE_FILE = "state.json"
DEFAULT_PARK_KEY = "magic_kingdom"
PARKS_ENV_VAR = "PARKSIGNALS_PARKS"
MAX_DOWNTIME_EVENTS_PER_RIDE = 120


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


def elapsed_seconds(started_at, ended_at):
    start = parse_timestamp(started_at)
    if start is None:
        return None

    return max(0, int((ended_at - start).total_seconds()))


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
        return [
            park_key.strip()
            for park_key in requested_parks.split(",")
            if park_key.strip()
        ]

    return config.get("default_parks", [DEFAULT_PARK_KEY])


def enabled_park_configs(config):
    parks = config.get("parks", {})

    for park_key in selected_park_keys(config):
        park_config = parks.get(park_key)
        if park_config is None:
            raise ValueError(f"Unknown park configured: {park_key}")

        if park_config.get("enabled", False):
            yield park_key, park_config


def fetch_rides(park_config):
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
            })

    return rides


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
            f"✅ {park_name} UPDATE\n\n"
            f"{ride['name']} has reopened.\n\n"
            f"Posted wait: {ride['wait_time']} minutes\n\n"
            f"{tags}\n#Reopened"
        )

    return (
        f"PARKSIGNALS // {resort_name}\n\n"
        f"🚨 {park_name} ALERT\n\n"
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
    }


def update_ride_state(ride_state, ride, observed_at):
    observed_at_text = isoformat(observed_at)
    current_status = ride["is_open"]
    previous_status = ride_state.get("is_open")

    ride_state["id"] = ride["id"]
    ride_state["name"] = ride["name"]
    ride_state["is_open"] = current_status
    ride_state["last_seen_at"] = observed_at_text

    if previous_status is None:
        ride_state["last_changed_at"] = observed_at_text
        if current_status is False:
            ride_state["down_since"] = observed_at_text
            ride_state["last_down_at"] = observed_at_text
        return None

    if previous_status == current_status:
        if current_status is False:
            ride_state["current_down_seconds"] = (
                elapsed_seconds(ride_state.get("down_since"), observed_at) or 0
            )
        else:
            ride_state["current_down_seconds"] = 0
        return None

    ride_state["last_changed_at"] = observed_at_text

    if current_status is False:
        ride_state["down_since"] = observed_at_text
        ride_state["last_down_at"] = observed_at_text
        ride_state["current_down_seconds"] = 0
        return "down"

    down_since = ride_state.get("down_since")
    duration_seconds = elapsed_seconds(down_since, observed_at) or 0
    ride_state["down_since"] = None
    ride_state["last_reopened_at"] = observed_at_text
    ride_state["current_down_seconds"] = 0
    ride_state["total_down_seconds"] = (
        int(ride_state.get("total_down_seconds", 0)) + duration_seconds
    )
    ride_state.setdefault("downtime_events", []).append({
        "down_at": down_since,
        "reopened_at": observed_at_text,
        "duration_seconds": duration_seconds,
    })
    ride_state["downtime_events"] = ride_state["downtime_events"][
        -MAX_DOWNTIME_EVENTS_PER_RIDE:
    ]
    return "reopened"


def monitor_park(park_key, park_config, state, observed_at):
    major_rides = set(park_config.get("major_rides", []))
    park_state = state.setdefault(park_key, {})
    rides = fetch_rides(park_config)
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
    }

    for ride in rides:
        if ride["name"] not in major_rides:
            continue

        matched_ride_names.add(ride["name"])
        ride_id = ride["id"]
        summary["monitored_count"] += 1
        if ride["is_open"] is False:
            summary["down_count"] += 1
        elif ride["is_open"] is True:
            summary["open_count"] += 1
        summary["ride_ids"].append({
            "id": ride_id,
            "name": ride["name"],
            "status": status_label(ride["is_open"]),
            "wait_time": ride["wait_time"],
        })

        park_state[ride_id] = normalize_ride_state(
            park_state.get(ride_id), observed_at
        )
        transition = update_ride_state(park_state[ride_id], ride, observed_at)
        if ride["is_open"] is False:
            summary["down_rides"].append({
                "name": ride["name"],
                "duration_seconds": park_state[ride_id].get(
                    "current_down_seconds", 0
                ),
            })

        if transition is not None:
            summary["transitions"].append({
                "type": transition,
                "ride_id": ride_id,
                "ride_name": ride["name"],
            })
            print(build_post(park_config, ride, reopened=transition == "reopened"))
            print("-" * 50)

    summary["missing_configured_rides"] = sorted(major_rides - matched_ride_names)
    return summary


def print_run_summary(summaries, observed_at):
    print(f"ParkSignals monitor summary at {isoformat(observed_at)}")

    for summary in summaries:
        print("")
        print(
            f"{summary['park_name']}: "
            f"{summary['monitored_count']}/{summary['configured_count']} configured "
            f"rides matched from {summary['fetched_count']} fetched rides"
        )
        print(
            f"Status: {summary['open_count']} open, "
            f"{summary['down_count']} unavailable"
        )

        if summary["down_rides"]:
            print("Currently unavailable:")
            for ride in summary["down_rides"]:
                print(
                    f"  - {ride['name']} "
                    f"({format_duration(ride['duration_seconds'])})"
                )

        print("Ride ID map:")
        for ride in summary["ride_ids"]:
            wait_time = ride["wait_time"]
            wait_text = "n/a" if wait_time is None else f"{wait_time} min"
            print(
                f"  {ride['id']}: {ride['name']} "
                f"({ride['status']}, wait {wait_text})"
            )

        if summary["transitions"]:
            print("Status changes detected:")
            for transition in summary["transitions"]:
                print(
                    f"  - {transition['ride_name']} "
                    f"({transition['ride_id']}) -> {transition['type']}"
                )
        else:
            print("No status changes detected.")

        if summary["missing_configured_rides"]:
            print("Configured rides not found in Queue-Times response:")
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
