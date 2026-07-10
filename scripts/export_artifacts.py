import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import parksignals
import parksignals_analytics


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
    for index, metric in enumerate(rankings[:limit] if limit else rankings, start=1):
        lines.append(f"{index}. {metric_line(metric)}")
    return lines


def monthly_rankings(summary):
    if not summary.get("monthly_reliability_ready", True):
        return []
    return summary.get("monthly_top") or summary.get("thirty_day_top", [])


def analytics_hold_message(summary, readiness_key, min_days_key):
    if summary.get(readiness_key, True):
        return None
    return (
        f"Waiting for {summary.get(min_days_key, 0)} days of history; "
        f"current history is {summary.get('data_age_days', 0)} days."
    )


def build_daily_summary(summary):
    return "\n".join(format_rankings("Daily downtime summary", summary["daily_top"], limit=3))


def build_readiness_summary(summary):
    reliability_rankings = monthly_rankings(summary)
    trend_hold = analytics_hold_message(summary, "trend_insights_ready", "trend_insights_min_days")
    monthly_hold = analytics_hold_message(summary, "monthly_reliability_ready", "monthly_reliability_min_days")
    lines = ["Analytics readiness"]
    lines.extend(format_rankings("Daily summary inputs", summary["daily_top"]))
    if monthly_hold:
        lines.append("Monthly reliability inputs")
        lines.append(monthly_hold)
    else:
        lines.extend(format_rankings("Monthly reliability inputs", reliability_rankings))
    if trend_hold:
        lines.append(f"Trend insight inputs: waiting ({trend_hold})")
    else:
        lines.append(f"Trend insight inputs: {len(summary.get('elevated_trends', []))} elevated trend(s)")
    lines.append(f"Projection inputs: {len(summary.get('active_projections', []))} active projection(s)")
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
    write_json(output_dir / "analytics-summary.json", summary)
    write_json(output_dir / "ride-id-map.json", build_ride_id_map(state))
    write_json(output_dir / "park-status.json", park_statuses)
    write_text(output_dir / "daily-summary.txt", build_daily_summary(summary))
    write_text(output_dir / "analytics-readiness.txt", build_readiness_summary(summary))
    write_text(output_dir / "park-status.txt", build_park_status_text(park_statuses))


if __name__ == "__main__":
    main()
