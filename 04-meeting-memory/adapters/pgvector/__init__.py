"""Optional pgvector semantic-retrieval adapter."""

from .retriever import EmbeddingProvider, PgVectorDependencyError, PgVectorRetriever

__all__ = ["EmbeddingProvider", "PgVectorRetriever", "PgVectorDependencyError"]
