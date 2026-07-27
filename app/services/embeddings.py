from __future__ import annotations

from functools import lru_cache

from app.config import settings


class EmbeddingService:
    """Local, deterministic embedding boundary used by ingestion and retrieval."""

    def __init__(self) -> None:
        self.enabled = settings.local_embeddings_enabled
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(
                model_name=settings.local_embedding_model,
                cache_dir=settings.local_embedding_cache,
                threads=4,
            )
        return self._model

    def documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.enabled:
            return [[] for _ in texts]
        model = self._load()
        return [
            vector.astype(float).tolist()
            for vector in model.embed([f"passage: {text}" for text in texts])
        ]

    def query(self, text: str) -> list[float] | None:
        if not text.strip() or not self.enabled:
            return None
        model = self._load()
        return next(model.embed([f"query: {text.strip()}"])).astype(float).tolist()


@lru_cache
def embedding_service() -> EmbeddingService:
    return EmbeddingService()
