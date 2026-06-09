import json
import requests
from datetime import datetime

PARK_ID = 6
PARK_NAME = "Magic Kingdom"
RESORT_TAG = "WDW"

URL = f"https://queue-times.com/parks/{PARK_ID}/queue_times.json"

STATE_FILE = "state.json"

MAJOR_RIDES = {
    "TRON Lightcycle / Run",
    "Space Mountain",
    "Seven Dwarfs Mine Train",
    "Big Thunder Mountain Railroad",
    "Pirates of the Caribbean",
    "Haunted Mansion",
    "Jungle Cruise",
}

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def fetch_rides():
    response = requests.get(URL, timeout=10)
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

def build_post(ride, reopened=False):
    if reopened:
        return (
            f"✅ {RESORT_TAG} UPDATE\n\n"
            f"{ride['name']} has reopened at {PARK_NAME}.\n\n"
            f"Current wait: {ride['wait_time']} minutes."
        )

    return (
        f"🚨 {RESORT_TAG} ALERT\n\n"
        f"{ride['name']} is currently unavailable at {PARK_NAME}.\n\n"
        f"Follow @ParkSignals for live ride downtime updates."
    )

def main():
    rides = fetch_rides()
    state = load_state()

    for ride in rides:
        if ride["name"] not in MAJOR_RIDES:
            continue

        ride_id = ride["id"]
        current_status = ride["is_open"]
        previous_status = state.get(ride_id)

        if previous_status is None:
            state[ride_id] = current_status
            continue

        if previous_status != current_status:
            reopened = current_status is True
            print(build_post(ride, reopened=reopened))
            print("-" * 50)

        state[ride_id] = current_status

    save_state(state)

if __name__ == "__main__":
    print(f"Running ParkSignals check at {datetime.now()}")
    main()
