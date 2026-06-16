import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import x_integration


DEFAULT_LOG_FILE = "posting_log.json"
DEFAULT_BATCH_SIZE = 1
DEFAULT_BATCH_DELAY_SECONDS = 60
POST_PRIORITY = {
    "down": 1,
    "reopened": 2,
    "multi_ride_closure": 3,
    "wdw_daily_summary": 5,
    "wdw_monthly_reliability": 6,
    "wdw_30_day_downtime": 6,
    "trend_detection": 7,
    "active_projection": 8,
}
AUTH_CONFIGURATION_ERROR_MARKERS = (
    "HTTP 401",
    "HTTP 403",
    "oauth1-permissions",
    "not configured with the appropriate oauth1 app permissions",
    "Missing required X credentials",
)


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


def github_warning(title, message):
    safe_message = str(message).replace("\n", " ")
    print(f"::warning title={title}::{safe_message}")


def ready_posts(plan):
    ready = []
    for index, item in enumerate(plan.get("items", [])):
        if item.get("decision") != "post" or item.get("status") != "ready_to_post":
            continue
        ready.append((index, item))
    return [
        item
        for _index, item in sorted(
            ready,
            key=lambda indexed_item: (
                POST_PRIORITY.get(indexed_item[1].get("type"), 99),
                indexed_item[0],
            ),
        )
    ]


def post_result_template(item, sequence, batch_number):
    return {
        "dedupe_key": item["dedupe_key"],
        "pillar": item["pillar"],
        "type": item["type"],
        "park_name": item.get("park_name"),
        "ride_name": item.get("ride_name"),
        "priority": POST_PRIORITY.get(item.get("type"), 99),
        "sequence": sequence,
        "batch_number": batch_number,
        "status": "pending",
        "tweet_id": None,
        "error": None,
    }


def is_auth_configuration_error(error):
    error_text = str(error)
    return any(marker in error_text for marker in AUTH_CONFIGURATION_ERROR_MARKERS)


def skipped_after_auth_failure_result(item, sequence, batch_number):
    result = post_result_template(item, sequence, batch_number)
    result["status"] = "skipped"
    result["error"] = "Skipped because an earlier X post failed with an authentication or app-permission error."
    return result


def dispatch_ready_posts(plan, batch_size=DEFAULT_BATCH_SIZE, batch_delay_seconds=DEFAULT_BATCH_DELAY_SECONDS, sleep=time.sleep):
    posts = ready_posts(plan)
    results = []
    if not posts:
        return results

    batch_size = max(1, int(batch_size))
    batch_delay_seconds = max(0, int(batch_delay_seconds))
    total_batches = (len(posts) + batch_size - 1) // batch_size
    print(
        f"Dispatching {len(posts)} X post(s) in {total_batches} batch(es), "
        f"{batch_delay_seconds}s cooldown between batches.",
        flush=True,
    )

    stop_after_auth_failure = False
    for batch_index in range(total_batches):
        batch_number = batch_index + 1
        batch = posts[batch_index * batch_size:(batch_index + 1) * batch_size]

        if stop_after_auth_failure:
            for item in batch:
                results.append(skipped_after_auth_failure_result(item, len(results) + 1, batch_number))
            continue

        if batch_index > 0 and batch_delay_seconds:
            print(
                f"Waiting {batch_delay_seconds}s before X post batch {batch_number}/{total_batches}.",
                flush=True,
            )
            sleep(batch_delay_seconds)

        for item in batch:
            result = post_result_template(item, len(results) + 1, batch_number)
            label = item.get("ride_name") or item.get("type") or item.get("dedupe_key")
            print(f"Sending X post batch {batch_number}/{total_batches}: {label}", flush=True)
            try:
                posted = x_integration.publish_post(item.get("preview_text", ""))
            except x_integration.XIntegrationError as exc:
                result["status"] = "failed"
                result["error"] = str(exc)
                print(f"X post failed: {label}: {exc}", flush=True)
                if is_auth_configuration_error(exc):
                    stop_after_auth_failure = True
                    print(
                        "Stopping remaining X dispatch attempts because X reported an authentication or app-permission error.",
                        flush=True,
                    )
            else:
                result["status"] = "posted"
                result["tweet_id"] = posted.get("tweet_id")
                print(f"X post sent: {label}", flush=True)
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


def build_results_text(results, batch_size=DEFAULT_BATCH_SIZE, batch_delay_seconds=DEFAULT_BATCH_DELAY_SECONDS):
    lines = ["X dispatch results"]
    lines.append(f"Batch size: {batch_size}")
    lines.append(f"Delay between batches: {batch_delay_seconds} seconds")
    lines.append("Priority: single closures, single reopenings, multi-ride closures, then summaries and insights")
    lines.append("")
    if not results:
        lines.append("No posts were ready to dispatch.")
        return "\n".join(lines)

    for result in results:
        lines.append(
            f"- {result['status']}: batch {result['batch_number']}, "
            f"sequence {result['sequence']}, priority {result['priority']} "
            f"({result['pillar']} / {result['type']})"
        )
        if result.get("park_name"):
            lines.append(f"  Park: {result['park_name']}")
        if result.get("ride_name"):
            lines.append(f"  Ride: {result['ride_name']}")
        if result.get("tweet_id"):
            lines.append(f"  Tweet ID: {result['tweet_id']}")
        if result.get("error"):
            lines.append(f"  Error: {result['error']}")
    return "\n".join(lines)


def warn_for_failures(results):
    for result in results:
        if result.get("status") != "failed":
            continue
        label = result.get("ride_name") or result.get("type") or result.get("dedupe_key")
        github_warning("X dispatch failed", f"{label}: {result.get('error')}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--log", default=DEFAULT_LOG_FILE)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--batch-delay-seconds", type=int, default=DEFAULT_BATCH_DELAY_SECONDS)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    plan = load_json(output_dir / "post-dispatch-plan.json", {})
    posting_log = load_json(Path(args.log), {"version": 1, "posted_keys": [], "decisions": []})

    results = dispatch_ready_posts(
        plan,
        batch_size=args.batch_size,
        batch_delay_seconds=args.batch_delay_seconds,
    )
    posting_log = update_posting_log(posting_log, results)
    results_text = build_results_text(results, args.batch_size, args.batch_delay_seconds)

    write_json(
        output_dir / "x-dispatch-results.json",
        {
            "batch_size": max(1, int(args.batch_size)),
            "batch_delay_seconds": max(0, int(args.batch_delay_seconds)),
            "priority_order": POST_PRIORITY,
            "results": results,
        },
    )
    write_text(output_dir / "x-dispatch-results.txt", results_text)
    write_json(Path(args.log), posting_log)

    print("")
    print(results_text)
    warn_for_failures(results)


if __name__ == "__main__":
    main()
