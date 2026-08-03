"""可选 LLM Provider 与固定 Fixture 评估工具。

该目录可以直接复制到
``04-meeting-memory/baseline/evaluation``。实现只依赖 Python 标准库，默认
不会联网；只有显式选择 ``OpenAICompatibleProvider`` 时才会调用远端端点。
"""

from .provider import (
    FixtureReplayProvider,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
    ProviderError,
    Usage,
    build_answer_request,
    build_meeting_extraction_request,
)

__all__ = [
    "FixtureReplayProvider",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "OpenAICompatibleConfig",
    "OpenAICompatibleProvider",
    "ProviderError",
    "Usage",
    "build_answer_request",
    "build_meeting_extraction_request",
]
