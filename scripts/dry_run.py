import argparse
import io
import json
import shutil
import sys
import tempfile
import types
from contextlib import redirect_stdout
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.modules.setdefault("requests", types.SimpleNamespace(get=lambda *args, **kwargs: None))

import parksignals
import export_artifacts
import parksignals_analytics
import run_monitor


def load_dry_run_data(path):
    with open(path, "r") as f:
        return json.load(f)


def dedupe_repeated_bullets(output):
    lines = []
    seen_bullets_by_section = set()
    current_section = None
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.endswith(":") and not stripped.startswith("- "):
            current_section = stripped
            seen_bullets_by_section = set()
        if stripped.startswith("- "):
            key = (current_section, stripped)
            if key in seen_bullets_by_section:
                continue
            seen_bullets_by_section.add(key)
        lines.append(line)
    return "\n".join(lines)


def normalize_dry_run_output(output):
    normalized = export_artifacts.normalize_post_hashtags(
        export_artifacts.normalize_post_display_text(output)
    )
    return dedupe_repeated_bullets(normalized)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="samples/dry_run_themeparks_wiki.json")
    parser.add_argument("--output-dir", default="outputs")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    dry_run_data = load_dry_run_data(args.data)
    original_fetch_rides = parksignals.fetch_rides

    def fetch_rides_from_sample(park_config, *args, **kwargs):
        park_key = kwargs.get("park_key") or park_config.get("park_key")
        park_data = dry_run_data.get(park_key, {})
        rides = []
        for land in park_data.get("lands", []):
            for ride in land.get("rides", []):
                rides.append({
                    "id": str(ride.get("id")),
                    "name": ride.get("name"),
                    "is_open": ride.get("is_open"),
                    "wait_time": ride.get("wait_time"),
                    "source": "themeparks_wiki_sample",
                    "source_status": ride.get("source_status"),
                    "planned_closure": ride.get("planned_closure"),
                })
        return rides

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_state = Path(temp_dir) / "state.json"
        if Path(parksignals.STATE_FILE).exists():
            shutil.copyfile(parksignals.STATE_FILE, temp_state)
        original_state_file = parksignals.STATE_FILE
        parksignals.STATE_FILE = str(temp_state)
        parksignals.fetch_rides = fetch_rides_from_sample

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            config = parksignals.load_config()
            state = parksignals.load_state()
            observed_at = parksignals.utc_now()
            summaries = []
            for park_key, park_config in parksignals.enabled_park_configs(config):
                summaries.append(
                    parksignals.monitor_park(
                        park_key,
                        park_config,
                        state,
                        observed_at,
                    )
                )
            pillar_summary = parksignals_analytics.collect_content_pillar_summary(
                state,
                config,
                observed_at,
            )
            parksignals.print_run_summary(summaries, observed_at)
            run_monitor.print_content_pillar_summary(pillar_summary, summaries)

        parksignals.fetch_rides = original_fetch_rides
        parksignals.STATE_FILE = original_state_file

    output = normalize_dry_run_output(buffer.getvalue())
    print(output, end="")
    (output_dir / "dry-run-summary.txt").write_text(output)


if __name__ == "__main__":
    main()
