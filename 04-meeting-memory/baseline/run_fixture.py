from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from engine import MemoryStore, evaluate_all, load_fixture
from service import MeetingMemoryService


DEFAULT_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "meeting-memory-fixture-10"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-root", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--implementation",
        choices=("modular", "legacy"),
        default="modular",
        help="modular uses MeetingMemoryService; legacy runs the original MemoryStore path",
    )
    args = parser.parse_args()
    fixture = load_fixture(args.fixture_root)
    if args.implementation == "legacy":
        store: Any = MemoryStore.from_fixture(fixture)
    else:
        store = MeetingMemoryService.from_fixture(fixture)
    report = evaluate_all(store, fixture.queries)
    result = {
        "fixture": str(args.fixture_root),
        "implementation": args.implementation,
        "meetings": len(store.meetings),
        "segments": len(store.segments),
        "artifacts": len(store.artifacts),
        "claims": len(store.claims),
        "active_claims": sum(1 for claim in store.claims.values() if claim["status"] == "active"),
        "superseded_claims": sum(1 for claim in store.claims.values() if claim["status"] == "superseded"),
        "metrics": {key: value for key, value in report.items() if key != "queries"},
        "query_results": report["queries"],
    }
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    print(payload)


if __name__ == "__main__":
    main()
