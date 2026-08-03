"""标准 evidence {segment_id} 结构的硬校验回归。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
PROVIDER_ROOT = MODULE_ROOT.parent / "llm-providers"
for path in (MODULE_ROOT.parent, MODULE_ROOT, PROVIDER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

try:
    from .schema import validate_artifact  # noqa: E402
except ImportError:  # unittest discover -s intelligence imports this as a top-level module
    from intelligence.schema import validate_artifact  # type: ignore  # noqa: E402


class TestEvidenceSchema(unittest.TestCase):
    def test_segment_id_evidence_is_accepted_and_checked(self) -> None:
        meeting = {"meeting_id": "m1", "tenant_id": "t1"}
        segments = [{"segment_id": "s1", "meeting_id": "m1", "tenant_id": "t1"}]
        base = {
            "schema_version": "meeting-artifact-v1", "meeting_id": "m1", "tenant_id": "t1", "summary": "x",
            "topics": [], "chapters": [], "facts": [], "decisions": [], "action_items": [], "risks": [],
            "open_questions": [], "keywords": [], "claims": [], "evidence": [{"segment_id": "s1"}],
        }
        self.assertTrue(validate_artifact(base, meeting=meeting, segments=segments).valid)
        base["evidence"] = [{"segment_id": "missing"}]
        report = validate_artifact(base, meeting=meeting, segments=segments)
        self.assertFalse(report.valid)
        self.assertTrue(any("unknown segment_id" in issue for issue in report.issues))


if __name__ == "__main__":
    unittest.main()
