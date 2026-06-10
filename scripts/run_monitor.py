from datetime import datetime, time
from zoneinfo import ZoneInfo

import parksignals


def parse_local_time(value):
    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute))


def is_time_in_window(current_time, opens_at, closes_at):
    if opens_at <= closes_at:
        return opens_at <= current_time < closes_at
    return current_time >= opens_at or current_time < closes_at


def monitoring_hours_status(park_config, observed_at):
    hours = park_config.get("monitoring_hours")
    if not hours or hours.get("enabled") is False:
        return True, None

    timezone_name = hours.get("timezone", "America/New_York")
    local_observed_at = observed_at.astimezone(ZoneInfo(timezone_name))
    opens_at = parse_local_time(hours["opens_at"])
    closes_at = parse_local_time(hours["closes_at"])
    if is_time_in_window(local_observed_at.time(), opens_at, closes_at):
        return True, None

    return False, (
        "outside configured monitoring hours "
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
    summaries = []

    for park_key, park_config in parksignals.enabled_park_configs(config):
        monitoring_allowed, reason = monitoring_hours_status(park_config, observed_at)
        if monitoring_allowed:
            summaries.append(parksignals.monitor_park(park_key, park_config, state, observed_at))
        else:
            summaries.append(build_suppressed_summary(park_key, park_config, observed_at, reason))

    pillar_summary = parksignals.collect_content_pillar_summary(state, config, observed_at)
    parksignals.save_state(state)
    parksignals.print_run_summary(summaries, observed_at)
    print_suppression_notes(summaries)
    parksignals.print_content_pillar_summary(pillar_summary, summaries)


if __name__ == "__main__":
    print(f"Running ParkSignals check at {datetime.now()}")
    run()
