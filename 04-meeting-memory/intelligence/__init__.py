"""单会议理解：可选 LLM 抽取、固定 Artifact schema 和证据硬校验。"""

from __future__ import annotations

import sys
from pathlib import Path

# llm-providers 是平台横向基础设施，不复制到本模块。源码运行时把 sibling
# package 放入路径；正式部署应安装该 package（或由 PYTHONPATH 提供）。
_provider_root = Path(__file__).resolve().parents[1].parent / "llm-providers"
if _provider_root.exists() and str(_provider_root) not in sys.path:
    sys.path.insert(0, str(_provider_root))

from .extractor import ExtractionFailed, ExtractionOutcome, ExtractionStatus, MeetingArtifactExtractor
from .schema import ArtifactValidationError, ValidationReport, require_valid_artifact, validate_artifact

__all__ = [
    "ArtifactValidationError",
    "ExtractionFailed",
    "ExtractionOutcome",
    "ExtractionStatus",
    "MeetingArtifactExtractor",
    "ValidationReport",
    "require_valid_artifact",
    "validate_artifact",
]
