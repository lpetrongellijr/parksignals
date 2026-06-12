import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import parksignals
import x_integration


DEFAULT_POLICY_FILE = "posting_policy.json"
DEFAULT_LOG_FILE = "posting_log.json"
MAX_RECORDED_DECISIONS = 500
PARK_TIMEZONE = "America/New_York"
POST_CONTEXT_MONITOR = "monitor"
POST_CONTEXT_DAILY_SUMMARY = "daily_summary"


def utc_now_text():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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


def suppressed_reopening_pairs(candidates):
    pairs = set()
    for item in candidates.get("multi_ride_reopenings", []):
        park_name = item.get("park_name")
        for ride_name in item.get("rides", []):
            if park_name and ride_name:
                pairs.add((park_name, ride_name))
    return pairs


def candidate_groups(candidates):
    suppressed_reopenings = suppressed_reopening_pairs(candidates)
    groups = [
        ("single_ride_closures", candidates.get("single_ride_closures", [])),
        ("single_ride_reopenings", candidates.get("single_ride_reopenings", [])),
        ("multi_ride_closures", candidates.get("multi_ride_closures", [])),
        ("multi_ride_reopenings", candidates.get("multi_ride_reopenings", [])),
        ("daily_summaries", candidates.get("daily_summaries", [])),
        ("thirty_day_rankings", candidates.get("thirty_day_rankings", [])),
        ("insights_elevated_trends", candidates.get("insights", {}).get("elevated_trends", [])),
        ("insights_active_projections", candidates.get("insights", {}).get("active_projections", [])),
    ]
    for group_name, items in groups:
        for item in items:
            if (
                group_name == "single_ride_reopenings"
                and (item.get("park_name"), item.get("ride_name")) in suppressed_reopenings
            ):
                continue
            yield group_name, item


def candidate_text(candidate):
    return candidate.get("preview_text", "") or ""


def stable_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def local_date_from_observed_at(observed_at):
    parsed = parksignals.parse_timestamp(observed_at)
    if parsed is None:
        return "unknown-date"
    return parsed.astimezone(ZoneInfo(PARK_TIMEZONE)).date().isoformat()


def stable_ride_set(candidate):
    return "|".join(sorted(candidate.get("rides", [])))


def candidate_key(candidate, observed_at):
    pillar = candidate.get("pillar", "unknown")
    candidate_type = candidate.get("type", "unknown")
    park = candidate.get("park_name") or candidate.get("metric", {}).get("park_name") or "resort"
    ride_id = candidate.get("ride_id") or candidate.get("metric", {}).get("ride_id")
    ride_name = candidate.get("ride_name") or candidate.get("metric", {}).get("ride_name")
    local_date = local_date_from_observed_at(observed_at)

    if pillar == "real_time_alert" and ride_id:
        return f"{pillar}:{candidate_type}:{park}:{ride_id}:{observed_at}"
    if pillar == "real_time_alert" and candidate.get("rides"):
        return f"{pillar}:{candidate_type}:{park}:{stable_hash(stable_ride_set(candidate))}:{local_date}"
    if pillar == "daily_operations_summary":
        return f"{pillar}:{candidate_type}:{local_date}"
    if pillar == "reliability_analytics":
        return f"{pillar}:{candidate_type}:{local_date}"
    if pillar == "insights_predictions" and ride_id:
        return f"{pillar}:{candidate_type}:{park}:{ride_id}:{local_date}"
    if ride_name:
        return f"{pillar}:{candidate_type}:{park}:{stable_hash(ride_name)}:{local_date}"
    return f"{pillar}:{candidate_type}:{stable_hash(candidate_text(candidate))}:{local_date}"


def policy_type_enabled(policy, pillar, candidate_type):
    pillar_policy = policy.get("pillars", {}).get(pillar, {})
    if not pillar_policy.get("enabled", False):
        return False
    type_policy = pillar_policy.get("types", {})
    return type_policy.get(candidate_type, False)


def posted_key_set(posting_log):
    keys = set(posting_log.get("posted_keys", []))
    for decision in posting_log.get("decisions", []):
        if decision.get("status") in {"posted", "dispatch_confirmed"}:
            keys.add(decision.get("dedupe_key"))
    return {key for key in keys if key}


def park_is_open_for_candidate(candidate, park_statuses):
    park_name = candidate.get("park_name") or candidate.get("metric", {}).get("park_name")
    if not park_name:
        return True
    for status in park_statuses:
        if status.get("park_name") == park_name:
            return status.get("monitoring_allowed") is True
    return True


def has_nonempty_metrics(candidate):
    metrics = candidate.get("metrics")
    if metrics is None:
        return True
    return bool(metrics)


def evaluate_candidate(candidate, policy, x_status, posting_log, park_statuses, observed_at, post_context):
    text = candidate_text(candidate)
    pillar = candidate.get("pillar", "unknown")
    candidate_type = candidate.get("type", "unknown")
    key = candidate_key(candidate, observed_at)
    reasons = []

    if not text.strip():
        reasons.append("missing_preview_text")
    if len(text) > int(policy.get("max_post_characters", 280)):
        reasons.append("post_text_too_long")
    if not policy_type_enabled(policy, pillar, candidate_type):
        reasons.append("pillar_or_type_disabled")
    if policy.get("require_x_credentials", True) and not x_status.get("ready_for_manual_connection_test"):
        reasons.append("x_credentials_not_ready")
    if (
        policy.get("rules", {}).get("block_real_time_posts_outside_park_hours", True)
        and pillar == "real_time_alert"
        and not park_is_open_for_candidate(candidate, park_statuses)
    ):
        reasons.append("park_closed_for_monitoring")
    if (
        policy.get("rules", {}).get("block_daily_summary_outside_daily_workflow", True)
        and pillar == "daily_operations_summary"
        and post_context != POST_CONTEXT_DAILY_SUMMARY
    ):
        reasons.append("daily_summary_not_in_daily_workflow")
    if (
        policy.get("rules", {}).get("block_empty_daily_summary", True)
        and pillar == "daily_operations_summary"
        and not has_nonempty_metrics(candidate)
    ):
        reasons.append("empty_daily_summary")
    if (
        policy.get("rules", {}).get("block_empty_analytics", True)
        and pillar == "reliability_analytics"
        and not has_nonempty_metrics(candidate)
    ):
        reasons.append("empty_analytics")
    if (
        policy.get("rules", {}).get("block_duplicate_posted_keys", True)
        and key in posted_key_set(posting_log)
    ):
        reasons.append("duplicate_previously_posted")

    posting_enabled = bool(policy.get("posting_enabled", False)) and x_integration.posting_enabled()
    if reasons:
        decision = "skip"
        status = "blocked"
    elif posting_enabled:
        decision = "post"
        status = "ready_to_post"
    elif policy.get("dry_run", True):
        decision = "would_post"
        status = "dry_run_planned"
    else:
        decision = "skip"
        status = "posting_disabled"
        reasons.append("posting_disabled")

    return {
        "dedupe_key": key,
        "pillar": pillar,
        "type": candidate_type,
        "park_name": candidate.get("park_name") or candidate.get("metric", {}).get("park_name"),
        "ride_name": candidate.get("ride_name") or candidate.get("metric", {}).get("ride_name"),
        "decision": decision,
        "status": status,
        "reasons": reasons,
        "text_length": len(text),
        "preview_text": text,
    }


def append_decisions(posting_log, plan, generated_at):
    posting_log.setdefault("version", 1)
    posting_log.setdefault("posted_keys", [])
    decisions = posting_log.setdefault("decisions", [])
    for item in plan["items"]:
        if item["decision"] not in {"would_post", "post"}:
            continue
        decisions.append({
            "recorded_at": generated_at,
            "dedupe_key": item["dedupe_key"],
            "pillar": item["pillar"],
            "type": item["type"],
            "park_name": item.get("park_name"),
            "ride_name": item.get("ride_name"),
            "status": item["status"],
            "posting_enabled": plan["posting_enabled"],
        })
    posting_log["decisions"] = decisions[-MAX_RECORDED_DECISIONS:]
    return posting_log


def build_plan_text(plan):
    lines = ["Post dispatch plan"]
    lines.append(f"Generated at: {plan['generated_at']}")
    lines.append(f"Post context: {plan['post_context']}")
    lines.append(f"Posting enabled: {str(plan['posting_enabled']).lower()}")
    lines.append(f"Dry run: {str(plan['dry_run']).lower()}")
    lines.append(f"Candidates: {plan['candidate_count']}")
    lines.append(f"Would post: {plan['would_post_count']}")
    lines.append(f"Ready to post: {plan['ready_to_post_count']}")
    lines.append(f"Skipped: {plan['skip_count']}")
    lines.append("")

    if not plan["items"]:
        lines.append("No post candidates were available.")
        return "\n".join(lines)

    for index, item in enumerate(plan["items"], start=1):
        lines.append(f"Candidate {index}: {item['decision']} ({item['pillar']} / {item['type']})")
        if item.get("park_name"):
            lines.append(f"Park: {item['park_name']}")
        if item.get("ride_name"):
            lines.append(f"Ride: {item['ride_name']}")
        lines.append(f"Key: {item['dedupe_key']}")
        if item["reasons"]:
            lines.append("Reasons: " + ", ".join(item["reasons"]))
        lines.append(f"Text length: {item['text_length']}")
        lines.append("Preview:")
        lines.append(item["preview_text"] or "(empty)")
        lines.append("")
    return "\n".join(lines)


def build_plan(candidates, policy, x_status, posting_log, last_run, post_context=POST_CONTEXT_MONITOR):
    generated_at = utc_now_text()
    observed_at = candidates.get("observed_at") or last_run.get("observed_at") or generated_at
    park_statuses = last_run.get("park_statuses", [])
    items = [
        evaluate_candidate(candidate, policy, x_status, posting_log, park_statuses, observed_at, post_context)
        for _group_name, candidate in candidate_groups(candidates)
    ]
    return {
        "generated_at": generated_at,
        "observed_at": observed_at,
        "post_context": post_context,
        "posting_enabled": bool(policy.get("posting_enabled", False)) and x_integration.posting_enabled(),
        "dry_run": bool(policy.get("dry_run", True)),
        "candidate_count": len(items),
        "would_post_count": sum(1 for item in items if item["decision"] == "would_post"),
        "ready_to_post_count": sum(1 for item in items if item["decision"] == "post"),
        "skip_count": sum(1 for item in items if item["decision"] == "skip"),
        "items": items,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--policy", default=DEFAULT_POLICY_FILE)
    parser.add_argument("--log", default=DEFAULT_LOG_FILE)
    parser.add_argument("--post-context", default=os.environ.get("PARKSIGNALS_POST_CONTEXT", POST_CONTEXT_MONITOR))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    policy = load_json(Path(args.policy), {})
    posting_log = load_json(Path(args.log), {"version": 1, "posted_keys": [], "decisions": []})
    candidates = load_json(output_dir / "post-candidates.json", {})
    x_status = load_json(output_dir / "x-connection-status.json", x_integration.connection_status())
    last_run = load_json(output_dir / "last-run-summary.json", {})

    plan = build_plan(candidates, policy, x_status, posting_log, last_run, args.post_context)
    if policy.get("rules", {}).get("record_dry_run_decisions", True):
        posting_log = append_decisions(posting_log, plan, plan["generated_at"])

    write_json(output_dir / "post-dispatch-plan.json", plan)
    write_text(output_dir / "post-dispatch-plan.txt", build_plan_text(plan))
    write_json(Path(args.log), posting_log)


if __name__ == "__main__":
    main()
