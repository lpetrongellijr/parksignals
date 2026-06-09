import json
import os
from datetime import datetime

import requests


CONFIG_FILE = "parks_config.json"
STATE_FILE = "state.json"
DEFAULT_PARK_KEY = "magic_kingdom"
PARKS_ENV_VAR = "PARKSIGNALS_PARKS"


def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    if is_legacy_state(state):
        return {DEFAULT_PARK_KEY: state}

    return state


def is_legacy_state(state):
    return isinstance(state, dict) and state and all(
        isinstance(value, bool) for value in state.values()
    )


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


def build_post(park_config, ride, reopened=False):
    park_name = park_config["park_name"]
    resort_tag = park_config["resort_tag"]

    if reopened:
        return (
            f"✅ {resort_tag} UPDATE\n\n"
            f"{ride['name']} has reopened at {park_name}.\n\n"
            f"Current wait: {ride['wait_time']} minutes."
        )

    return (
        f"🚨 {resort_tag} ALERT\n\n"
        f"{ride['name']} is currently unavailable at {park_name}.\n\n"
        f"Follow @ParkSignals for live ride downtime updates."
    )


def monitor_park(park_key, park_config, state):
    major_rides = set(park_config.get("major_rides", []))
    park_state = state.setdefault(park_key, {})

    for ride in fetch_rides(park_config):
        if ride["name"] not in major_rides:
            continue

        ride_id = ride["id"]
        current_status = ride["is_open"]
        previous_status = park_state.get(ride_id)

        if previous_status is None:
            park_state[ride_id] = current_status
            continue

        if previous_status != current_status:
            reopened = current_status is True
            print(build_post(park_config, ride, reopened=reopened))
            print("-" * 50)

        park_state[ride_id] = current_status


def main():
    config = load_config()
    state = load_state()

    for park_key, park_config in enabled_park_configs(config):
        monitor_park(park_key, park_config, state)

    save_state(state)


if __name__ == "__main__":
    print(f"Running ParkSignals check at {datetime.now()}")
    main()
