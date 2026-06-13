from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import parksignals


PARK_ANALYTICS_TIMEZONE = "America/New_York"
SECONDS_PER_DAY = 24 * 60 * 60


def local_day_start(observed_at, timezone_name=PARK_ANALYTICS_TIMEZONE):
    local_tz = ZoneInfo(timezone_name)
    local_observed_at = observed_at.astimezone(local_tz)
    return datetime.combine(
        local_observed_at.date(),
        time.min,
        tzinfo=local_tz,
    ).astimezone(timezone.utc)


def completed_month_window(observed_at, timezone_name=PARK_ANALYTICS_TIMEZONE):
    local_tz = ZoneInfo(timezone_name)
    local_observed_at = observed_at.astimezone(local_tz)
    current_month_start = datetime(local_observed_at.year, local_observed_at.month, 1, tzinfo=local_tz)
    if current_month_start.month == 1:
        previous_month_start = datetime(current_month_start.year - 1, 12, 1, tzinfo=local_tz)
    else:
        previous_month_start = datetime(current_month_start.year, current_month_start.month - 1, 1, tzinfo=local_tz)
    return (
        previous_month_start.astimezone(timezone.utc),
        current_month_start.astimezone(timezone.utc),
        previous_month_start.strftime("%B %Y"),
    )


def state_history_start(state):
    timestamps = []
    ride_timestamp_fields = ["last_seen_at", "last_changed_at", "down_since", "last_down_at", "last_reopened_at"]
    event_timestamp_fields = ["down_at", "reopened_at"]

    for park_state in state.values():
        if not isinstance(park_state, dict):
            continue
        for ride_state in park_state.values():
            if not isinstance(ride_state, dict):
                continue
            for field in ride_timestamp_fields:
                parsed = parksignals.parse_timestamp(ride_state.get(field))
                if parsed is not None:
                    timestamps.append(parsed)
            for event in ride_state.get("downtime_events", []):
                if not isinstance(event, dict):
                    continue
                for field in event_timestamp_fields:
                    parsed = parksignals.parse_timestamp(event.get(field))
                    if parsed is not None:
                        timestamps.append(parsed)

    return min(timestamps) if timestamps else None


def data_coverage(state, observed_at):
    started_at = state_history_start(state)
    if started_at is None:
        return {"data_observed_since": None, "data_age_seconds": 0, "data_age_days": 0}

    age_seconds = max(0, int((observed_at - started_at).total_seconds()))
    return {
        "data_observed_since": parksignals.isoformat(started_at),
        "data_age_seconds": age_seconds,
        "data_age_days": age_seconds // SECONDS_PER_DAY,
    }


def observed_active_end(ride_state, window_end):
    last_seen_at = parksignals.parse_timestamp(ride_state.get("last_seen_at"))
    if last_seen_at is None:
        return window_end
    return min(last_seen_at, window_end)


def analytics_events_in_window(ride_state, window_start, window_end):
    events = list(parksignals.events_in_window(ride_state, window_start, window_end))
    if ride_state.get("is_open") is not False:
        return events

    active_end = observed_active_end(ride_state, window_end)
    active_events = [
        event
        for event in events
        if event.get("reopened_at") is None
    ]
    completed_events = [
        event
        for event in events
        if event.get("reopened_at") is not None
    ]
    if not active_events:
        return completed_events

    active_duration = parksignals.overlap_seconds(
        ride_state.get("down_since"),
        parksignals.isoformat(active_end),
        window_start,
        window_end,
    )
    if active_duration <= 0:
        return completed_events

    completed_events.append({
        "down_at": ride_state.get("down_since"),
        "reopened_at": None,
        "duration_seconds": active_duration,
    })
    return completed_events


def analytics_downtime_seconds_in_window(ride_state, window_start, window_end):
    return sum(event["duration_seconds"] for event in analytics_events_in_window(ride_state, window_start, window_end))


def analytics_current_down_seconds(ride_state, window_start, window_end):
    if ride_state.get("is_open") is not False:
        return 0
    return parksignals.overlap_seconds(
        ride_state.get("down_since"),
        parksignals.isoformat(observed_active_end(ride_state, window_end)),
        window_start,
        window_end,
    )


def analytics_ride_metric(park_key, park_name, ride_id, ride_state, window_start, window_end):
    events = analytics_events_in_window(ride_state, window_start, window_end)
    return {
        "park_key": park_key,
        "park_name": park_name,
        "ride_id": ride_id,
        "ride_name": ride_state.get("name") or ride_id,
        "is_open": ride_state.get("is_open"),
        "downtime_seconds": sum(event["duration_seconds"] for event in events),
        "event_count": len(events),
        "average_completed_downtime_seconds": parksignals.average_completed_downtime_seconds(
            ride_state,
            window_start,
            window_end,
        ),
        "current_down_seconds": analytics_current_down_seconds(ride_state, window_start, window_end),
    }


def unavailable_ride_names(park_state):
    names = []
    seen = set()
    for ride_id, ride_state in park_state.items():
        if not isinstance(ride_state, dict) or ride_state.get("is_open") is not False:
            continue
        name = ride_state.get("name") or ride_id
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def collect_content_pillar_summary(state, config, observed_at):
    day_start = local_day_start(observed_at)
    monthly_start, monthly_end, monthly_label = completed_month_window(observed_at)
    trend_start = observed_at - timedelta(days=parksignals.TREND_LOOKBACK_DAYS)
    coverage = data_coverage(state, observed_at)
    trend_insights_ready = coverage["data_age_seconds"] >= parksignals.TREND_LOOKBACK_DAYS * SECONDS_PER_DAY
    monthly_reliability_ready = coverage["data_age_seconds"] >= parksignals.ANALYTICS_LOOKBACK_DAYS * SECONDS_PER_DAY
    parks = config.get("parks", {})
    daily_metrics = []
    monthly_metrics = []
    trend_metrics = []
    park_daily_totals = {}

    for park_key, park_config in parksignals.enabled_park_configs(config):
        park_name = park_config["park_name"]
        park_state = state.get(park_key, {})
        park_daily_totals[park_name] = 0

        for ride_id, ride_state in park_state.items():
            if not isinstance(ride_state, dict):
                continue

            parksignals.prune_downtime_events(ride_state, observed_at)
            daily_metric = analytics_ride_metric(park_key, park_name, ride_id, ride_state, day_start, observed_at)
            monthly_metric = analytics_ride_metric(park_key, park_name, ride_id, ride_state, monthly_start, monthly_end)
            trend_metric = analytics_ride_metric(park_key, park_name, ride_id, ride_state, trend_start, observed_at)

            daily_metrics.append(daily_metric)
            monthly_metrics.append(monthly_metric)
            trend_metrics.append(trend_metric)
            park_daily_totals[park_name] += daily_metric["downtime_seconds"]

    stable_park = None
    if park_daily_totals:
        stable_park = min(park_daily_totals.items(), key=lambda item: item[1])

    active_multi_ride_alerts = []
    for park_key, park_config in parks.items():
        if not park_config.get("enabled", False):
            continue
        unavailable = unavailable_ride_names(state.get(park_key, {}))
        if len(unavailable) >= 2:
            active_multi_ride_alerts.append({"park_name": park_config["park_name"], "rides": unavailable})

    elevated_trends = []
    if trend_insights_ready:
        elevated_trends = [metric for metric in trend_metrics if metric["event_count"] >= 2]

    active_projections = []
    if monthly_reliability_ready:
        for metric in monthly_metrics:
            average_duration = metric["average_completed_downtime_seconds"]
            if metric["is_open"] is False and average_duration and metric["current_down_seconds"] > 0:
                active_projections.append({
                    **metric,
                    "projected_total_seconds": average_duration,
                    "projected_remaining_seconds": max(0, average_duration - metric["current_down_seconds"]),
                })

    monthly_top = parksignals.top_downtime(monthly_metrics) if monthly_reliability_ready else []
    return {
        "daily_window_timezone": PARK_ANALYTICS_TIMEZONE,
        "daily_window_start": parksignals.isoformat(day_start),
        "daily_window_end": parksignals.isoformat(observed_at),
        "monthly_window_timezone": PARK_ANALYTICS_TIMEZONE,
        "monthly_window_start": parksignals.isoformat(monthly_start),
        "monthly_window_end": parksignals.isoformat(monthly_end),
        "monthly_window_label": monthly_label,
        "data_observed_since": coverage["data_observed_since"],
        "data_age_seconds": coverage["data_age_seconds"],
        "data_age_days": coverage["data_age_days"],
        "trend_insights_ready": trend_insights_ready,
        "trend_insights_min_days": parksignals.TREND_LOOKBACK_DAYS,
        "monthly_reliability_ready": monthly_reliability_ready,
        "monthly_reliability_min_days": parksignals.ANALYTICS_LOOKBACK_DAYS,
        "daily_top": parksignals.top_downtime(daily_metrics),
        "monthly_top": monthly_top,
        "thirty_day_top": monthly_top,
        "stable_park": stable_park,
        "active_multi_ride_alerts": active_multi_ride_alerts,
        "elevated_trends": elevated_trends,
        "active_projections": active_projections,
    }
