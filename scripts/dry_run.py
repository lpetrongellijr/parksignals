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
sys.modules.setdefault("requests", types.SimpleNamespace(get=lambda *args, **kwargs: None))

import parksignals


def load_dry_run_data(path):
    with open(path, "r") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="samples/dry_run_queue_times.json")
    parser.add_argument("--output-dir", default="outputs")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    dry_run_data = load_dry_run_data(args.data)
    original_fetch_rides = parksignals.fetch_rides

    def fetch_rides_from_sample(park_config, *args, **kwargs):
        park_key = kwargs.get("park_key")
        for candidate_key, candidate_config in parksignals.load_config().get("parks", {}).items():
            if candidate_config.get("park_id") == park_config.get("park_id"):
                park_key = candidate_key
                break
        park_data = dry_run_data.get(park_key, {})
        rides = []
        for land in park_data.get("lands", []):
            for ride in land.get("rides", []):
                rides.append({
                    "id": str(ride.get("id")),
                    "name": ride.get("name"),
                    "is_open": ride.get("is_open"),
                    "wait_time": ride.get("wait_time"),
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
            pillar_summary = parksignals.collect_content_pillar_summary(
                state,
                config,
                observed_at,
            )
            if hasattr(parksignals, "print_run_summary"):
                parksignals.print_run_summary(summaries, observed_at)
                parksignals.print_content_pillar_summary(pillar_summary, summaries)
            else:
                print(parksignals.build_run_summary_text(summaries, observed_at))
                print(parksignals.build_content_pillar_text(pillar_summary, summaries))

        parksignals.fetch_rides = original_fetch_rides
        parksignals.STATE_FILE = original_state_file

    output = buffer.getvalue()
    print(output, end="")
    (output_dir / "dry-run-summary.txt").write_text(output)


if __name__ == "__main__":
    main()
