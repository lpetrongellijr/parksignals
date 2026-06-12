import json
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import parksignals
import parksignals_analytics


PARK_HOURS_CACHE_FILE = "park_hours_cache.json"
LAST_RUN_SUMMARY_FILE = Path("outputs") / "last-run-summary.json"
DEFAULT_PARK_TIMEZONE = "America/New_York"
OFFICIAL_HOURS_UNAVAILABLE_REASON = (
    "official park hours unavailable; monitoring suppressed so generic configured hours are not used"
)


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

    timezone_name = park_hours.get("timezone") or cache.get("timezone", DEFAULT_PARK_TIMEZONE)
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
        "timezone": hours.get("timezone", DEFAULT_PARK_TIMEZONE),
        "opens_at": hours["opens_at"],
        "closes_at": hours["closes_at"],
    }


def resolved_monitoring_hours(park_key, park_config, observed_at, cache):
    return official_hours_for_park(park_key, observed_at, cache)


def monitoring_hours_status(park_key, park_config, observed_at, cache=None):
    cache = cache or {"parks": {}}
    hours = resolved_monitoring_hours(park_key, park_config, observed_at, cache)
    if not hours:
        return False, OFFICIAL_HOURS_UNAVAILABLE_REASON

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


def park_status_for_park(park_key, park_config, observed_at, cache):
    hours = resolved_monitoring_hours(park_key, park_config, observed_at, cache)
    monitoring_allowed, reason = monitoring_hours_status(
        park_key,
        park_config,
        observed_at,
        cache,
    )
    timezone_name = hours["timezone"] if hours else DEFAULT_PARK_TIMEZONE
    local_observed_at = observed_at.astimezone(ZoneInfo(timezone_name))

    return {
        "park_key": park_key,
        "park_name": park_config["park_name"],
        "operating_status": "open" if monitoring_allowed else "closed",
        "monitoring_allowed": monitoring_allowed,
        "reason": reason,
        "observed_at_local": local_observed_at.isoformat(timespec="seconds"),
        "hours": hours,
        "configured_fallback_hours": configured_hours_for_park(park_config),
    }


def build_suppressed_summary(park_key, park_config, observed_at, reason):
    major_rides = set(park_config.get("major_rides", []))
    rides = parksignals.fetch_rides(park_config)
    matched_ride_names = set()
    summary = {
        "park_key": park_key,
        "park_name": park_config["park_name"],
        "park_operating_status": "closed",
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
    missing_official_hours = []
    for park_key, park_config in parksignals.enabled_park_configs(config):
        hours = resolved_monitoring_hours(park_key, park_config, observed_at, cache)
        if not hours:
            fallback = configured_hours_for_park(park_config)
            fallback_text = "no configured fallback present"
            if fallback:
                fallback_text = (
                    f"configured fallback ignored ({fallback['opens_at']}-{fallback['closes_at']} "
                    f"{fallback['timezone']})"
                )
            print(f"- {park_config['park_name']}: official hours unavailable; {fallback_text}")
            missing_official_hours.append(park_config["park_name"])
            continue
        print(
            f"- {park_config['park_name']}: {hours['source']} "
            f"{hours['opens_at']}-{hours['closes_at']} {hours['timezone']}"
        )

    if missing_official_hours:
        print("")
        print("Park hours missing notice")
        print(
            "Official park hours were not available for: "
            + ", ".join(missing_official_hours)
        )
        print("No generic fallback hours were used; monitoring is suppressed for those parks.")
        if cache.get("last_fetch_status") and cache.get("last_fetch_status") != "ok":
            print(f"Last official-hours fetch status: {cache['last_fetch_status']}")
        if cache.get("last_fetch_error"):
            print(f"Last official-hours fetch error: {cache['last_fetch_error']}")


def print_park_status_notes(park_statuses):
    print("")
    print("Park operating status")
    for status in park_statuses:
        hours = status.get("hours") or {}
        hours_text = "official hours unavailable"
        if hours:
            hours_text = f"{hours['opens_at']}-{hours['closes_at']} {hours['timezone']} ({hours['source']})"
        print(
            f"- {status['park_name']}: {status['operating_status']} "
            f"for monitoring; {hours_text}"
        )
        if status.get("reason"):
            print(f"  {status['reason']}")


def print_suppression_notes(summaries):
    suppressed = [summary for summary in summaries if summary.get("monitoring_suppressed")]
    if not suppressed:
        return

    print("")
    print("Downtime tracking suppressed")
    for summary in suppressed:
        print(f"- {summary['park_name']}: {summary['suppression_reason']}")


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
            multi_reopenings.append({"park_name": summary["park_name"], "rides": reopened})

    if multi_reopenings:
        print("Multi-ride reopening candidates:")
        for alert in multi_reopenings:
            print(f"  {alert['park_name']}:")
            for ride_name in alert["rides"][:5]:
                print(f"    - {ride_name}")
    else:
        print("Multi-ride reopening candidates: none this run")

    print("")
    print("2. Daily summary inputs:")
    if pillar_summary["daily_top"]:
        print("  Most downtime today:")
        for index, metric in enumerate(pillar_summary["daily_top"], start=1):
            print(
                f"  {index}. {metric['ride_name']} "
                f"({metric['park_name']}) - "
                f"{parksignals.format_duration(metric['downtime_seconds'])}"
            )
    else:
        print("  Most downtime today: no downtime recorded yet")

    stable_park = pillar_summary["stable_park"]
    if stable_park:
        print(f"  Most stable park today: {stable_park[0]}")

    print("")
    print("3. Monthly reliability inputs:")
    if not pillar_summary.get("monthly_reliability_ready", True):
        print(
            "  Waiting for "
            f"{pillar_summary.get('monthly_reliability_min_days', parksignals.ANALYTICS_LOOKBACK_DAYS)} "
            f"days of history; current history is {pillar_summary.get('data_age_days', 0)} days."
        )
    elif pillar_summary.get("monthly_top"):
        for index, metric in enumerate(pillar_summary["monthly_top"], start=1):
            print(
                f"  {index}. {metric['ride_name']} "
                f"({metric['park_name']}) - "
                f"{parksignals.format_duration(metric['downtime_seconds'])}"
            )
    else:
        print("  No completed downtime history yet")

    print("")
    print("4. Insight and projection inputs:")
    if not pillar_summary.get("trend_insights_ready", True):
        print(
            "  Elevated downtime frequency: waiting for "
            f"{pillar_summary.get('trend_insights_min_days', parksignals.TREND_LOOKBACK_DAYS)} "
            f"days of history; current history is {pillar_summary.get('data_age_days', 0)} days."
        )
    elif pillar_summary["elevated_trends"]:
        print("  Elevated downtime frequency:")
        for metric in pillar_summary["elevated_trends"][:5]:
            print(
                f"  - {metric['ride_name']} ({metric['park_name']}): "
                f"{metric['event_count']} events in {parksignals.TREND_LOOKBACK_DAYS} days"
            )
    else:
        print("  Elevated downtime frequency: no trend candidates yet")

    if pillar_summary["active_projections"]:
        print("  Active downtime projections:")
        for projection in pillar_summary["active_projections"][:5]:
            print(
                f"  - {projection['ride_name']} ({projection['park_name']}): "
                f"currently down {parksignals.format_duration(projection['current_down_seconds'])}; "
                f"historical average {parksignals.format_duration(projection['projected_total_seconds'])}"
            )
    else:
        print("  Active downtime projections: no active rides with history yet")


def write_last_run_summary(observed_at, summaries, pillar_summary, hours_cache, park_statuses):
    LAST_RUN_SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "observed_at": parksignals.isoformat(observed_at),
        "posting_connected": False,
        "park_statuses": park_statuses,
        "run_summaries": summaries,
        "content_pillar_summary": pillar_summary,
        "park_hours_cache_status": hours_cache.get("last_fetch_status"),
    }
    with open(LAST_RUN_SUMMARY_FILE, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def run():
    config = parksignals.load_config()
    state = parksignals.load_state()
    observed_at = parksignals.utc_now()
    hours_cache = load_park_hours_cache()
    summaries = []
    park_statuses = []

    for park_key, park_config in parksignals.enabled_park_configs(config):
        park_status = park_status_for_park(park_key, park_config, observed_at, hours_cache)
        park_statuses.append(park_status)
        if park_status["monitoring_allowed"]:
            summary = parksignals.monitor_park(park_key, park_config, state, observed_at)
            summary["park_key"] = park_key
            summary["park_operating_status"] = "open"
            summary["monitoring_suppressed"] = False
            summaries.append(summary)
        else:
            summaries.append(
                build_suppressed_summary(
                    park_key,
                    park_config,
                    observed_at,
                    park_status["reason"],
                )
            )

    pillar_summary = parksignals_analytics.collect_content_pillar_summary(
        state,
        config,
        observed_at,
    )
    parksignals.save_state(state)
    write_last_run_summary(observed_at, summaries, pillar_summary, hours_cache, park_statuses)
    parksignals.print_run_summary(summaries, observed_at)
    print_hours_source_notes(config, observed_at, hours_cache)
    print_park_status_notes(park_statuses)
    print_suppression_notes(summaries)
    print_content_pillar_summary(pillar_summary, summaries)


if __name__ == "__main__":
    print(f"Running ParkSignals check at {datetime.now()}")
    run()
