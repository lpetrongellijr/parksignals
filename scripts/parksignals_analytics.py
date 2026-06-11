from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import parksignals


PARK_ANALYTICS_TIMEZONE = "America/New_York"


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
    current_month_start = datetime(
        local_observed_at.year,
        local_observed_at.month,
        1,
        tzinfo=local_tz,
    )
    if current_month_start.month == 1:
        previous_month_start = datetime(current_month_start.year - 1, 12, 1, tzinfo=local_tz)
    else:
        previous_month_start = datetime(
            current_month_start.year,
            current_month_start.month - 1,
            1,
            tzinfo=local_tz,
        )
    return (
        previous_month_start.astimezone(timezone.utc),
        current_month_start.astimezone(timezone.utc),
        previous_month_start.strftime("%B %Y"),
    )


def collect_content_pillar_summary(state, config, observed_at):
    day_start = local_day_start(observed_at)
    monthly_start, monthly_end, monthly_label = completed_month_window(observed_at)
    trend_start = observed_at - timedelta(days=parksignals.TREND_LOOKBACK_DAYS)
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
            daily_metric = parksignals.ride_metric(
                park_key,
                park_name,
                ride_id,
                ride_state,
                day_start,
                observed_at,
            )
            monthly_metric = parksignals.ride_metric(
                park_key,
                park_name,
                ride_id,
                ride_state,
                monthly_start,
                monthly_end,
            )
            trend_metric = parksignals.ride_metric(
                park_key,
                park_name,
                ride_id,
                ride_state,
                trend_start,
                observed_at,
            )

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
    for metric in monthly_metrics:
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

    monthly_top = parksignals.top_downtime(monthly_metrics)
    return {
        "daily_window_timezone": PARK_ANALYTICS_TIMEZONE,
        "daily_window_start": parksignals.isoformat(day_start),
        "daily_window_end": parksignals.isoformat(observed_at),
        "monthly_window_timezone": PARK_ANALYTICS_TIMEZONE,
        "monthly_window_start": parksignals.isoformat(monthly_start),
        "monthly_window_end": parksignals.isoformat(monthly_end),
        "monthly_window_label": monthly_label,
        "daily_top": parksignals.top_downtime(daily_metrics),
        "monthly_top": monthly_top,
        "thirty_day_top": monthly_top,
        "stable_park": stable_park,
        "active_multi_ride_alerts": active_multi_ride_alerts,
        "elevated_trends": elevated_trends,
        "active_projections": active_projections,
    }
