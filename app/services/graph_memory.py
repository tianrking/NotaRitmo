from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.config import settings


async def ingest_episode(meeting_id: str, project_id: str | None, payload: dict[str, Any]) -> bool:
    """Write a confirmed derived event to Graphiti when the optional profile is enabled."""
    if not settings.graphiti_enabled:
        return False

    from graphiti_core import Graphiti
    from graphiti_core.nodes import EpisodeType

    graphiti = Graphiti(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password,
    )
    try:
        await graphiti.build_indices_and_constraints()
        await graphiti.add_episode(
            name=f"meeting:{meeting_id}",
            episode_body=json.dumps(payload, ensure_ascii=False),
            source=EpisodeType.json,
            source_description="canonical meeting memory event",
            reference_time=datetime.now(UTC),
            group_id=project_id or "default",
        )
        return True
    finally:
        await graphiti.close()
