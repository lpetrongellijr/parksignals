import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

try:
    import tweepy
except Exception:  # tweepy is optional until X posting is enabled
    tweepy = None

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state" / "ride_status.json"
QUEUE_TIMES_URL = "https://queue-times.com/parks/{park_id}/queue_times.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def fetch_park_rides(park_id: int) -> List[Dict[str, Any]]:
    url = QUEUE_TIMES_URL.format(park_id=park_id)
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    data = response.json()

    rides: List[Dict[str, Any]] = []
    for land in data.get("lands", []):
        land_name = land.get("name", "Unknown Land")
        for ride in land.get("rides", []):
            rides.append(
                {
                    "id": str(ride.get("id")),
                    "name": ride.get("name"),
                    "is_open": ride.get("is_open"),
                    "wait_time": ride.get("wait_time"),
                    "last_updated": ride.get("last_updated"),
                    "land": land_name,
                }
            )
    return rides


def build_alert_text(
    resort_tag: str,
    park_name: str,
    ride: Dict[str, Any],
    previous_is_open: Optional[bool],
    account_handle: str,
) -> Optional[str]:
    current_is_open = ride.get("is_open")
    ride_name = ride.get("name")

    if previous_is_open is True and current_is_open is False:
        return (
            f"🚨 {resort_tag} ALERT\n\n"
            f"{ride_name} is currently unavailable at {park_name}.\n\n"
            f"Follow {account_handle} for live ride downtime updates."
        )

    if previous_is_open is False and current_is_open is True:
        wait_time = ride.get("wait_time")
        wait_line = f"\n\nCurrent posted wait: {wait_time} min." if wait_time is not None else ""
        return (
            f"✅ {resort_tag} UPDATE\n\n"
            f"{ride_name} has reopened at {park_name}.{wait_line}\n\n"
            f"Follow {account_handle} for live ride operations updates."
        )

    return None


def x_client_from_env():
    required = [
        "X_CONSUMER_KEY",
        "X_CONSUMER_SECRET",
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET",
    ]
    if not all(os.getenv(key) for key in required):
        return None
    if tweepy is None:
        raise RuntimeError("tweepy is not installed but X posting was requested")

    return tweepy.Client(
        consumer_key=os.environ["X_CONSUMER_KEY"],
        consumer_secret=os.environ["X_CONSUMER_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def post_to_x(text: str) -> None:
    client = x_client_from_env()
    if client is None:
        print("DRY RUN / NO X SECRETS SET:")
        print(text)
        print("-" * 50)
        return
    client.create_tweet(text=text)
    print("Posted to X:")
    print(text)
    print("-" * 50)


def main() -> None:
    config = load_json(CONFIG_PATH, {})
    state: Dict[str, Any] = load_json(STATE_PATH, {})

    account_handle = config.get("account_handle", "@ParkSignals")
    post_settings = config.get("post_settings", {})
    dry_run = bool(post_settings.get("dry_run", True))
    max_posts = int(post_settings.get("max_posts_per_run", 3))

    alerts: List[str] = []

    for park in config.get("tracked_parks", []):
        resort_tag = park["resort_tag"]
        park_name = park["park_name"]
        park_id = park["queue_times_park_id"]
        major_rides = set(park.get("major_rides", []))

        rides = fetch_park_rides(park_id)
        print(f"Checked {len(rides)} rides for {park_name}")

        for ride in rides:
            ride_name = ride.get("name")
            if major_rides and ride_name not in major_rides:
                continue

            state_key = f"{park_id}:{ride['id']}"
            old_record = state.get(state_key)
            previous_is_open = old_record.get("is_open") if old_record else None
            current_is_open = ride.get("is_open")

            # First run: initialize state only. No alert.
            if old_record is None:
                state[state_key] = {
                    "park_name": park_name,
                    "resort_tag": resort_tag,
                    "ride_id": ride["id"],
                    "ride_name": ride_name,
                    "is_open": current_is_open,
                    "wait_time": ride.get("wait_time"),
                    "last_updated": ride.get("last_updated"),
                    "checked_at": utc_now_iso(),
                }
                continue

            alert = build_alert_text(
                resort_tag=resort_tag,
                park_name=park_name,
                ride=ride,
                previous_is_open=previous_is_open,
                account_handle=account_handle,
            )
            if alert:
                alerts.append(alert)

            state[state_key] = {
                "park_name": park_name,
                "resort_tag": resort_tag,
                "ride_id": ride["id"],
                "ride_name": ride_name,
                "is_open": current_is_open,
                "wait_time": ride.get("wait_time"),
                "last_updated": ride.get("last_updated"),
                "checked_at": utc_now_iso(),
            }

    save_json(STATE_PATH, state)

    if not alerts:
        print("No status-change alerts this run.")
        return

    print(f"Generated {len(alerts)} alert(s).")
    for alert in alerts[:max_posts]:
        if dry_run:
            print("DRY RUN:")
            print(alert)
            print("-" * 50)
        else:
            post_to_x(alert)


if __name__ == "__main__":
    main()
