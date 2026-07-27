from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from neo4j import AsyncGraphDatabase

from app.config import settings
from app.services.embeddings import embedding_service


class LocalGraphitiEmbedder:
    async def create(self, input_data: Any) -> list[float]:
        text = input_data if isinstance(input_data, str) else json.dumps(input_data)
        vector = await asyncio.to_thread(embedding_service().query, text)
        return vector or [0.0] * settings.embedding_dimensions

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(embedding_service().documents, input_data_list)


class GraphMemory:
    """Deterministic Neo4j projection with optional Graphiti enrichment."""

    def __init__(self) -> None:
        self.enabled = settings.graph_memory_enabled
        self.driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    async def close(self) -> None:
        await self.driver.close()

    async def ensure_schema(self) -> None:
        constraints = (
            "CREATE CONSTRAINT meeting_id IF NOT EXISTS FOR (n:Meeting) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT segment_id IF NOT EXISTS FOR (n:Segment) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT memory_id IF NOT EXISTS FOR (n:Memory) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT project_id IF NOT EXISTS FOR (n:Project) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT speaker_key IF NOT EXISTS FOR (n:Speaker) REQUIRE n.key IS UNIQUE",
            "CREATE CONSTRAINT topic_key IF NOT EXISTS FOR (n:Topic) REQUIRE n.key IS UNIQUE",
        )
        async with self.driver.session() as session:
            for statement in constraints:
                await session.run(statement)

    async def health(self) -> dict[str, Any]:
        await self.driver.verify_connectivity()
        async with self.driver.session() as session:
            result = await session.run(
                "MATCH (n) RETURN count(n) AS nodes "
                "CALL { MATCH ()-[r]->() RETURN count(r) AS relationships } "
                "RETURN nodes, relationships"
            )
            record = await result.single()
        return {
            "status": "ready",
            "backend": "neo4j-community",
            "nodes": record["nodes"] if record else 0,
            "relationships": record["relationships"] if record else 0,
            "graphiti_enrichment": settings.graphiti_enabled,
        }

    async def project(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {"indexed": False, "reason": "graph memory disabled"}
        await self.ensure_schema()
        meeting = payload["meeting"]
        segments = payload.get("transcript", [])
        memories = payload.get("memories", [])
        project_id = meeting.get("project_id") or "unassigned"
        speakers: dict[str, dict[str, Any]] = {}
        for item in segments:
            speaker_id = item.get("speaker_id")
            if speaker_id:
                speakers[speaker_id] = {
                    "id": speaker_id,
                    "key": f"{meeting['id']}:{speaker_id}",
                    "name": item.get("speaker_name") or "Unknown",
                }
        topics = [
            {
                "key": f"{project_id}:{item.get('subject') or item['content']}".lower(),
                "name": item.get("subject") or item["content"],
                "memory_id": item["memory_id"],
            }
            for item in memories
            if item["kind"] == "topic"
        ]
        async with self.driver.session() as session:
            await session.run(
                """
                MERGE (m:Meeting {id: $id})
                SET m.title = $title, m.project_id = $project_id,
                    m.created_at = $created_at, m.duration_ms = $duration_ms,
                    m.source_provider = $source_provider
                MERGE (p:Project {id: $project_id})
                MERGE (p)-[:HAS_MEETING]->(m)
                """,
                id=meeting["id"],
                title=meeting["title"],
                project_id=project_id,
                created_at=meeting["created_at"],
                duration_ms=meeting.get("duration_ms"),
                source_provider=meeting.get("source_provider"),
            )
            await session.run(
                """
                MATCH (m:Meeting {id: $meeting_id})
                OPTIONAL MATCH (m)-[:HAS_SEGMENT|HAS_MEMORY|HAS_SPEAKER]->(old)
                DETACH DELETE old
                """,
                meeting_id=meeting["id"],
            )
            await session.run(
                """
                MATCH (m:Meeting {id: $meeting_id})-[r:HAS_TOPIC]->()
                DELETE r
                """,
                meeting_id=meeting["id"],
            )
            if speakers:
                await session.run(
                    """
                    MATCH (m:Meeting {id: $meeting_id})
                    UNWIND $speakers AS row
                    CREATE (s:Speaker {id: row.id, key: row.key, name: row.name})
                    CREATE (m)-[:HAS_SPEAKER]->(s)
                    """,
                    meeting_id=meeting["id"],
                    speakers=list(speakers.values()),
                )
            if segments:
                await session.run(
                    """
                    MATCH (m:Meeting {id: $meeting_id})
                    UNWIND $segments AS row
                    CREATE (s:Segment {
                        id: row.segment_id, text: row.text, start_ms: row.start_ms,
                        end_ms: row.end_ms, ordinal: row.ordinal
                    })
                    CREATE (m)-[:HAS_SEGMENT]->(s)
                    WITH m, s, row
                    OPTIONAL MATCH (speaker:Speaker {key: $meeting_id + ':' + row.speaker_id})
                    FOREACH (_ IN CASE WHEN speaker IS NULL THEN [] ELSE [1] END |
                        CREATE (speaker)-[:SPOKE]->(s)
                    )
                    """,
                    meeting_id=meeting["id"],
                    segments=[
                        {
                            **item,
                            "speaker_id": item.get("speaker_id") or "",
                        }
                        for item in segments
                    ],
                )
            if memories:
                await session.run(
                    """
                    MATCH (meeting:Meeting {id: $meeting_id})
                    UNWIND $memories AS row
                    CREATE (memory:Memory {
                        id: row.memory_id, kind: row.kind, subject: row.subject,
                        text: row.content, status: row.status,
                        valid_from: row.valid_from, valid_to: row.valid_to
                    })
                    CREATE (meeting)-[:HAS_MEMORY]->(memory)
                    WITH memory, row
                    UNWIND CASE WHEN size(row.evidence_segment_ids) = 0
                        THEN [null] ELSE row.evidence_segment_ids END AS segment_id
                    OPTIONAL MATCH (segment:Segment {id: segment_id})
                    FOREACH (_ IN CASE WHEN segment IS NULL THEN [] ELSE [1] END |
                        CREATE (memory)-[:EVIDENCED_BY]->(segment)
                    )
                    """,
                    meeting_id=meeting["id"],
                    memories=memories,
                )
                await session.run(
                    """
                    UNWIND $memories AS row
                    WITH row WHERE row.supersedes_id IS NOT NULL
                    MATCH (newer:Memory {id: row.memory_id})
                    MATCH (older:Memory {id: row.supersedes_id})
                    MERGE (newer)-[:SUPERSEDES]->(older)
                    """,
                    memories=memories,
                )
            if topics:
                await session.run(
                    """
                    MATCH (meeting:Meeting {id: $meeting_id})
                    UNWIND $topics AS row
                    MERGE (topic:Topic {key: row.key})
                    SET topic.name = row.name, topic.project_id = $project_id
                    MERGE (meeting)-[:HAS_TOPIC]->(topic)
                    WITH topic, row
                    MATCH (memory:Memory {id: row.memory_id})
                    MERGE (memory)-[:ABOUT]->(topic)
                    """,
                    meeting_id=meeting["id"],
                    project_id=project_id,
                    topics=topics,
                )
            for link in payload.get("memory_links", []):
                relation = link["relation"]
                if relation not in {"related_to", "follows_up", "supersedes"}:
                    continue
                await session.run(
                    """
                    MATCH (source:Memory {id: $source})
                    MATCH (target:Memory {id: $target})
                    MERGE (source)-[r:RELATED_TO]->(target)
                    SET r.kind = $kind, r.confidence = $confidence,
                        r.rationale = $rationale
                    """,
                    source=link["source_memory_id"],
                    target=link["target_memory_id"],
                    kind=relation,
                    confidence=link.get("confidence"),
                    rationale=link.get("rationale"),
                )
        enriched = False
        enrichment_error = None
        if settings.graphiti_enabled:
            try:
                enriched = await self._graphiti_episode(payload)
            except Exception as exc:
                enrichment_error = f"{type(exc).__name__}: {exc}"[:1000]
        return {
            "indexed": True,
            "backend": "neo4j-community",
            "segments": len(segments),
            "memories": len(memories),
            "topics": len(topics),
            "graphiti_enriched": enriched,
            "graphiti_error": enrichment_error,
        }

    async def _graphiti_episode(self, payload: dict[str, Any]) -> bool:
        from graphiti_core import Graphiti
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
        from graphiti_core.nodes import EpisodeType

        if not settings.llm_enabled or not settings.llm_model:
            raise RuntimeError("Graphiti enrichment requires a structured-output LLM")
        llm = OpenAIGenericClient(
            config=LLMConfig(
                api_key=settings.llm_api_key or "local",
                model=settings.llm_model,
                small_model=settings.llm_model,
                base_url=settings.llm_base_url,
                temperature=0,
            ),
            structured_output_mode="json_object",
        )
        graphiti = Graphiti(
            settings.neo4j_uri,
            settings.neo4j_user,
            settings.neo4j_password,
            llm_client=llm,
            embedder=LocalGraphitiEmbedder(),
        )
        try:
            await graphiti.build_indices_and_constraints()
            await graphiti.add_episode(
                name=f"meeting:{payload['meeting']['id']}",
                episode_body=json.dumps(payload, ensure_ascii=False),
                source=EpisodeType.json,
                source_description="NotaRitmo canonical meeting memory",
                reference_time=datetime.fromisoformat(payload["meeting"]["created_at"]),
                group_id=payload["meeting"].get("project_id") or "default",
            )
            return True
        finally:
            await graphiti.close()

    async def search(
        self, query: str, *, project_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        lowered = query.lower()
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (n)
                WHERE (n:Meeting OR n:Memory OR n:Topic OR n:Segment OR n:Speaker)
                  AND ($project_id IS NULL OR n.project_id = $project_id
                       OR EXISTS { MATCH (p:Project {id: $project_id})-[*1..2]-(n) })
                  AND (
                    toLower(coalesce(n.title, '')) CONTAINS $query OR
                    toLower(coalesce(n.text, '')) CONTAINS $query OR
                    toLower(coalesce(n.name, '')) CONTAINS $query OR
                    toLower(coalesce(n.subject, '')) CONTAINS $query
                  )
                RETURN labels(n) AS labels, properties(n) AS properties
                LIMIT $limit
                """,
                query=lowered,
                project_id=project_id,
                limit=limit,
            )
            return [record.data() async for record in result]

    async def meeting_graph(self, meeting_id: str) -> dict[str, Any]:
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH p=(m:Meeting {id: $meeting_id})-[*1..2]-(n)
                UNWIND relationships(p) AS r
                RETURN DISTINCT
                    elementId(startNode(r)) AS source_element_id,
                    labels(startNode(r)) AS source_labels,
                    properties(startNode(r)) AS source,
                    type(r) AS relation,
                    properties(r) AS relation_properties,
                    elementId(endNode(r)) AS target_element_id,
                    labels(endNode(r)) AS target_labels,
                    properties(endNode(r)) AS target
                LIMIT 2000
                """,
                meeting_id=meeting_id,
            )
            rows = [record.data() async for record in result]
        nodes: dict[str, dict[str, Any]] = {}
        edges = []
        for row in rows:
            nodes[row["source_element_id"]] = {
                "element_id": row["source_element_id"],
                "labels": row["source_labels"],
                "properties": row["source"],
            }
            nodes[row["target_element_id"]] = {
                "element_id": row["target_element_id"],
                "labels": row["target_labels"],
                "properties": row["target"],
            }
            edges.append(
                {
                    "source": row["source_element_id"],
                    "target": row["target_element_id"],
                    "relation": row["relation"],
                    "properties": row["relation_properties"],
                }
            )
        return {"meeting_id": meeting_id, "nodes": list(nodes.values()), "edges": edges}


async def ingest_episode(
    meeting_id: str, project_id: str | None, payload: dict[str, Any]
) -> dict[str, Any]:
    graph = GraphMemory()
    try:
        return await graph.project(payload)
    finally:
        await graph.close()


async def graph_health() -> dict[str, Any]:
    graph = GraphMemory()
    try:
        return await graph.health()
    finally:
        await graph.close()


async def graph_search(
    query: str, *, project_id: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    graph = GraphMemory()
    try:
        return await graph.search(query, project_id=project_id, limit=limit)
    finally:
        await graph.close()


async def graph_for_meeting(meeting_id: str) -> dict[str, Any]:
    graph = GraphMemory()
    try:
        return await graph.meeting_graph(meeting_id)
    finally:
        await graph.close()
