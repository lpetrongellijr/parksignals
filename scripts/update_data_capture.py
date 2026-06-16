import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import data_capture
import parksignals


LAST_RUN_SUMMARY_FILE = Path("outputs") / "last-run-summary.json"


def load_last_run(path=LAST_RUN_SUMMARY_FILE):
    with open(path, "r") as f:
        return json.load(f)


def main():
    config = parksignals.load_config()
    state = parksignals.load_state()
    last_run = load_last_run()
    observed_at = parksignals.parse_timestamp(last_run.get("observed_at"))
    if observed_at is None:
        raise RuntimeError("last-run-summary.json is missing a valid observed_at timestamp")

    data_capture.update_history(
        state,
        config,
        last_run.get("run_summaries", []),
        observed_at,
    )
    print("Updated analytics_history.json")
    print("Wrote outputs/data-capture-summary.txt")
    print("Wrote outputs/data-capture-summary.json")


if __name__ == "__main__":
    main()
