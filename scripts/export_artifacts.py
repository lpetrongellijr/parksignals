import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import parksignals


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


def format_rankings(title, rankings):
    lines = [title]
    if not rankings:
        lines.append("No downtime recorded yet")
        return lines

    for index, metric in enumerate(rankings, start=1):
        lines.append(
            f"{index}. {metric['ride_name']} ({metric['park_name']}) - "
            f"{parksignals.format_duration(metric['downtime_seconds'])}"
        )
    return lines


def build_daily_summary(summary):
    lines = format_rankings("Daily downtime summary", summary["daily_top"])
    stable_park = summary.get("stable_park")
    if stable_park:
        lines.append(f"Most stable park: {stable_park[0]}")
    return "\n".join(lines)


def build_readiness_summary(summary):
    lines = ["Content pillar readiness"]
    lines.append("Single ride closure/reopen: supported by monitor transitions")
    if summary["active_multi_ride_alerts"]:
        lines.append(
            "Multi-ride closures: "
            + str(len(summary["active_multi_ride_alerts"]))
            + " active candidates"
        )
    else:
        lines.append("Multi-ride closures: none active")
    lines.extend(format_rankings("Daily summary inputs", summary["daily_top"]))
    lines.extend(format_rankings("30-day downtime inputs", summary["thirty_day_top"]))
    lines.append(f"Trend candidates: {len(summary['elevated_trends'])}")
    lines.append(f"Active projection candidates: {len(summary['active_projections'])}")
    return "\n".join(lines)


def build_post_candidates(summary):
    return {
        "posting_connected": False,
        "single_ride_closures": [],
        "single_ride_reopenings": [],
        "multi_ride_closures": summary["active_multi_ride_alerts"],
        "multi_ride_reopenings": [],
        "daily_summaries": summary["daily_top"],
        "thirty_day_rankings": summary["thirty_day_top"],
        "insights": {
            "elevated_trends": summary["elevated_trends"],
            "active_projections": summary["active_projections"],
        },
    }


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
    observed_at = parksignals.utc_now()
    summary = parksignals.collect_content_pillar_summary(state, config, observed_at)

    write_json(output_dir / "analytics-summary.json", summary)
    write_json(output_dir / "post-candidates.json", build_post_candidates(summary))
    write_json(output_dir / "ride-id-map.json", build_ride_id_map(state))
    write_text(output_dir / "daily-summary.txt", build_daily_summary(summary))
    write_text(output_dir / "content-pillar-readiness.txt", build_readiness_summary(summary))


if __name__ == "__main__":
    main()
