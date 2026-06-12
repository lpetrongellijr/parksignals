import argparse
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import parksignals
import parksignals_analytics


PARK_TIMEZONE = "America/New_York"
MAX_POST_CHARACTERS = 280
POST_RANKING_LIMIT = 3
POST_DISPLAY_REPLACEMENTS = {
    "Walt Disney World": "Disney World",
    "WDW": "Disney World",
    "Universal Orlando Resort": "Universal Orlando",
    "UOR": "Universal Orlando",
    "Universal Hollywood Resort": "Universal Hollywood",
    "UHR": "Universal Hollywood",
    "DL": "Disneyland",
    "Expedition Everest - Legend of the Forbidden Mountain": "Expedition Everest",
    "The Twilight Zone™ Tower of Terror": "The Twilight Zone Tower of Terror",
    "Star Tours - The Adventures Continue": "Star Tours",
    "Journey Into Imagination With Figment": "Journey Into Imagination",
    "Gran Fiesta Tour Starring The Three Caballeros": "Gran Fiesta Tour",
    "Tomorrowland Transit Authority PeopleMover": "PeopleMover",
    "Rock ’n’ Roller Coaster Starring The Muppets": "Rock ’n’ Roller Coaster",
    "Walt Disney’s Carousel of Progress": "Carousel of Progress",
    "Walt Disney's Carousel of Progress": "Carousel of Progress",
}
HASHTAG_REPLACEMENTS = {
    "#WaltDisneyWorld": "#DisneyWorld",
    "#WDW": "#DisneyWorld",
    "#UniversalOrlandoResort": "#UniversalOrlando",
    "#UOR": "#UniversalOrlando",
    "#UniversalHollywoodResort": "#UniversalHollywood",
    "#UHR": "#UniversalHollywood",
    "#DL": "#Disneyland",
    "#ExpeditionEverestLegendoftheForbiddenMountain": "#ExpeditionEverest",
    "#StarToursTheAdventuresContinue": "#StarTours",
    "#JourneyIntoImaginationWithFigment": "#JourneyIntoImagination",
    "#GranFiestaTourStarringTheThreeCaballeros": "#GranFiestaTour",
    "#TomorrowlandTransitAuthorityPeopleMover": "#PeopleMover",
    "#RocknRollerCoasterStarringTheMuppets": "#RocknRollerCoaster",
    "#WaltDisneysCarouselofProgress": "#CarouselofProgress",
}
REMOVED_HASHTAGS = {
    "#down",
    "#reopened",
    "#opsalert",
    "#dailyops",
    "#analytics",
    "#aiinsight",
    "#operations",
}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
        if not content.endswith("\n"):
            f.write("\n")


def load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def normalize_post_display_text(text):
    normalized = text
    for source, replacement in POST_DISPLAY_REPLACEMENTS.items():
        normalized = normalized.replace(source, replacement)
    return normalized


def display_resort_name(resort_name):
    return normalize_post_display_text(resort_name)


def normalize_hashtag(hashtag):
    return HASHTAG_REPLACEMENTS.get(hashtag, hashtag)


def normalize_post_hashtags(post_text):
    normalized_lines = []
    for line in post_text.splitlines():
        stripped = line.strip()
        if is_hashtag_line(stripped):
            hashtag = normalize_hashtag(stripped)
            if hashtag.lower() in REMOVED_HASHTAGS:
                continue
            normalized_lines.append(hashtag)
        else:
            normalized_lines.append(line)
    return "\n".join(trim_blank_edges(normalized_lines))


def enabled_park_lookup(config):
    lookup = {}
    for park_key, park_config in parksignals.enabled_park_configs(config):
        lookup[park_key] = park_config
        lookup[park_config["park_name"]] = park_config
    return lookup


def tags_for_park(park_config, extras=None):
    extras = extras or []
    resort_hashtag = park_config.get(
        "resort_hashtag",
        parksignals.hashtag(park_config["resort_name"])[1:],
    )
    park_hashtag = park_config.get(
        "park_hashtag",
        parksignals.hashtag(park_config["park_name"])[1:],
    )
    tags = [normalize_hashtag(f"#{resort_hashtag}"), f"#{park_hashtag}"]
    tags.extend(normalize_hashtag(tag) for tag in extras)
    return "\n".join(tag for tag in tags if tag.lower() not in REMOVED_HASHTAGS)


def is_hashtag_line(line):
    stripped = line.strip()
    return stripped.startswith("#") and " " not in stripped and len(stripped) > 1


def trim_blank_edges(lines):
    trimmed = list(lines)
    while trimmed and trimmed[0] == "":
        trimmed.pop(0)
    while trimmed and trimmed[-1] == "":
        trimmed.pop()
    return trimmed


def trim_post_hashtags(post_text, max_characters=MAX_POST_CHARACTERS):
    lines = post_text.splitlines()
    hashtag_indices = [index for index, line in enumerate(lines) if is_hashtag_line(line)]
    if len(post_text) <= max_characters or len(hashtag_indices) <= 1:
        return post_text

    protected_hashtag_index = hashtag_indices[0]
    removable_indices = [index for index in hashtag_indices if index != protected_hashtag_index]
    remaining_lines = list(lines)

    for index in reversed(removable_indices):
        remaining_lines.pop(index)
        candidate = "\n".join(trim_blank_edges(remaining_lines))
        if len(candidate) <= max_characters:
            return candidate

    return "\n".join(trim_blank_edges(remaining_lines))


def add_priority_hashtags(lines, hashtags, max_characters=MAX_POST_CHARACTERS):
    body = "\n".join(lines).rstrip()
    return trim_post_hashtags(body + "\n\n" + "\n".join(hashtags), max_characters)


def metric_line(metric, include_park=True):
    name = metric["ride_name"]
    if include_park:
        name = f"{name} ({metric['park_name']})"
    return f"{name} - {parksignals.format_duration(metric['downtime_seconds'])}"


def format_rankings(title, rankings, limit=None):
    lines = [title]
    if not rankings:
        lines.append("No downtime recorded yet")
        return lines

    limited_rankings = rankings[:limit] if limit else rankings
    for index, metric in enumerate(limited_rankings, start=1):
        lines.append(f"{index}. {metric_line(metric)}")
    return lines


def monthly_rankings(summary):
    if not summary.get("monthly_reliability_ready", True):
        return []
    return summary.get("monthly_top") or summary.get("thirty_day_top", [])


def analytics_hold_message(summary, readiness_key, min_days_key):
    if summary.get(readiness_key, True):
        return None
    data_age_days = summary.get("data_age_days", 0)
    min_days = summary.get(min_days_key, 0)
    return f"Waiting for {min_days} days of history; current history is {data_age_days} days."


def build_daily_summary(summary):
    return "\n".join(
        format_rankings(
            "Daily downtime summary",
            summary["daily_top"],
            limit=POST_RANKING_LIMIT,
        )
    )


def local_date_label(observed_at):
    parsed = parksignals.parse_timestamp(observed_at)
    if parsed is None:
        return "today"
    return parsed.astimezone(ZoneInfo(PARK_TIMEZONE)).strftime("%B %-d, %Y")


def build_wdw_daily_post(summary, observed_at):
    lines = [
        "PARKSIGNALS // Disney World",
        "",
        f"Disney World Summary - {local_date_label(observed_at)}",
        "",
        "Most downtime:",
    ]
    if summary["daily_top"]:
        for index, metric in enumerate(summary["daily_top"][:POST_RANKING_LIMIT], start=1):
            lines.append(f"{index}. {metric_line(metric)}")
    else:
        lines.append("No downtime recorded yet")

    return add_priority_hashtags(lines, ["#DisneyWorld"])


def build_thirty_day_post(summary):
    rankings = monthly_rankings(summary)
    label = summary.get("monthly_window_label") or "Monthly"
    lines = [
        "PARKSIGNALS // Disney World",
        "",
        f"Disney World Reliability - {label}",
        "",
    ]
    if rankings:
        for index, metric in enumerate(rankings[:POST_RANKING_LIMIT], start=1):
            lines.append(f"{index}. {metric_line(metric)}")
    else:
        lines.append("No completed downtime history yet")

    lines.extend(["", "#DisneyWorld"])
    return "\n".join(lines)


def build_multi_ride_closure_post(alert, park_lookup):
    park_config = park_lookup.get(alert["park_name"])
    resort_name = display_resort_name(park_config["resort_name"]) if park_config else "Disney World"
    lines = [f"PARKSIGNALS // {resort_name}", ""]
    lines.append(f"ALERT: {alert['park_name']}")
    lines.extend(["", "Currently unavailable:"])
    for ride_name in alert["rides"][:5]:
        lines.append(f"- {ride_name}")
    if park_config:
        lines.extend(["", tags_for_park(park_config)])
    return "\n".join(lines)


def build_multi_ride_reopening_post(alert, park_lookup):
    park_config = park_lookup.get(alert["park_name"])
    resort_name = display_resort_name(park_config["resort_name"]) if park_config else "Disney World"
    lines = [f"PARKSIGNALS // {resort_name}", ""]
    lines.append(f"UPDATE: {alert['park_name']}")
    lines.extend(["", "Multiple attractions have reopened:"])
    for ride_name in alert["rides"][:5]:
        lines.append(f"- {ride_name}")
    if park_config:
        lines.extend(["", tags_for_park(park_config)])
    return "\n".join(lines)


def build_trend_post(metric, park_lookup):
    park_config = park_lookup.get(metric["park_key"]) or park_lookup.get(metric["park_name"])
    resort_name = display_resort_name(park_config["resort_name"]) if park_config else "Disney World"
    lines = [
        f"PARKSIGNALS // {resort_name}",
        "",
        f"{metric['ride_name']} has experienced elevated downtime frequency over the past 7 days.",
        "",
    ]
    if park_config:
        lines.append(tags_for_park(park_config, [parksignals.ride_hashtag(metric["ride_name"])]))
    return "\n".join(lines)


def build_projection_post(metric, park_lookup):
    park_config = park_lookup.get(metric["park_key"]) or park_lookup.get(metric["park_name"])
    resort_name = display_resort_name(park_config["resort_name"]) if park_config else "Disney World"
    lines = [
        f"PARKSIGNALS // {resort_name}",
        "",
        f"Elevated operational disruption risk detected at {metric['park_name']} based on historical downtime patterns.",
        "",
        f"{metric['ride_name']} is currently down {parksignals.format_duration(metric['current_down_seconds'])}.",
        f"Historical average: {parksignals.format_duration(metric['projected_total_seconds'])}.",
        "",
    ]
    if park_config:
        lines.append(tags_for_park(park_config))
    return "\n".join(lines)


def ride_lookup_for_summary(summary):
    return {
        ride["id"]: ride
        for ride in summary.get("ride_ids", [])
    }


def with_trimmed_preview(candidate):
    candidate["preview_text"] = trim_post_hashtags(
        normalize_post_hashtags(normalize_post_display_text(candidate["preview_text"]))
    )
    return candidate


def build_single_ride_candidates(last_run, park_lookup):
    closures = []
    reopenings = []
    for run_summary in last_run.get("run_summaries", []):
        park_config = park_lookup.get(run_summary.get("park_key")) or park_lookup.get(run_summary["park_name"])
        if not park_config:
            continue
        rides_by_id = ride_lookup_for_summary(run_summary)
        for transition in run_summary.get("transitions", []):
            ride = rides_by_id.get(transition["ride_id"], {})
            ride_payload = {
                "id": transition["ride_id"],
                "name": transition["ride_name"],
                "wait_time": ride.get("wait_time"),
            }
            candidate = with_trimmed_preview({
                "pillar": "real_time_alert",
                "type": transition["type"],
                "park_name": run_summary["park_name"],
                "ride_id": transition["ride_id"],
                "ride_name": transition["ride_name"],
                "preview_text": parksignals.build_post(
                    park_config,
                    ride_payload,
                    reopened=transition["type"] == "reopened",
                ),
            })
            if transition["type"] == "reopened":
                reopenings.append(candidate)
            else:
                closures.append(candidate)
    return closures, reopenings


def build_multi_ride_reopenings(last_run):
    alerts = []
    for run_summary in last_run.get("run_summaries", []):
        reopened = [
            transition["ride_name"]
            for transition in run_summary.get("transitions", [])
            if transition["type"] == "reopened"
        ]
        if len(reopened) >= 2:
            alerts.append({"park_name": run_summary["park_name"], "rides": reopened})
    return alerts


def build_post_candidates(summary, config, last_run, observed_at):
    park_lookup = enabled_park_lookup(config)
    single_closures, single_reopenings = build_single_ride_candidates(last_run, park_lookup)
    multi_reopenings = build_multi_ride_reopenings(last_run)
    reliability_rankings = monthly_rankings(summary)
    monthly_ready = summary.get("monthly_reliability_ready", True)
    trends_ready = summary.get("trend_insights_ready", True)

    multi_closures = [
        with_trimmed_preview({
            "pillar": "real_time_alert",
            "type": "multi_ride_closure",
            **alert,
            "preview_text": build_multi_ride_closure_post(alert, park_lookup),
        })
        for alert in summary["active_multi_ride_alerts"]
    ]
    multi_reopening_candidates = [
        with_trimmed_preview({
            "pillar": "real_time_alert",
            "type": "multi_ride_reopening",
            **alert,
            "preview_text": build_multi_ride_reopening_post(alert, park_lookup),
        })
        for alert in multi_reopenings
    ]
    daily_summary = with_trimmed_preview({
        "pillar": "daily_operations_summary",
        "type": "wdw_daily_summary",
        "preview_text": build_wdw_daily_post(summary, observed_at),
        "metrics": summary["daily_top"][:POST_RANKING_LIMIT],
    })
    monthly_reliability = []
    if monthly_ready:
        monthly_reliability = [with_trimmed_preview({
            "pillar": "reliability_analytics",
            "type": "wdw_monthly_reliability",
            "preview_text": build_thirty_day_post(summary),
            "metrics": reliability_rankings[:POST_RANKING_LIMIT],
        })]
    trend_candidates = []
    if trends_ready:
        trend_candidates = [
            with_trimmed_preview({
                "pillar": "insights_predictions",
                "type": "trend_detection",
                "metric": metric,
                "preview_text": build_trend_post(metric, park_lookup),
            })
            for metric in summary["elevated_trends"][:5]
        ]
    projection_candidates = [
        with_trimmed_preview({
            "pillar": "insights_predictions",
            "type": "active_projection",
            "metric": metric,
            "preview_text": build_projection_post(metric, park_lookup),
        })
        for metric in summary["active_projections"][:5]
    ]

    return {
        "posting_connected": False,
        "observed_at": observed_at,
        "single_ride_closures": single_closures,
        "single_ride_reopenings": single_reopenings,
        "multi_ride_closures": multi_closures,
        "multi_ride_reopenings": multi_reopening_candidates,
        "daily_summaries": [daily_summary],
        "monthly_reliability_rankings": monthly_reliability,
        "thirty_day_rankings": monthly_reliability,
        "insights": {
            "elevated_trends": trend_candidates,
            "active_projections": projection_candidates,
        },
    }


def build_post_previews(candidates):
    reliability_candidates = candidates.get("monthly_reliability_rankings") or candidates["thirty_day_rankings"]
    sections = [
        ("Single Ride Closures", candidates["single_ride_closures"]),
        ("Single Ride Reopenings", candidates["single_ride_reopenings"]),
        ("Multi-Ride Closures", candidates["multi_ride_closures"]),
        ("Multi-Ride Reopenings", candidates["multi_ride_reopenings"]),
        ("Daily Summaries", candidates["daily_summaries"]),
        ("Monthly Reliability", reliability_candidates),
        ("Trend Insights", candidates["insights"]["elevated_trends"]),
        ("Projection Insights", candidates["insights"]["active_projections"]),
    ]
    lines = ["ParkSignals post previews", "Posting connected: false"]
    for title, items in sections:
        lines.extend(["", "=" * len(title), title, "=" * len(title)])
        if not items:
            lines.append("No candidates right now.")
            continue
        for index, item in enumerate(items, start=1):
            lines.extend(["", f"Candidate {index}", "-" * 11, item["preview_text"]])
    return "\n".join(lines)


def build_readiness_summary(summary, candidates):
    reliability_rankings = monthly_rankings(summary)
    reliability_candidates = candidates.get("monthly_reliability_rankings") or candidates["thirty_day_rankings"]
    trend_hold = analytics_hold_message(summary, "trend_insights_ready", "trend_insights_min_days")
    monthly_hold = analytics_hold_message(summary, "monthly_reliability_ready", "monthly_reliability_min_days")
    lines = ["Content pillar readiness"]
    lines.append(
        "Single ride closure/reopen previews: "
        + str(len(candidates["single_ride_closures"]) + len(candidates["single_ride_reopenings"]))
        + " current-run candidates"
    )
    lines.append(
        "Multi-ride closure/reopening previews: "
        + str(len(candidates["multi_ride_closures"]) + len(candidates["multi_ride_reopenings"]))
        + " candidates"
    )
    lines.extend(format_rankings("Daily summary inputs", summary["daily_top"]))
    if monthly_hold:
        lines.append("Monthly reliability inputs")
        lines.append(monthly_hold)
    else:
        lines.extend(format_rankings("Monthly reliability inputs", reliability_rankings))
    lines.append(f"Monthly reliability preview candidates: {len(reliability_candidates)}")
    if trend_hold:
        lines.append(f"Trend preview candidates: 0 ({trend_hold})")
    else:
        lines.append(f"Trend preview candidates: {len(candidates['insights']['elevated_trends'])}")
    lines.append(f"Projection preview candidates: {len(candidates['insights']['active_projections'])}")
    lines.append("Posting connected: false")
    return "\n".join(lines)


def build_park_status_text(park_statuses):
    lines = ["Park operating status"]
    if not park_statuses:
        lines.append("No park status was recorded for this run.")
        return "\n".join(lines)

    for status in park_statuses:
        hours = status.get("hours") or {}
        hours_text = "official hours unavailable"
        if hours:
            hours_text = f"{hours['opens_at']}-{hours['closes_at']} {hours['timezone']} ({hours['source']})"
        lines.append(f"- {status['park_name']}: {status['operating_status']} for monitoring; {hours_text}")
        if status.get("reason"):
            lines.append(f"  {status['reason']}")
    return "\n".join(lines)


def build_ride_id_map(state):
    ride_map = {}
    for park_key, rides in state.items():
        if not isinstance(rides, dict):
            continue
        ride_map[park_key] = [
            {
                "id": ride_id,
                "name": ride_state.get("name") if isinstance(ride_state, dict) else None,
                "is_open": ride_state.get("is_open") if isinstance(ride_state, dict) else ride_state,
            }
            for ride_id, ride_state in rides.items()
        ]
    return ride_map


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="outputs")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    config = parksignals.load_config()
    state = parksignals.load_state()
    observed_at = parksignals.isoformat(parksignals.utc_now())
    last_run = load_json(output_dir / "last-run-summary.json", {})
    if last_run.get("observed_at"):
        observed_at = last_run["observed_at"]
    summary = last_run.get("content_pillar_summary") or parksignals_analytics.collect_content_pillar_summary(
        state,
        config,
        parksignals.parse_timestamp(observed_at) or parksignals.utc_now(),
    )
    park_statuses = last_run.get("park_statuses", [])
    candidates = build_post_candidates(summary, config, last_run, observed_at)

    write_json(output_dir / "analytics-summary.json", summary)
    write_json(output_dir / "post-candidates.json", candidates)
    write_json(output_dir / "ride-id-map.json", build_ride_id_map(state))
    write_json(output_dir / "park-status.json", park_statuses)
    write_text(output_dir / "daily-summary.txt", build_daily_summary(summary))
    write_text(output_dir / "content-pillar-readiness.txt", build_readiness_summary(summary, candidates))
    write_text(output_dir / "park-status.txt", build_park_status_text(park_statuses))
    write_text(output_dir / "post-previews.txt", build_post_previews(candidates))


if __name__ == "__main__":
    main()
