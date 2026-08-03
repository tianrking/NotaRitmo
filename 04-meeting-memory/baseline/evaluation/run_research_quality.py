from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from research_quality import evaluate_fixture
except ImportError:  # invoked as evaluation/run_research_quality.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from research_quality import evaluate_fixture


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate fixed meeting retrieval/policy quality")
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate_fixture(args.fixture_dir)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
