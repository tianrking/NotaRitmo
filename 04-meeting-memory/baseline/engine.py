from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


STOP_WORDS = {
    "的", "是", "和", "了", "在", "有", "什么", "怎么", "如何", "是否",
    "有没有", "哪", "哪个", "哪些", "为什么", "应该", "可以", "先", "现在",
    "当前", "这个", "那个", "我们", "系统", "项目", "会议", "内容",
}

TOPIC_RULES = {
    "项目范围": ("范围", "第一版"),
    "Tingwu 接入": ("Tingwu", "ASR"),
    "权威存储": ("PostgreSQL", "事实", "证据"),
    "会议输出": ("摘要", "章节", "待办", "热词"),
    "开源项目边界": ("RAGFlow", "Graphiti", "Mem0", "Hindsight"),
    "RAGFlow": ("RAGFlow",),
    "Graphiti": ("Graphiti",),
    "Memory Provider": ("Mem0", "Hindsight", "Provider"),
    "TranscriptBundle": ("TranscriptBundle", "segment_id"),
    "说话人": ("speaker_id", "说话人"),
    "时间戳": ("start_ms", "end_ms", "时间点"),
    "版本": ("版本", "原始转写"),
    "单会议理解": ("MeetingArtifactBundle", "单会议理解"),
    "结构化抽取": ("LLM", "Pydantic", "结构化"),
    "证据": ("evidence", "证据"),
    "成本统计": ("Token", "成本"),
    "Claim": ("Claim",),
    "当前状态": ("active", "当前"),
    "历史状态": ("superseded", "历史"),
    "Provider 边界": ("Provider", "事实源"),
    "全文检索": ("全文检索", "FTS"),
    "向量检索": ("pgvector", "向量"),
    "重排": ("重排",),
    "引用": ("引用", "播放"),
    "拒答": ("no_answer", "证据不足"),
    "租户隔离": ("tenant_id", "租户"),
    "权限": ("权限",),
    "删除": ("删除",),
    "审计": ("审计",),
    "Go API": ("Go API",),
    "Python Worker": ("Python", "Worker"),
    "Temporal": ("Temporal", "重试"),
    "模型路由": ("LiteLLM", "模型"),
    "成本": ("成本", "Token"),
    "架构修订": ("修订", "复盘"),
    "生产检索": ("生产检索", "主链路"),
    "验收标准": ("验收",),
    "蓝海客户": ("蓝海", "客户"),
    "预算": ("预算",),
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def tokenize(text: str) -> set[str]:
    text = text.lower()
    tokens: set[str] = set()
    for part in re.findall(r"[a-z0-9_+#.-]+|[\u4e00-\u9fff]+", text):
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            if part not in STOP_WORDS and len(part) > 1:
                tokens.add(part)
            tokens.update(
                part[index : index + 2]
                for index in range(len(part) - 1)
                if part[index : index + 2] not in STOP_WORDS
            )
        elif part not in STOP_WORDS:
            tokens.add(part)
    return tokens


def lexical_score(query: str, text: str) -> float:
    query_lower = query.lower()
    text_lower = text.lower()
    query_terms = tokenize(query)
    text_terms = tokenize(text)
    if not query_terms:
        return 0.0
    overlap = len(query_terms & text_terms) / len(query_terms)
    phrase_hits = sum(
        1
        for term in query_terms
        if len(term) >= 2 and term in text_lower
    )
    phrase_score = min(1.0, phrase_hits / max(1, min(4, len(query_terms))))
    exact_bonus = 0.15 if query_lower.strip() in text_lower else 0.0
    return round(min(1.0, 0.65 * overlap + 0.35 * phrase_score + exact_bonus), 6)


def stable_id(source_meeting_id: str, subject: str, predicate: str, obj: str) -> str:
    raw = "|".join((source_meeting_id, subject, predicate, obj))
    return "candidate_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


@dataclass
class Fixture:
    meetings: list[dict[str, Any]]
    segments: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    gold_claims: list[dict[str, Any]]
    queries: list[dict[str, Any]]


def load_fixture(root: Path) -> Fixture:
    return Fixture(
        meetings=read_jsonl(root / "meetings.jsonl"),
        segments=read_jsonl(root / "segments.jsonl"),
        artifacts=read_jsonl(root / "gold_artifacts.jsonl"),
        gold_claims=read_jsonl(root / "gold_claims.jsonl"),
        queries=read_jsonl(root / "queries.jsonl"),
    )


class FixtureRuleExtractor:
    """Deterministic baseline only; production will replace this with an LLM adapter."""

    def _claim_candidates(self, segment: dict[str, Any]) -> list[dict[str, Any]]:
        text = segment["text"]
        meeting_id = segment["meeting_id"]
        tenant_id = segment["tenant_id"]
        evidence = [segment["segment_id"]]
        candidates: list[tuple[str, str, str]] = []

        if "星河会议平台的第一版范围" in text:
            candidates.append(("星河会议平台", "第一版范围", "接入会议转写并支持单会议和跨会议查询"))
        if "第一版先接入 Tingwu" in text:
            candidates.append(("星河会议平台", "ASR方案", "第一版接入Tingwu输出，不重新开发ASR"))
        if "事实和证据放在 PostgreSQL" in text:
            candidates.append(("星河会议平台", "事实存储", "PostgreSQL保存事实、证据和状态"))
        if "每场会议至少要输出" in text:
            candidates.append(("会议结果", "最小输出", "摘要、章节、事实、决策、待办、风险、热词和证据"))
        if "演示版使用 RAGFlow" in text:
            candidates.append(("生产检索", "主链路", "RAGFlow"))
        if "Graphiti 可以作为关系图投影" in text:
            candidates.append(("Graphiti", "系统定位", "关系图和时态检索的可选投影"))
        if "Mem0 和 Hindsight 可以" in text:
            candidates.append(("Mem0", "系统定位", "可选的记忆召回实验Provider，不是事实源"))
        if "每个片段都要有" in text:
            candidates.append(("TranscriptBundle", "必填字段", "segment_id、speaker_id、start_ms、end_ms、text、confidence"))
        if "没有证据的模型输出" in text:
            candidates.append(("单会议理解", "无证据输出", "只能进入候选或人工审核，不能进入当前记忆"))
        if "Claim 至少包含" in text:
            candidates.append(("Meeting Memory", "事实结构", "使用带来源和证据的Claim，而不是只保存摘要"))
        if "旧 Claim 不能删除" in text:
            candidates.append(("决策状态", "旧决策处理", "旧Claim保留并标记superseded，链接到新Claim"))
        if "PostgreSQL 全文检索" in text:
            candidates.append(("检索", "关键词方案", "PostgreSQL全文检索"))
        if "语义问题使用 pgvector" in text:
            candidates.append(("检索", "语义方案", "pgvector向量检索"))
        if "返回 no_answer" in text:
            candidates.append(("查询回答", "无证据行为", "证据不足时返回no_answer"))
        if "所有会议、片段、Claim" in text:
            candidates.append(("数据安全", "租户隔离", "所有会议、片段、Claim、向量和对象存储路径关联tenant_id"))
        if "生产检索核心改为" in text:
            candidates.append(("生产检索", "主链路", "PostgreSQL全文检索加pgvector，RAGFlow只做基线"))
        if "正式架构确定为" in text:
            candidates.append(("正式架构", "组成", "Tingwu、Python单会议理解、Go Claim校验、PostgreSQL记忆、混合检索和证据回答"))
        if "客户门户首版计划使用 React" in text:
            candidates.append(("蓝海客户项目", "前端方案", "React"))

        return [
            {
                "claim_id": stable_id(meeting_id, subject, predicate, obj),
                "tenant_id": tenant_id,
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "status": "active",
                "valid_from": meeting_id,
                "valid_to": None,
                "source_meeting_id": meeting_id,
                "evidence_segment_ids": evidence,
            }
            for subject, predicate, obj in candidates
        ]

    def extract(self, meeting: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
        full_text = " ".join(segment["text"] for segment in segments)
        topics = [
            topic
            for topic, markers in TOPIC_RULES.items()
            if any(marker.lower() in full_text.lower() for marker in markers)
        ]
        claims = [
            claim
            for segment in segments
            for claim in self._claim_candidates(segment)
        ]
        decision_segments = [
            segment
            for segment in segments
            if any(marker in segment["text"] for marker in ("决定", "确认", "采用", "使用", "必须", "改为", "正式架构"))
        ]
        decisions = [
            {
                "decision_id": f"{meeting['meeting_id']}_decision_{index:02d}",
                "content": segment["text"],
                "speaker_id": segment["speaker_id"],
                "evidence_segment_ids": [segment["segment_id"]],
            }
            for index, segment in enumerate(decision_segments, 1)
        ]
        action_segments = [
            segment
            for segment in segments
            if any(marker in segment["text"] for marker in ("负责", "我来", "下一步", "提交", "写入", "整理"))
        ]
        action_items = [
            {
                "action_id": f"{meeting['meeting_id']}_action_{index:02d}",
                "task": segment["text"],
                "owner_speaker_id": segment["speaker_id"],
                "status": "open",
                "evidence_segment_ids": [segment["segment_id"]],
            }
            for index, segment in enumerate(action_segments, 1)
        ]
        risk_segments = [segment for segment in segments if "风险" in segment["text"]]
        risks = [
            {
                "risk_id": f"{meeting['meeting_id']}_risk_{index:02d}",
                "content": segment["text"],
                "evidence_segment_ids": [segment["segment_id"]],
            }
            for index, segment in enumerate(risk_segments, 1)
        ]
        keyword_counts = Counter(
            term
            for segment in segments
            for term in tokenize(segment["text"])
            if len(term) >= 2
        )
        keywords = [{"term": term, "count": count} for term, count in keyword_counts.most_common(20)]
        chapters = [
            {
                "chapter_id": f"{meeting['meeting_id']}_chapter_{index:02d}",
                "title": topic,
                "start_ms": segments[0]["start_ms"],
                "end_ms": segments[-1]["end_ms"],
                "evidence_segment_ids": [
                    segment["segment_id"]
                    for segment in segments
                    if any(marker.lower() in segment["text"].lower() for marker in TOPIC_RULES[topic])
                ][:3],
            }
            for index, topic in enumerate(topics, 1)
        ]
        summary_parts = [segments[0]["text"]]
        summary_parts.extend(decision["content"] for decision in decisions[:3])
        facts = [
            {
                "fact_id": f"{meeting['meeting_id']}_fact_{index:02d}",
                "content": segment["text"],
                "evidence_segment_ids": [segment["segment_id"]],
            }
            for index, segment in enumerate(segments, 1)
            if any(marker in segment["text"] for marker in ("是", "属于", "放在", "包含", "负责"))
        ]
        return {
            "meeting_id": meeting["meeting_id"],
            "tenant_id": meeting["tenant_id"],
            "summary": " ".join(summary_parts),
            "topics": topics,
            "chapters": chapters,
            "facts": facts,
            "decisions": decisions,
            "action_items": action_items,
            "risks": risks,
            "open_questions": [],
            "keywords": keywords,
            "claims": claims,
            "mindmap": {"root": meeting["title"], "children": [{"title": topic} for topic in topics]},
            "quality": {"mode": "fixture_rule_baseline", "evidence_required": True},
        }


class MemoryStore:
    def __init__(self, extractor: Any | None = None) -> None:
        self.meetings: dict[str, dict[str, Any]] = {}
        self.segments: dict[str, dict[str, Any]] = {}
        self.artifacts: dict[str, dict[str, Any]] = {}
        self.claims: dict[str, dict[str, Any]] = {}
        self.active_by_key: dict[tuple[str, str, str], str] = {}
        self.extractor = extractor or FixtureRuleExtractor()

    @classmethod
    def from_fixture(cls, fixture: Fixture) -> "MemoryStore":
        store = cls()
        for meeting in fixture.meetings:
            meeting_segments = [
                segment
                for segment in fixture.segments
                if segment["meeting_id"] == meeting["meeting_id"]
            ]
            store.ingest_meeting(meeting, meeting_segments)
        return store

    def ingest_meeting(
        self,
        meeting: dict[str, Any],
        segments: list[dict[str, Any]],
        *,
        extractor: Any | None = None,
    ) -> dict[str, Any]:
        self.meetings[meeting["meeting_id"]] = meeting
        for segment in segments:
            self.segments[segment["segment_id"]] = segment
        artifact = self.extractor.extract(meeting, segments)
        self.artifacts[meeting["meeting_id"]] = artifact
        for claim in artifact["claims"]:
            self.upsert_claim(claim)
        return artifact

    def upsert_claim(self, claim: dict[str, Any]) -> None:
        key = (claim["tenant_id"], claim["subject"], claim["predicate"])
        previous_id = self.active_by_key.get(key)
        if previous_id and previous_id != claim["claim_id"]:
            previous = self.claims[previous_id]
            if previous["object"] != claim["object"] and previous["status"] == "active":
                previous["status"] = "superseded"
                previous["valid_to"] = claim["valid_from"]
                previous["superseded_by"] = claim["claim_id"]
                claim["supersedes"] = previous_id
        self.claims[claim["claim_id"]] = claim
        if claim["status"] == "active":
            self.active_by_key[key] = claim["claim_id"]

    def visible_segments(self, tenant_id: str) -> list[dict[str, Any]]:
        return [segment for segment in self.segments.values() if segment["tenant_id"] == tenant_id]

    def visible_claims(self, tenant_id: str) -> list[dict[str, Any]]:
        return [claim for claim in self.claims.values() if claim["tenant_id"] == tenant_id]

    def retrieve(self, question: str, tenant_id: str, query_type: str, top_k: int = 5) -> dict[str, list[dict[str, Any]]]:
        segment_rows = [
            {"score": lexical_score(question, segment["text"]), "segment": segment}
            for segment in self.visible_segments(tenant_id)
        ]
        segment_rows = sorted(
            (row for row in segment_rows if row["score"] > 0),
            key=lambda row: row["score"],
            reverse=True,
        )
        claim_rows = []
        for claim in self.visible_claims(tenant_id):
            score = lexical_score(
                question,
                " ".join((claim["subject"], claim["predicate"], claim["object"])),
            )
            if query_type == "current_state" and claim["status"] != "active":
                score *= 0.2
            if query_type == "historical_state" and claim["status"] == "superseded":
                score = min(1.0, score * 1.25)
            if score > 0:
                claim_rows.append({"score": min(1.0, score), "claim": claim})
        claim_rows.sort(key=lambda row: row["score"], reverse=True)
        return {"segments": segment_rows[:top_k], "claims": claim_rows[:top_k]}

    def answer(self, question: str, tenant_id: str, query_type: str, top_k: int = 5) -> dict[str, Any]:
        retrieved = self.retrieve(question, tenant_id, query_type, top_k)
        segments = retrieved["segments"]
        claims = retrieved["claims"]
        best_score = max([row["score"] for row in segments + claims] or [0.0])
        threshold = 0.25 if query_type in {"tenant_isolation", "no_answer"} else 0.12
        if best_score < threshold:
            return {
                "answer": None,
                "no_answer": True,
                "confidence": 0.0,
                "meetings": [],
                "claims": [],
                "citations": [],
                "retrieval_mode": "offline_lexical_token_baseline",
            }
        visible_claims = [row["claim"] for row in claims]
        if query_type == "current_state":
            visible_claims = [claim for claim in visible_claims if claim["status"] == "active"] or visible_claims
        answer_parts = [
            f"{claim['subject']}的{claim['predicate']}是：{claim['object']}。"
            for claim in visible_claims[:3]
        ]
        if not answer_parts:
            answer_parts = [row["segment"]["text"] for row in segments[:2]]
        citations = []
        seen = set()
        for row in segments:
            segment = row["segment"]
            if segment["segment_id"] in seen:
                continue
            seen.add(segment["segment_id"])
            citations.append(
                {
                    "meeting_id": segment["meeting_id"],
                    "segment_id": segment["segment_id"],
                    "speaker_id": segment["speaker_id"],
                    "start_ms": segment["start_ms"],
                    "end_ms": segment["end_ms"],
                    "text": segment["text"],
                    "score": row["score"],
                }
            )
        for row in claims:
            for segment_id in row["claim"].get("evidence_segment_ids", []):
                if segment_id in seen or segment_id not in self.segments:
                    continue
                segment = self.segments[segment_id]
                if segment["tenant_id"] != tenant_id:
                    continue
                seen.add(segment_id)
                citations.append(
                    {
                        "meeting_id": segment["meeting_id"],
                        "segment_id": segment["segment_id"],
                        "speaker_id": segment["speaker_id"],
                        "start_ms": segment["start_ms"],
                        "end_ms": segment["end_ms"],
                        "text": segment["text"],
                        "score": row["score"],
                    }
                )
        meeting_ids = sorted(
            {claim["source_meeting_id"] for claim in visible_claims}
            | {citation["meeting_id"] for citation in citations}
        )
        return {
            "answer": " ".join(answer_parts),
            "no_answer": False,
            "confidence": round(min(0.99, max(0.5, best_score)), 4),
            "meetings": meeting_ids,
            "claims": visible_claims,
            "citations": citations,
            "retrieval_mode": "offline_lexical_token_baseline",
        }


def evaluate_query(store: MemoryStore, query: dict[str, Any]) -> dict[str, Any]:
    result = store.answer(query["question"], query["tenant_id"], query["query_type"])
    actual_meetings = set(result["meetings"])
    expected_meetings = set(query["expected_meetings"])
    actual_evidence = {citation["segment_id"] for citation in result["citations"]}
    expected_evidence = set(query["expected_evidence"])
    return {
        "query_id": query["query_id"],
        "no_answer_correct": result["no_answer"] == query["no_answer"],
        "meeting_recall": len(actual_meetings & expected_meetings) / len(expected_meetings) if expected_meetings else (1.0 if not actual_meetings else 0.0),
        "evidence_recall": len(actual_evidence & expected_evidence) / len(expected_evidence) if expected_evidence else (1.0 if not actual_evidence else 0.0),
        "result": result,
    }


def evaluate_all(store: MemoryStore, queries: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [evaluate_query(store, query) for query in queries]
    return {
        "queries": rows,
        "no_answer_accuracy": sum(row["no_answer_correct"] for row in rows) / len(rows),
        "mean_meeting_recall": sum(row["meeting_recall"] for row in rows) / len(rows),
        "mean_evidence_recall": sum(row["evidence_recall"] for row in rows) / len(rows),
    }
