import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import x_integration


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--timeout", type=int, default=x_integration.DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    status = x_integration.verify_connection(timeout=args.timeout)
    write_json(output_dir / "x-connection-test.json", status)
    write_text(output_dir / "x-connection-test.txt", x_integration.connection_status_text(status))
    print(x_integration.connection_status_text(status))

    if not status.get("connection_test_passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
