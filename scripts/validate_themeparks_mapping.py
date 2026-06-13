import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import parksignals
import themeparks_wiki


OUTPUT_DIR = Path("outputs")


def status_line(result):
    if result.get("error"):
        return f"{result['park_name']}: ERROR - {result['error']}"
    return (
        f"{result['park_name']}: "
        f"{result['matched_count']}/{result['configured_count']} matched "
        f"against {result.get('themeparks_wiki_entity_name')} "
        f"({result.get('themeparks_wiki_entity_id')})"
    )


def build_text(results):
    lines = ["ThemeParks Wiki mapping validation", ""]
    for result in results:
        lines.append(status_line(result))
        if result.get("error"):
            lines.append("")
            continue
        if result.get("missing"):
            lines.append("Missing configured rides:")
            for name in result["missing"]:
                lines.append(f"  - {name}")
        lines.append("Matched rides:")
        for match in result.get("matches", []):
            wait_time = match.get("wait_time")
            wait_text = "n/a" if wait_time is None else f"{wait_time} min"
            lines.append(
                "  - "
                + match["configured_name"]
                + " -> "
                + str(match.get("matched_name"))
                + " ["
                + str(match.get("entity_id"))
                + "] status "
                + str(match.get("status"))
                + ", wait "
                + wait_text
            )
        lines.append("")
    failed = [result for result in results if result.get("error") or result.get("missing_count", 0) > 0]
    lines.append("Result: " + ("FAILED" if failed else "PASSED"))
    return "\n".join(lines)


def main():
    config = parksignals.load_config()
    results = themeparks_wiki.validate_mapping(config)
    text = build_text(results)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "themeparks-wiki-mapping.json").write_text(json.dumps(results, indent=2) + "\n")
    (OUTPUT_DIR / "themeparks-wiki-mapping.txt").write_text(text + "\n")
    print(text)
    if any(result.get("error") or result.get("missing_count", 0) > 0 for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
