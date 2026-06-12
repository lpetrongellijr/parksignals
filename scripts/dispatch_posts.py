import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import x_integration


DEFAULT_LOG_FILE = "posting_log.json"


def load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


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


def dispatch_ready_posts(plan):
    results = []
    for item in plan.get("items", []):
        if item.get("decision") != "post" or item.get("status") != "ready_to_post":
            continue

        result = {
            "dedupe_key": item["dedupe_key"],
            "pillar": item["pillar"],
            "type": item["type"],
            "park_name": item.get("park_name"),
            "ride_name": item.get("ride_name"),
            "status": "pending",
            "tweet_id": None,
            "error": None,
        }
        try:
            posted = x_integration.publish_post(item.get("preview_text", ""))
        except x_integration.XIntegrationError as exc:
            result["status"] = "failed"
            result["error"] = str(exc)
        else:
            result["status"] = "posted"
            result["tweet_id"] = posted.get("tweet_id")
        results.append(result)
    return results


def update_posting_log(posting_log, results):
    posting_log.setdefault("version", 1)
    posted_keys = set(posting_log.setdefault("posted_keys", []))
    decisions = posting_log.setdefault("decisions", [])

    for result in results:
        if result["status"] != "posted":
            continue
        posted_keys.add(result["dedupe_key"])
        decisions.append({
            "dedupe_key": result["dedupe_key"],
            "pillar": result["pillar"],
            "type": result["type"],
            "park_name": result.get("park_name"),
            "ride_name": result.get("ride_name"),
            "status": "posted",
            "tweet_id": result.get("tweet_id"),
            "posting_enabled": True,
        })

    posting_log["posted_keys"] = sorted(posted_keys)
    posting_log["decisions"] = decisions[-500:]
    return posting_log


def build_results_text(results):
    lines = ["X dispatch results"]
    if not results:
        lines.append("No posts were ready to dispatch.")
        return "\n".join(lines)

    for result in results:
        lines.append(f"- {result['status']}: {result['pillar']} / {result['type']}")
        if result.get("park_name"):
            lines.append(f"  Park: {result['park_name']}")
        if result.get("ride_name"):
            lines.append(f"  Ride: {result['ride_name']}")
        if result.get("tweet_id"):
            lines.append(f"  Tweet ID: {result['tweet_id']}")
        if result.get("error"):
            lines.append(f"  Error: {result['error']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--log", default=DEFAULT_LOG_FILE)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    plan = load_json(output_dir / "post-dispatch-plan.json", {})
    posting_log = load_json(Path(args.log), {"version": 1, "posted_keys": [], "decisions": []})

    results = dispatch_ready_posts(plan)
    posting_log = update_posting_log(posting_log, results)

    write_json(output_dir / "x-dispatch-results.json", {"results": results})
    write_text(output_dir / "x-dispatch-results.txt", build_results_text(results))
    write_json(Path(args.log), posting_log)

    failed = [result for result in results if result["status"] == "failed"]
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
