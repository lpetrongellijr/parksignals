import json
import os
from datetime import datetime, time, timedelta, timezone

import requests


CONFIG_FILE = "parks_config.json"
STATE_FILE = "state.json"
DEFAULT_PARK_KEY = "magic_kingdom"
PARKS_ENV_VAR = "PARKSIGNALS_PARKS"
MAX_DOWNTIME_EVENTS_PER_RIDE = 120
DOWNTIME_EVENT_RETENTION_DAYS = 45
ANALYTICS_LOOKBACK_DAYS = 30
TREND_LOOKBACK_DAYS = 7


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


def events_in_window(ride_state, window_start, window_end):
    events = []
    for event in ride_state.get("downtime_events", []):
        duration = overlap_seconds(
            event.get("down_at"),
            event.get("reopened_at"),
            window_start,
            window_end,
        )
        if duration > 0:
            events.append({
                "down_at": event.get("down_at"),
                "reopened_at": event.get("reopened_at"),
                "duration_seconds": duration,
            })

    if ride_state.get("is_open") is False:
        duration = overlap_seconds(
            ride_state.get("down_since"),
            None,
            window_start,
            window_end,
        )
        if duration > 0:
            events.append({
                "down_at": ride_state.get("down_since"),
                "reopened_at": None,
                "duration_seconds": duration,
            })

    return events


def downtime_seconds_in_window(ride_state, window_start, window_end):
    return sum(
        event["duration_seconds"]
        for event in events_in_window(ride_state, window_start, window_end)
    )


def average_completed_downtime_seconds(ride_state, window_start, window_end):
    durations = []
    for event in ride_state.get("downtime_events", []):
        reopened_at = parse_timestamp(event.get("reopened_at"))
        if reopened_at is None or reopened_at < window_start or reopened_at > window_end:
            continue
        duration = int(event.get("duration_seconds") or 0)
        if duration > 0:
            durations.append(duration)

    if not durations:
        return None

    return int(sum(durations) / len(durations))


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


def ride_metric(park_key, park_name, ride_id, ride_state, window_start, window_end):
    return {
        "park_key": park_key,
        "park_name": park_name,
        "ride_id": ride_id,
        "ride_name": ride_state.get("name") or ride_id,
        "is_open": ride_state.get("is_open"),
        "downtime_seconds": downtime_seconds_in_window(
            ride_state,
            window_start,
            window_end,
        ),
        "event_count": len(events_in_window(ride_state, window_start, window_end)),
        "average_completed_downtime_seconds": average_completed_downtime_seconds(
            ride_state,
            window_start,
            window_end,
        ),
        "current_down_seconds": int(ride_state.get("current_down_seconds", 0) or 0),
    }


def top_downtime(metrics, limit=3):
    return [
        metric
        for metric in sorted(
            metrics,
            key=lambda item: item["downtime_seconds"],
            reverse=True,
        )
        if metric["downtime_seconds"] > 0
    ][:limit]


def collect_content_pillar_summary(state, config, observed_at):
    day_start = datetime.combine(observed_at.date(), time.min, tzinfo=timezone.utc)
    thirty_day_start = observed_at - timedelta(days=ANALYTICS_LOOKBACK_DAYS)
    trend_start = observed_at - timedelta(days=TREND_LOOKBACK_DAYS)
    parks = config.get("parks", {})
    daily_metrics = []
    thirty_day_metrics = []
    trend_metrics = []
    park_daily_totals = {}

    for park_key, park_config in enabled_park_configs(config):
        park_name = park_config["park_name"]
        park_state = state.get(park_key, {})
        park_daily_totals[park_name] = 0

        for ride_id, ride_state in park_state.items():
            if not isinstance(ride_state, dict):
                continue

            prune_downtime_events(ride_state, observed_at)
            daily_metric = ride_metric(
                park_key,
                park_name,
                ride_id,
                ride_state,
                day_start,
                observed_at,
            )
            monthly_metric = ride_metric(
                park_key,
                park_name,
                ride_id,
                ride_state,
                thirty_day_start,
                observed_at,
            )
            trend_metric = ride_metric(
                park_key,
                park_name,
                ride_id,
                ride_state,
                trend_start,
                observed_at,
            )

            daily_metrics.append(daily_metric)
            thirty_day_metrics.append(monthly_metric)
            trend_metrics.append(trend_metric)
            park_daily_totals[park_name] += daily_metric["downtime_seconds"]

    stable_park = None
    if park_daily_totals:
        stable_park = min(park_daily_totals.items(), key=lambda item: item[1])

    active_multi_ride_alerts = []
    for park_key, park_config in parks.items():
        if not park_config.get("enabled", False):
            continue
        unavailable = [
            ride_state.get("name") or ride_id
            for ride_id, ride_state in state.get(park_key, {}).items()
            if isinstance(ride_state, dict) and ride_state.get("is_open") is False
        ]
        if len(unavailable) >= 2:
            active_multi_ride_alerts.append({
                "park_name": park_config["park_name"],
                "rides": unavailable,
            })

    elevated_trends = [
        metric
        for metric in trend_metrics
        if metric["event_count"] >= 2
    ]
    active_projections = []
    for metric in thirty_day_metrics:
        average_duration = metric["average_completed_downtime_seconds"]
        if (
            metric["is_open"] is False
            and average_duration
            and metric["current_down_seconds"] > 0
        ):
            active_projections.append({
                **metric,
                "projected_total_seconds": average_duration,
                "projected_remaining_seconds": max(
                    0,
                    average_duration - metric["current_down_seconds"],
                ),
            })

    return {
        "daily_top": top_downtime(daily_metrics),
        "thirty_day_top": top_downtime(thirty_day_metrics),
        "stable_park": stable_park,
        "active_multi_ride_alerts": active_multi_ride_alerts,
        "elevated_trends": elevated_trends,
        "active_projections": active_projections,
    }


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


def print_content_pillar_summary(pillar_summary, run_summaries):
    print("")
    print("Content pillar readiness")
    print("1. Real-time single ride closures/reopenings: supported")

    multi_closures = pillar_summary["active_multi_ride_alerts"]
    if multi_closures:
        print("1C. Multi-ride closure candidates:")
        for alert in multi_closures:
            print(f"  {alert['park_name']}:")
            for ride_name in alert["rides"][:5]:
                print(f"    - {ride_name}")
    else:
        print("1C. Multi-ride closure candidates: none active")

    multi_reopenings = []
    for summary in run_summaries:
        reopened = [
            transition["ride_name"]
            for transition in summary["transitions"]
            if transition["type"] == "reopened"
        ]
        if len(reopened) >= 2:
            multi_reopenings.append({
                "park_name": summary["park_name"],
                "rides": reopened,
            })

    if multi_reopenings:
        print("Multi-ride reopening candidates:")
        for alert in multi_reopenings:
            print(f"  {alert['park_name']}:")
            for ride_name in alert["rides"][:5]:
                print(f"    - {ride_name}")
    else:
        print("Multi-ride reopening candidates: none this run")

    print("")
    print("2. Daily operations summary inputs:")
    if pillar_summary["daily_top"]:
        print("  Most downtime today:")
        for index, metric in enumerate(pillar_summary["daily_top"], start=1):
            print(
                f"  {index}. {metric['ride_name']} "
                f"({metric['park_name']}) — "
                f"{format_duration(metric['downtime_seconds'])}"
            )
    else:
        print("  Most downtime today: no downtime recorded yet")

    stable_park = pillar_summary["stable_park"]
    if stable_park:
        print(f"  Most stable park today: {stable_park[0]}")

    print("")
    print("3. 30-day reliability analytics inputs:")
    if pillar_summary["thirty_day_top"]:
        for index, metric in enumerate(pillar_summary["thirty_day_top"], start=1):
            print(
                f"  {index}. {metric['ride_name']} "
                f"({metric['park_name']}) — "
                f"{format_duration(metric['downtime_seconds'])}"
            )
    else:
        print("  No completed downtime history yet")

    print("")
    print("4. Insight and projection inputs:")
    if pillar_summary["elevated_trends"]:
        print("  Elevated downtime frequency:")
        for metric in pillar_summary["elevated_trends"][:5]:
            print(
                f"  - {metric['ride_name']} ({metric['park_name']}): "
                f"{metric['event_count']} events in {TREND_LOOKBACK_DAYS} days"
            )
    else:
        print("  Elevated downtime frequency: no trend candidates yet")

    if pillar_summary["active_projections"]:
        print("  Active downtime projections:")
        for projection in pillar_summary["active_projections"][:5]:
            print(
                f"  - {projection['ride_name']} ({projection['park_name']}): "
                f"currently down {format_duration(projection['current_down_seconds'])}; "
                f"historical average {format_duration(projection['projected_total_seconds'])}"
            )
    else:
        print("  Active downtime projections: no active rides with history yet")


def main():
    config = load_config()
    state = load_state()
    observed_at = utc_now()
    summaries = []

    for park_key, park_config in enabled_park_configs(config):
        summaries.append(monitor_park(park_key, park_config, state, observed_at))

    pillar_summary = collect_content_pillar_summary(state, config, observed_at)
    save_state(state)
    print_run_summary(summaries, observed_at)
    print_content_pillar_summary(pillar_summary, summaries)


if __name__ == "__main__":
    print(f"Running ParkSignals check at {datetime.now()}")
    main()
