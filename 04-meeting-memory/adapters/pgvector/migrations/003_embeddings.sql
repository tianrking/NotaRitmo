-- 04-meeting-memory pgvector projection, migration 003.
-- Requires the pgvector extension.  This is rebuildable and is not authority.
-- Default dimension is 1536; use a separate migration/table for another model dimension.

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS segment_embeddings (
    tenant_id       text        NOT NULL,
    segment_id      text        NOT NULL,
    model_id        text        NOT NULL,
    dimensions      integer     NOT NULL CHECK (dimensions = 1536),
    embedding       vector(1536) NOT NULL,
    content_hash    text        NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, segment_id, model_id),
    FOREIGN KEY (tenant_id, segment_id)
      REFERENCES segments (tenant_id, segment_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS claim_embeddings (
    tenant_id       text        NOT NULL,
    claim_id        text        NOT NULL,
    model_id        text        NOT NULL,
    dimensions      integer     NOT NULL CHECK (dimensions = 1536),
    embedding       vector(1536) NOT NULL,
    content_hash    text        NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, claim_id, model_id),
    FOREIGN KEY (tenant_id, claim_id)
      REFERENCES claims (tenant_id, claim_id) ON DELETE CASCADE
);

-- HNSW is preferred for online cosine search on modern pgvector versions.
CREATE INDEX IF NOT EXISTS idx_segment_embeddings_hnsw
    ON segment_embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_claim_embeddings_hnsw
    ON claim_embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_segment_embeddings_tenant_model
    ON segment_embeddings (tenant_id, model_id);
CREATE INDEX IF NOT EXISTS idx_claim_embeddings_tenant_model
    ON claim_embeddings (tenant_id, model_id);

COMMIT;
