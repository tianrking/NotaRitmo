#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

BASE = os.getenv("MEETING_API_BASE", "http://127.0.0.1:4200").rstrip("/")
CORPUS_VERSION = "public-interviews-v1"
REQUIRED_ARTIFACTS = {
    "summary",
    "detailed_summary",
    "facts",
    "chapters",
    "action_items",
    "decisions",
    "risks",
    "open_questions",
    "keywords",
    "wordcloud",
    "mindmap",
    "speaker_stats",
    "key_information",
}

# These are short Chinese adaptations of facts in public interview transcripts.
# They intentionally preserve the Q&A shape while avoiding wholesale reproduction.
ARTICLES: list[dict[str, Any]] = [
    {
        "key": "nasa_shirley",
        "title": "公开访谈ASR验收｜Donna Shirley谈火星车与机器人AI",
        "project_id": f"{CORPUS_VERSION}-ai-space",
        "source_url": (
            "https://www.nasa.gov/wp-content/uploads/2025/08/"
            "shirleydl-7-17-01.pdf"
        ),
        "source_name": "NASA Oral History: Donna L. Shirley, 2001-07-17",
        "utterances": [
            ("1", "采访者：火星车项目中的计算机能力和人工智能发生了什么变化？"),
            ("2", "雪莉：早期研究者曾预计人工智能进展会更快，但实际发展比预期缓慢。"),
            (
                "2",
                "雪莉：大型Robby火星车用多台摄像机扫描地形，分析高程并选择危险最少的路径。",
            ),
            ("1", "采访者：这种自主规划在当时面临的主要风险是什么？"),
            ("2", "雪莉：当时完成环境分析和路径规划需要非常庞大的计算资源。"),
            (
                "2",
                "雪莉：Rod Brooks建议不要让机器人像人一样思考，而是像昆虫一样组合简单行为。",
            ),
            (
                "2",
                "雪莉：行走和避障等行为逐层覆盖，形成了后来所称的包容式分层架构。",
            ),
            ("2", "雪莉：JPL的小机器人FANG和Tooth已经尝试了这类简单行为。"),
            (
                "2",
                "雪莉：团队把Tooth的控制逻辑装到Rocky六轮摇臂车体上，验证小型户外火星车。",
            ),
            (
                "2",
                "雪莉：Rocky演示推动了微型火星车项目，后来需要借助Pathfinder任务搭载飞行。",
            ),
        ],
    },
    {
        "key": "nasa_erb",
        "title": "公开访谈ASR验收｜Bryan Erb谈遥感、自动化与空间站",
        "project_id": f"{CORPUS_VERSION}-ai-space",
        "source_url": (
            "https://www.nasa.gov/wp-content/uploads/2025/07/"
            "erbrb-10-14-99.pdf"
        ),
        "source_name": "NASA JSC Oral History: R. Bryan Erb, 1999-10-14",
        "utterances": [
            ("1", "采访者：你在地球遥感工作后期遇到了什么组织问题？"),
            (
                "2",
                "厄布：总部缺少持续支持，而一个约百人的部门每年需要数百万美元维持。",
            ),
            (
                "2",
                "厄布：中心最终决定撤销该部门，我理解这个决定，并因此考虑提前退休。",
            ),
            ("1", "采访者：遥感工作与人工智能有什么联系？"),
            (
                "2",
                "厄布：面对巨大的地球观测数据流，核心问题是怎样高效抽取真正需要的信息。",
            ),
            (
                "2",
                "厄布：自动化、机器人和人工智能被视为提升产业竞争力的关键技术。",
            ),
            (
                "2",
                "厄布：Jake Garn建议利用空间站提出足够困难的任务，以推动这些技术进步。",
            ),
            (
                "2",
                "厄布：NASA在一九八四年前后成立高级技术咨询委员会，Aaron Cohen担任主席。",
            ),
            (
                "1",
                "采访者：卫星遥感等技术被社会采用之后，公众还会注意到它们吗？",
            ),
            (
                "2",
                "厄布：成熟技术往往退到背景中，例如跨洋通信和导航已依赖卫星却不易被察觉。",
            ),
        ],
    },
    {
        "key": "nih_horigan",
        "title": "公开访谈ASR验收｜John Horigan谈All of Us精准医疗项目",
        "project_id": f"{CORPUS_VERSION}-health",
        "source_url": (
            "https://history.nih.gov/collections/oral-histories/"
            "horigan-john-2023/"
        ),
        "source_name": "NIH Oral History: John Horigan, 2023-12-11",
        "utterances": [
            ("1", "采访者：All of Us项目早期与精准医疗计划有什么关系？"),
            (
                "2",
                "霍里根：项目与精准医疗和癌症登月计划同期发展，早期名称还不是All of Us。",
            ),
            (
                "2",
                "霍里根：早期伦理审查工作关注电子知情同意、社区意见和联邦人体研究规则。",
            ),
            ("1", "采访者：项目目前扩大覆盖范围的进度怎样？"),
            (
                "2",
                "霍里根：参与站点已经扩展到更多地区，个人也可以从美国不同地方申请加入。",
            ),
            (
                "2",
                "霍里根：当时参与人数已经超过七十万，项目目标是一百万人以上。",
            ),
            (
                "2",
                "霍里根：偏远和医疗资源不足地区仍存在交通与数字接入风险，需要社区组织协助。",
            ),
            (
                "2",
                "霍里根：有些人去最近的学术医疗中心单程需要两小时，这会阻碍持续参与。",
            ),
            (
                "2",
                "霍里根：为了获得足够规模和多样性的数据，他提出把人数上限提高到两百万。",
            ),
            (
                "2",
                "霍里根：项目整合电子健康记录、生物样本和测序数据，并向研究机构共享。",
            ),
        ],
    },
    {
        "key": "nih_grady",
        "title": "公开访谈ASR验收｜Christine Grady谈临床生物伦理",
        "project_id": f"{CORPUS_VERSION}-health",
        "source_url": (
            "https://history.nih.gov/collections/oral-histories/"
            "grady-christine-2025/"
        ),
        "source_name": "NIH Oral History: Christine Grady, 2025-09-25",
        "utterances": [
            ("1", "采访者：早期护理经历怎样影响了你对生物伦理的兴趣？"),
            (
                "2",
                "格雷迪：急诊、社区、国际和临终关怀工作不断带来难以直接回答的伦理问题。",
            ),
            (
                "2",
                "格雷迪：这些问题包括资源如何分配、怎样帮助临终患者，以及如何平衡个人利益和公共卫生要求。",
            ),
            (
                "2",
                "格雷迪：当时生物伦理还不普及，我希望获得一种更有结构的方法进行判断。",
            ),
            ("1", "采访者：临床中心最初怎样看待一九九六年成立的生物伦理部门？"),
            (
                "2",
                "格雷迪：开始时有怀疑，但咨询服务解决了实际问题，使用者不断回来并推荐给同事。",
            ),
            (
                "2",
                "格雷迪：部门确定咨询、严谨研究和人才培养是相互支持的三项工作。",
            ),
            (
                "2",
                "格雷迪：研究证明生物伦理不只提供观点，也能通过严谨方法形成临床指导。",
            ),
            (
                "2",
                "格雷迪：培养项目从一两名学员逐步扩大，后来约有八名教师和十二名学员。",
            ),
            (
                "2",
                "格雷迪：当前挑战是让科学家和临床人员理解生物伦理如何真正帮助决策。",
            ),
        ],
    },
    {
        "key": "npc_solar",
        "title": "公开访谈ASR验收｜黄鸣谈新能源技术与太阳能产业",
        "project_id": f"{CORPUS_VERSION}-energy",
        "source_url": (
            "https://www.npc.gov.cn/zgrdw/npc/zxft/jkkfxny/node_15742.htm"
        ),
        "source_name": "中国人大网在线访谈：健康开发新能源，2011-03-06",
        "utterances": [
            ("1", "采访者：先进新能源技术曾集中在发达国家，中国怎样提高自主研发能力？"),
            (
                "2",
                "黄鸣：早期光伏制造、大功率风机和海上风机确实落后，但这些领域已经逐步追赶。",
            ),
            (
                "2",
                "黄鸣：太阳能光热经过近二十年发展，在研发、设备和应用服务方面形成了完整产业体系。",
            ),
            (
                "1",
                "采访者：太阳能光热已经形成了哪些具有代表性的应用？",
            ),
            (
                "2",
                "黄鸣：太阳能热水器约占世界总量的百分之七十六，这是产业规模的重要事实。",
            ),
            (
                "2",
                "黄鸣：应用已经扩展到采暖、制冷、烘干、工业蒸汽以及中高温场景。",
            ),
            (
                "2",
                "黄鸣：技术进步之外仍有公众认知不足的问题，市场教育需要继续加强。",
            ),
            (
                "1",
                "采访者：新能源推广是否只依靠企业投资就可以完成？",
            ),
            (
                "2",
                "黄鸣：企业、公众和政策需要共同推动，生活方式变化也会影响能源转型。",
            ),
        ],
    },
    {
        "key": "ajph_kasich",
        "title": "公开访谈ASR验收｜John Kasich谈公共卫生",
        "project_id": f"{CORPUS_VERSION}-health",
        "source_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC8961818/",
        "source_name": "AJPH Interview: What Is Public Health?, 2022",
        "utterances": [
            ("1", "采访者：你怎样定义公共卫生？"),
            (
                "2",
                "卡西奇：公共卫生是维护社区整体健康，包括疫苗、餐饮卫生和其他预防工作。",
            ),
            ("1", "采访者：为什么公众平时不容易理解公共卫生？"),
            (
                "2",
                "卡西奇：体系正常运行时它往往不被注意，发生饮水污染等危机后人们才意识到其价值。",
            ),
            (
                "2",
                "卡西奇：长期风险是公共卫生预算不足，基层工作人员难以持续完成任务。",
            ),
            (
                "2",
                "卡西奇：我建议设置公共卫生日，用更直观的方式向社区解释日常预防工作。",
            ),
            ("1", "采访者：公共卫生应该主要由联邦政府统一管理吗？"),
            (
                "2",
                "卡西奇：它首先是地方事务，联邦政府可以提供资金方向和资源，但必须保持问责。",
            ),
            (
                "2",
                "卡西奇：公共卫生具有预防性质，应该像持续缴纳保险一样成为年度预算的固定优先事项。",
            ),
        ],
    },
]

RETRIEVAL_CASES: list[dict[str, Any]] = [
    {
        "name": "semantic_robot_insect",
        "query": "哪篇访谈谈到让机器人像昆虫一样用分层行为完成避障？",
        "expected": ["nasa_shirley"],
        "k": 1,
    },
    {
        "name": "exact_tooth_rocky",
        "query": "哪篇访谈说把Tooth的控制逻辑装到Rocky车体上？",
        "expected": ["nasa_shirley"],
        "k": 1,
    },
    {
        "name": "space_station_automation",
        "query": "空间站为什么被当作推动自动化和机器人技术的载体？",
        "expected": ["nasa_erb"],
        "k": 1,
    },
    {
        "name": "precision_medicine_scale",
        "query": "哪个项目已经有七十多万参与者，并以一百万人为目标？",
        "expected": ["nih_horigan"],
        "k": 1,
    },
    {
        "name": "bioethics_end_of_life",
        "query": "谁谈到资源分配、临终照护和个人利益与公共卫生之间的平衡？",
        "expected": ["nih_grady"],
        "k": 1,
    },
    {
        "name": "solar_76_percent",
        "query": "哪篇访谈提到太阳能热水器占世界总量百分之七十六？",
        "expected": ["npc_solar"],
        "k": 1,
    },
    {
        "name": "public_health_insurance",
        "query": "哪篇访谈把公共卫生比作需要持续缴费的保险？",
        "expected": ["ajph_kasich"],
        "k": 1,
    },
    {
        "name": "cross_ai_robotics",
        "query": "哪些访谈讨论了人工智能、机器人、自动化和计算资源？",
        "expected": ["nasa_shirley", "nasa_erb"],
        "k": 4,
    },
    {
        "name": "cross_health_ethics",
        "query": "哪些访谈讨论医疗研究参与者、临床伦理或公共卫生？",
        "expected": ["nih_horigan", "nih_grady", "ajph_kasich"],
        "k": 6,
    },
    {
        "name": "negative_ota",
        "query": "哪篇访谈决定K6 OTA采用灰度分包发布？",
        "expected": [],
        "k": 6,
    },
]


def request(method: str, path: str, payload: dict | None = None) -> Any:
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.loads(response.read())


def simulated_tingwu_payload(article: dict[str, Any]) -> dict[str, Any]:
    paragraphs = []
    start_ms = 1000
    word_id = 1
    for sentence_id, (speaker_id, text) in enumerate(article["utterances"], 1):
        duration_ms = max(1800, min(6000, len(text) * 110))
        end_ms = start_ms + duration_ms
        paragraphs.append(
            {
                "ParagraphId": f"p{sentence_id}",
                "SpeakerId": speaker_id,
                "Words": [
                    {
                        "Id": word_id,
                        "SentenceId": sentence_id,
                        "Start": start_ms,
                        "End": end_ms,
                        "Text": text,
                        "Confidence": round(0.97 - (sentence_id % 5) * 0.015, 3),
                    }
                ],
            }
        )
        word_id += 1
        start_ms = end_ms + 350
    duration_ms = start_ms + 1000
    return {
        "title": article["title"],
        "project_id": article["project_id"],
        "audio_uri": article["source_url"],
        "source_language": "cn",
        "raw_result": {
            "Transcription": {
                "TaskId": f"{CORPUS_VERSION}-{article['key']}",
                "Transcription": {
                    "AudioInfo": {
                        "Duration": duration_ms,
                        "SampleRate": 16000,
                        "Language": "cn",
                    },
                    "Paragraphs": paragraphs,
                    "AudioSegments": [[1000, duration_ms - 1000]],
                },
            },
            "_Source": {
                "name": article["source_name"],
                "url": article["source_url"],
                "adaptation": "short Chinese factual adaptation for ASR retrieval testing",
            },
        },
    }


def wait_ready(meeting_id: str, timeout: int = 600) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        meeting = request("GET", f"/v1/meetings/{meeting_id}")
        if meeting["status"] == "READY" and meeting["graph_status"] == "READY":
            return meeting
        if meeting["status"] == "FAILED" or meeting["graph_status"] == "FAILED":
            raise RuntimeError(f"meeting processing failed: {meeting}")
        time.sleep(1)
    raise TimeoutError(f"meeting did not become READY: {meeting_id}")


def ensure_corpus(*, force: bool = False) -> dict[str, dict[str, Any]]:
    existing = request("GET", "/v1/meetings")
    selected: dict[str, dict[str, Any]] = {}
    for article in ARTICLES:
        reusable = next(
            (
                item
                for item in existing
                if not force
                and item["title"] == article["title"]
                and item["project_id"] == article["project_id"]
                and item["status"] == "READY"
                and item["graph_status"] == "READY"
            ),
            None,
        )
        if reusable:
            meeting = reusable
            imported = False
        else:
            meeting = request(
                "POST", "/v1/meetings/import/tingwu", simulated_tingwu_payload(article)
            )
            meeting = wait_ready(meeting["id"])
            imported = True
        selected[article["key"]] = {**meeting, "imported": imported}
    return selected


def ordered_meeting_keys(
    results: list[dict[str, Any]], key_by_meeting_id: dict[str, str]
) -> list[str]:
    ordered: OrderedDict[str, None] = OrderedDict()
    for item in results:
        key = key_by_meeting_id.get(item["meeting_id"])
        if key:
            ordered.setdefault(key, None)
    return list(ordered)


def structural_checks(meetings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = []
    all_ok = True
    for key, meeting in meetings.items():
        report = request("GET", f"/v1/meetings/{meeting['id']}/report")
        pipeline = request(
            "GET", f"/v1/meetings/{meeting['id']}/pipeline-runs"
        )["runs"][0]
        artifacts = set(report["artifacts"])
        row = {
            "key": key,
            "meeting_id": meeting["id"],
            "imported": meeting["imported"],
            "status": meeting["status"],
            "graph_status": meeting["graph_status"],
            "segments": len(report["transcript"]),
            "words": sum(len(item["words"]) for item in report["transcript"]),
            "artifact_kinds": len(artifacts),
            "missing_artifacts": sorted(REQUIRED_ARTIFACTS - artifacts),
            "memories": len(report["memories"]),
            "memories_without_evidence": sum(
                not item["evidence_segment_ids"] for item in report["memories"]
            ),
            "pipeline_status": pipeline["status"],
            "pipeline_stages": len(pipeline["stages"]),
        }
        row["passed"] = (
            row["status"] == "READY"
            and row["graph_status"] == "READY"
            and row["segments"] > 0
            and row["words"] == row["segments"]
            and not row["missing_artifacts"]
            and row["memories"] > 0
            and row["memories_without_evidence"] == 0
            and row["pipeline_status"] == "COMPLETED"
            and row["pipeline_stages"] == 7
        )
        all_ok = all_ok and row["passed"]
        rows.append(row)
    return {"passed": all_ok, "meetings": rows}


def retrieval_checks(meetings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    meeting_ids = [item["id"] for item in meetings.values()]
    key_by_meeting_id = {item["id"]: key for key, item in meetings.items()}
    rows = []
    positive_hits = 0
    positive_total = 0
    recalls = []
    for case in RETRIEVAL_CASES:
        response = request(
            "POST",
            "/v1/search",
            {
                "query": case["query"],
                "meeting_ids": meeting_ids,
                "limit": 50,
            },
        )
        ranking = ordered_meeting_keys(response["results"], key_by_meeting_id)
        expected = case["expected"]
        if expected:
            positive_total += 1
            top1 = bool(ranking and ranking[0] in expected)
            positive_hits += int(top1)
            top_k = ranking[: case["k"]]
            recall = len(set(expected) & set(top_k)) / len(expected)
            recalls.append(recall)
            passed = recall == 1.0
        else:
            top1 = None
            recall = None
            # This is deliberately strict: unrelated corpora should not be returned
            # merely because vector search always emits a nearest neighbour.
            passed = not ranking
        rows.append(
            {
                **case,
                "ranking": ranking,
                "result_segments": len(response["results"]),
                "top1_correct": top1,
                "recall_at_k": recall,
                "passed": passed,
            }
        )
    return {
        "positive_top1_accuracy": (
            round(positive_hits / positive_total, 4) if positive_total else None
        ),
        "mean_recall_at_k": (
            round(sum(recalls) / len(recalls), 4) if recalls else None
        ),
        "negative_rejection_passed": next(
            item["passed"] for item in rows if item["name"] == "negative_ota"
        ),
        "cases": rows,
    }


def agent_checks(meetings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    key_by_meeting_id = {item["id"]: key for key, item in meetings.items()}
    ai_keys = ["nasa_shirley", "nasa_erb"]
    ai_ids = [meetings[key]["id"] for key in ai_keys]
    health_keys = ["nih_horigan", "nih_grady", "ajph_kasich"]
    health_ids = [meetings[key]["id"] for key in health_keys]
    cases = [
        {
            "name": "agent_cross_ai",
            "query": "两篇NASA访谈分别怎样描述人工智能、机器人和自动化的发展？",
            "meeting_ids": ai_ids,
            "expected": ai_keys,
        },
        {
            "name": "agent_cross_health",
            "query": "这些健康访谈分别涉及参与者覆盖、生物伦理和公共卫生哪些问题？",
            "meeting_ids": health_ids,
            "expected": health_keys,
        },
        {
            "name": "agent_solar_locate",
            "query": "哪个访谈提到太阳能热水器占世界总量百分之七十六？",
            "meeting_ids": [meetings["npc_solar"]["id"]],
            "expected": ["npc_solar"],
        },
    ]
    rows = []
    for case in cases:
        response = request(
            "POST",
            "/v1/agent/query",
            {
                "query": case["query"],
                "scope": {
                    "mode": "selected_meetings",
                    "meeting_ids": case["meeting_ids"],
                },
                "limit": 30,
            },
        )
        cited = ordered_meeting_keys(response["citations"], key_by_meeting_id)
        rows.append(
            {
                "name": case["name"],
                "query": case["query"],
                "expected": case["expected"],
                "intent": response["intent"],
                "cited_meetings": cited,
                "expected_cited": set(case["expected"]) <= set(cited),
                "grounded": response["verification"]["grounded"],
                "unresolved_memory_evidence": response["verification"][
                    "unresolved_memory_evidence"
                ],
                "llm_used": response["llm_used"],
                "answer": response["answer"],
            }
        )
    return {
        "passed": all(
            item["expected_cited"]
            and item["grounded"]
            and not item["unresolved_memory_evidence"]
            for item in rows
        ),
        "cases": rows,
    }


def evaluate(*, force: bool = False) -> dict[str, Any]:
    meetings = ensure_corpus(force=force)
    structural = structural_checks(meetings)
    retrieval = retrieval_checks(meetings)
    agents = agent_checks(meetings)
    meeting_ids = [item["id"] for item in meetings.values()]
    analysis = request(
        "POST",
        "/v1/analysis",
        {
            "scope": {
                "mode": "selected_meetings",
                "meeting_ids": meeting_ids,
            }
        },
    )
    return {
        "corpus_version": CORPUS_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "api_base": BASE,
        "source_policy": (
            "short factual Chinese adaptations of public interview transcripts; "
            "not wholesale copies"
        ),
        "sources": [
            {
                "key": item["key"],
                "title": item["title"],
                "project_id": item["project_id"],
                "source_name": item["source_name"],
                "source_url": item["source_url"],
                "utterances": len(item["utterances"]),
                "meeting_id": meetings[item["key"]]["id"],
            }
            for item in ARTICLES
        ],
        "structural": structural,
        "retrieval": retrieval,
        "agent": agents,
        "analysis": {
            "meeting_count": analysis["meeting_count"],
            "decisions": len(analysis["decisions"]),
            "action_items": len(analysis["action_items"]),
            "risks": len(analysis["risks"]),
            "open_questions": len(analysis["open_questions"]),
            "top_topics": analysis["top_topics"][:20],
            "cross_meeting_links": len(analysis["timeline"]["links"]),
            "overall_summary": analysis["overall_summary"],
        },
        "overall_passed": (
            structural["passed"]
            and retrieval["positive_top1_accuracy"] == 1.0
            and retrieval["mean_recall_at_k"] == 1.0
            and retrieval["negative_rejection_passed"]
            and agents["passed"]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force",
        action="store_true",
        help="import a fresh copy instead of reusing the versioned READY corpus",
    )
    args = parser.parse_args()
    result = evaluate(force=args.force)
    print("INTERVIEW_CORPUS_EVAL")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        print(exc.read().decode(errors="replace"))
        raise
