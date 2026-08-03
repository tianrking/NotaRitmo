from __future__ import annotations

import unittest
from pathlib import Path

from answerers import GroundedLLMAnswerer, TemplateAnswerer
from engine import FixtureRuleExtractor, load_fixture
from llm import LLMNotConfiguredError, OfflineLLMProvider, StaticLLMProvider
from retrievers import LexicalRetriever
from service import MeetingMemoryService


FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "meeting-memory-fixture-10"


class PluggableCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = load_fixture(FIXTURE_ROOT)

    def test_default_service_is_offline_and_regression_compatible(self) -> None:
        service = MeetingMemoryService.from_fixture(self.fixture)
        self.assertEqual(len(service.repository.meetings), 10)
        self.assertEqual(len(service.repository.segments), 60)
        result = service.answer(
            "现在生产检索的主链路是什么？",
            "tenant_alpha",
            "current_state",
        )
        self.assertFalse(result["no_answer"])
        self.assertEqual(result["retrieval_mode"], "offline_lexical_token_baseline")
        self.assertEqual(result["answer_mode"], "offline_template")
        self.assertTrue(result["citations"])

    def test_dependencies_are_constructor_injected(self) -> None:
        service = MeetingMemoryService.from_fixture(
            self.fixture,
            extractor=FixtureRuleExtractor(),
            answerer=TemplateAnswerer(),
        )
        self.assertIsInstance(service.retriever, LexicalRetriever)
        self.assertIsInstance(service.answerer, TemplateAnswerer)
        self.assertIsInstance(service.extractor, FixtureRuleExtractor)

    def test_grounded_llm_changes_only_wording(self) -> None:
        llm = StaticLLMProvider("经证据核验，生产检索使用 PostgreSQL 全文检索加 pgvector。")
        service = MeetingMemoryService.from_fixture(
            self.fixture,
            answerer=GroundedLLMAnswerer(llm),
        )
        result = service.answer(
            "现在生产检索的主链路是什么？",
            "tenant_alpha",
            "current_state",
        )
        self.assertFalse(result["no_answer"])
        self.assertEqual(result["answer_mode"], "llm_grounded")
        self.assertIn("PostgreSQL", result["answer"])
        self.assertTrue(result["citations"])
        self.assertEqual(result["llm"]["provider"], "static")

    def test_provider_injection_selects_grounded_answerer(self) -> None:
        llm = StaticLLMProvider("由注入的模型生成，但仅基于证据。")
        service = MeetingMemoryService.from_fixture(
            self.fixture,
            llm_provider=llm,
        )
        result = service.answer(
            "现在生产检索的主链路是什么？",
            "tenant_alpha",
            "current_state",
        )
        self.assertEqual(result["answer_mode"], "llm_grounded")
        self.assertTrue(result["citations"])

    def test_offline_provider_never_falls_back_to_network(self) -> None:
        with self.assertRaises(LLMNotConfiguredError):
            OfflineLLMProvider().generate(
                system_prompt="",
                user_prompt="",
            )


if __name__ == "__main__":
    unittest.main()
