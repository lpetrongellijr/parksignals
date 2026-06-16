import json
from pathlib import Path

import parksignals
import parksignals_analytics


ANALYTICS_HISTORY_FILE = "analytics_history.json"
ANALYTICS_SCHEMA_VERSION = 1


def load_history(path=ANALYTICS_HISTORY_FILE):
    try:
        with open(path, "r") as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        history = {}

    history.setdefault("schema_version", ANALYTICS_SCHEMA_VERSION)
    history.setdefault("first_observed_at", None)
    history.setdefault("last_observed_at", None)
    history.setdefault("runs_captured", 0)
    history.setdefault("days", {})
    return history


def save_history(history, path=ANALYTICS_HISTORY_FILE):
    with open(path, "w") as f:
        json.dump(history, f, indent=2, sort_keys=True)
        f.write("\n")


def local_date_key(observed_at, timezone_name=parksignals_analytics.PARK_ANALYTICS_TIMEZONE):
    return observed_at.astimezone(parksignals_analytics.ZoneInfo(timezone_name)).date().isoformat()


def blank_ride_record(ride_name):
    return {
        "ride_name": ride_name,
        "samples": 0,
        "open_samples": 0,
        "down_samples": 0,
        "planned_closure_samples": 0,
        "unknown_samples": 0,
        "wait_time_samples": 0,
        "wait_time_total": 0,
        "average_wait_time": None,
        "min_wait_time": None,
        "max_wait_time": None,
        "down_event_count": 0,
        "downtime_seconds": 0,
    }


def day_record(history, date_key):
    return history["days"].setdefault(
        date_key,
        {
            "date": date_key,
            "timezone": parksignals_analytics.PARK_ANALYTICS_TIMEZONE,
            "runs_captured": 0,
            "parks": {},
        },
    )


def park_day_record(day, park_key, park_name):
    return day["parks"].setdefault(
        park_key,
        {
            "park_name": park_name,
            "samples": 0,
            "rides": {},
        },
    )


def add_wait_sample(ride_record, wait_time):
    if not isinstance(wait_time, int):
        return
    ride_record["wait_time_samples"] += 1
    ride_record["wait_time_total"] += wait_time
    ride_record["average_wait_time"] = round(
        ride_record["wait_time_total"] / ride_record["wait_time_samples"],
        1,
    )
    if ride_record["min_wait_time"] is None or wait_time < ride_record["min_wait_time"]:
        ride_record["min_wait_time"] = wait_time
    if ride_record["max_wait_time"] is None or wait_time > ride_record["max_wait_time"]:
        ride_record["max_wait_time"] = wait_time


def add_status_sample(ride_record, status):
    ride_record["samples"] += 1
    if status == "open":
        ride_record["open_samples"] += 1
    elif status == "unavailable":
        ride_record["down_samples"] += 1
    elif status == "planned closure":
        ride_record["planned_closure_samples"] += 1
    else:
        ride_record["unknown_samples"] += 1


def update_samples(day, summaries):
    for summary in summaries:
        if summary.get("monitoring_suppressed"):
            continue
        park_key = summary.get("park_key")
        if not park_key:
            continue
        park = park_day_record(day, park_key, summary["park_name"])
        park["samples"] += 1
        rides = park["rides"]
        for ride in summary.get("ride_ids", []):
            ride_id = str(ride["id"])
            ride_record = rides.setdefault(ride_id, blank_ride_record(ride["name"]))
            ride_record["ride_name"] = ride["name"]
            add_status_sample(ride_record, ride.get("status"))
            add_wait_sample(ride_record, ride.get("wait_time"))

        for transition in summary.get("transitions", []):
            if transition.get("type") != "down":
                continue
            ride_id = str(transition["ride_id"])
            ride_record = rides.setdefault(
                ride_id,
                blank_ride_record(transition.get("ride_name") or ride_id),
            )
            ride_record["ride_name"] = transition.get("ride_name") or ride_record["ride_name"]
            ride_record["down_event_count"] += 1


def update_downtime_metrics(day, state, config, observed_at):
    day_start = parksignals_analytics.local_day_start(observed_at)
    for park_key, park_config in parksignals.enabled_park_configs(config):
        park_state = state.get(park_key, {})
        if not isinstance(park_state, dict):
            continue
        park = park_day_record(day, park_key, park_config["park_name"])
        for ride_id, ride_state in park_state.items():
            if not isinstance(ride_state, dict):
                continue
            metric = parksignals_analytics.analytics_ride_metric(
                park_key,
                park_config["park_name"],
                str(ride_id),
                ride_state,
                day_start,
                observed_at,
            )
            ride_record = park["rides"].setdefault(
                str(ride_id),
                blank_ride_record(metric["ride_name"]),
            )
            ride_record["ride_name"] = metric["ride_name"]
            ride_record["downtime_seconds"] = metric["downtime_seconds"]


def date_range_key(date_key, range_type):
    if range_type == "month":
        return date_key[:7]
    if range_type == "week":
        parsed = parksignals.parse_date(date_key)
        if parsed is None:
            return date_key
        week_start = parsed - parksignals.timedelta(days=parsed.weekday())
        return week_start.isoformat()
    return date_key


def build_rollup(history, range_type):
    rollup = {}
    for date_key, day in history.get("days", {}).items():
        bucket_key = date_range_key(date_key, range_type)
        bucket = rollup.setdefault(bucket_key, {"parks": {}})
        for park_key, park in day.get("parks", {}).items():
            bucket_park = bucket["parks"].setdefault(
                park_key,
                {"park_name": park["park_name"], "rides": {}},
            )
            for ride_id, ride in park.get("rides", {}).items():
                bucket_ride = bucket_park["rides"].setdefault(
                    ride_id,
                    {
                        "ride_name": ride["ride_name"],
                        "down_event_count": 0,
                        "downtime_seconds": 0,
                        "wait_time_samples": 0,
                        "wait_time_total": 0,
                        "average_wait_time": None,
                    },
                )
                bucket_ride["down_event_count"] += int(ride.get("down_event_count", 0) or 0)
                bucket_ride["downtime_seconds"] += int(ride.get("downtime_seconds", 0) or 0)
                bucket_ride["wait_time_samples"] += int(ride.get("wait_time_samples", 0) or 0)
                bucket_ride["wait_time_total"] += int(ride.get("wait_time_total", 0) or 0)
                if bucket_ride["wait_time_samples"]:
                    bucket_ride["average_wait_time"] = round(
                        bucket_ride["wait_time_total"] / bucket_ride["wait_time_samples"],
                        1,
                    )
    return rollup


def summarize_top_rides(history, date_key):
    day = history.get("days", {}).get(date_key, {})
    rows = []
    for park in day.get("parks", {}).values():
        for ride in park.get("rides", {}).values():
            rows.append({"park_name": park["park_name"], **ride})
    return sorted(
        rows,
        key=lambda item: (item.get("downtime_seconds", 0), item.get("down_event_count", 0)),
        reverse=True,
    )


def build_history_summary(history, observed_at):
    date_key = local_date_key(observed_at)
    lines = [f"ParkSignals data capture summary for {date_key}", ""]
    lines.append(f"Runs captured: {history.get('runs_captured', 0)}")
    lines.append(f"First observed: {history.get('first_observed_at') or 'n/a'}")
    lines.append(f"Last observed: {history.get('last_observed_at') or 'n/a'}")
    lines.append("")
    lines.append("Top downtime today:")
    rows = [row for row in summarize_top_rides(history, date_key) if row.get("downtime_seconds", 0) > 0]
    if not rows:
        lines.append("- No downtime captured yet")
    for row in rows[:10]:
        wait = row.get("average_wait_time")
        wait_text = "n/a" if wait is None else f"{wait} min avg wait"
        lines.append(
            f"- {row['ride_name']} ({row['park_name']}): "
            f"{parksignals.format_duration(row['downtime_seconds'])}, "
            f"{row.get('down_event_count', 0)} down events, {wait_text}"
        )
    return "\n".join(lines)


def write_history_summary(history, observed_at, output_dir):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with open(output_path / "data-capture-summary.txt", "w") as f:
        f.write(build_history_summary(history, observed_at))
        f.write("\n")
    with open(output_path / "data-capture-summary.json", "w") as f:
        json.dump(
            {
                "daily": history.get("days", {}).get(local_date_key(observed_at), {}),
                "weekly_rollups": build_rollup(history, "week"),
                "monthly_rollups": build_rollup(history, "month"),
            },
            f,
            indent=2,
            sort_keys=True,
        )
        f.write("\n")


def update_history(state, config, summaries, observed_at, path=ANALYTICS_HISTORY_FILE, output_dir="outputs"):
    history = load_history(path)
    observed_at_text = parksignals.isoformat(observed_at)
    if history.get("first_observed_at") is None:
        history["first_observed_at"] = observed_at_text
    history["last_observed_at"] = observed_at_text
    history["runs_captured"] = int(history.get("runs_captured", 0) or 0) + 1

    date_key = local_date_key(observed_at)
    day = day_record(history, date_key)
    day["runs_captured"] = int(day.get("runs_captured", 0) or 0) + 1
    day["last_observed_at"] = observed_at_text

    update_samples(day, summaries)
    update_downtime_metrics(day, state, config, observed_at)
    save_history(history, path)
    write_history_summary(history, observed_at, output_dir)
    return history
