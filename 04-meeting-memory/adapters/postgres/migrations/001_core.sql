-- 04-meeting-memory PostgreSQL authority, migration 001.
-- Run with a migration tool as an application/database administrator.
-- Do not use the table owner/BYPASSRLS role for runtime traffic.

BEGIN;

CREATE TABLE IF NOT EXISTS meetings (
    tenant_id       text        NOT NULL CHECK (length(btrim(tenant_id)) > 0),
    meeting_id      text        NOT NULL CHECK (length(btrim(meeting_id)) > 0),
    title           text,
    started_at      timestamptz,
    ended_at        timestamptz,
    payload         jsonb       NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, meeting_id),
    CHECK (ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at)
);

CREATE TABLE IF NOT EXISTS segments (
    tenant_id       text        NOT NULL CHECK (length(btrim(tenant_id)) > 0),
    segment_id      text        NOT NULL CHECK (length(btrim(segment_id)) > 0),
    meeting_id      text        NOT NULL,
    speaker_id      text,
    start_ms        bigint      NOT NULL CHECK (start_ms >= 0),
    end_ms          bigint      NOT NULL CHECK (end_ms >= start_ms),
    text            text        NOT NULL,
    confidence     double precision CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    words           jsonb       NOT NULL DEFAULT '[]'::jsonb,
    payload         jsonb       NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, segment_id),
    FOREIGN KEY (tenant_id, meeting_id)
      REFERENCES meetings (tenant_id, meeting_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS artifacts (
    tenant_id       text        NOT NULL CHECK (length(btrim(tenant_id)) > 0),
    artifact_id     text        NOT NULL CHECK (length(btrim(artifact_id)) > 0),
    meeting_id      text        NOT NULL,
    version         integer     NOT NULL CHECK (version > 0),
    payload         jsonb       NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, artifact_id),
    UNIQUE (tenant_id, meeting_id, version),
    FOREIGN KEY (tenant_id, meeting_id)
      REFERENCES meetings (tenant_id, meeting_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS claims (
    tenant_id       text        NOT NULL CHECK (length(btrim(tenant_id)) > 0),
    claim_id        text        NOT NULL CHECK (length(btrim(claim_id)) > 0),
    source_meeting_id text      NOT NULL,
    state_slot_id   text,
    subject         text        NOT NULL CHECK (length(btrim(subject)) > 0),
    predicate       text        NOT NULL CHECK (length(btrim(predicate)) > 0),
    object_text     text        NOT NULL,
    status          text        NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'superseded', 'disputed', 'retracted')),
    review_state    text        NOT NULL DEFAULT 'candidate'
                    CHECK (review_state IN ('candidate', 'human_approved', 'human_rejected', 'system_approved')),
    evidence_state  text        NOT NULL DEFAULT 'supported'
                    CHECK (evidence_state IN ('supported', 'missing', 'invalid', 'disputed')),
    valid_from      timestamptz,
    valid_to        timestamptz,
    superseded_by   text,
    payload         jsonb       NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, claim_id),
    FOREIGN KEY (tenant_id, source_meeting_id)
      REFERENCES meetings (tenant_id, meeting_id) ON DELETE RESTRICT,
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CHECK (status <> 'superseded' OR superseded_by IS NOT NULL OR valid_to IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS claim_evidence (
    tenant_id       text        NOT NULL,
    claim_id        text        NOT NULL,
    segment_id      text        NOT NULL,
    evidence_role   text        NOT NULL DEFAULT 'support'
                    CHECK (evidence_role IN ('support', 'counter', 'context')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, claim_id, segment_id),
    FOREIGN KEY (tenant_id, claim_id)
      REFERENCES claims (tenant_id, claim_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, segment_id)
      REFERENCES segments (tenant_id, segment_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS claim_relations (
    tenant_id       text        NOT NULL,
    source_claim_id text        NOT NULL,
    relation_type   text        NOT NULL
                    CHECK (relation_type IN ('supports', 'supersedes', 'contradicts', 'follows_up')),
    target_claim_id text        NOT NULL,
    confidence      double precision CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    evidence_ids    jsonb       NOT NULL DEFAULT '[]'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, source_claim_id, relation_type, target_claim_id),
    CHECK (source_claim_id <> target_claim_id),
    FOREIGN KEY (tenant_id, source_claim_id)
      REFERENCES claims (tenant_id, claim_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, target_claim_id)
      REFERENCES claims (tenant_id, claim_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_meetings_tenant_started
    ON meetings (tenant_id, started_at DESC, meeting_id);
CREATE INDEX IF NOT EXISTS idx_segments_tenant_meeting_time
    ON segments (tenant_id, meeting_id, start_ms, segment_id);
CREATE INDEX IF NOT EXISTS idx_claims_tenant_state_slot
    ON claims (tenant_id, state_slot_id, status, valid_from DESC);
CREATE INDEX IF NOT EXISTS idx_claims_tenant_subject_predicate
    ON claims (tenant_id, subject, predicate, status);
CREATE INDEX IF NOT EXISTS idx_claim_evidence_tenant_segment
    ON claim_evidence (tenant_id, segment_id);

-- PostgreSQL FTS is a lexical branch of Hybrid RAG; it is not the semantic index.
CREATE INDEX IF NOT EXISTS idx_segments_fts
    ON segments USING gin (to_tsvector('simple', text));
CREATE INDEX IF NOT EXISTS idx_claims_fts
    ON claims USING gin (to_tsvector('simple', subject || ' ' || predicate || ' ' || object_text));

CREATE OR REPLACE FUNCTION meeting_memory_touch_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS meetings_touch_updated_at ON meetings;
CREATE TRIGGER meetings_touch_updated_at
BEFORE UPDATE ON meetings FOR EACH ROW EXECUTE FUNCTION meeting_memory_touch_updated_at();
DROP TRIGGER IF EXISTS segments_touch_updated_at ON segments;
CREATE TRIGGER segments_touch_updated_at
BEFORE UPDATE ON segments FOR EACH ROW EXECUTE FUNCTION meeting_memory_touch_updated_at();
DROP TRIGGER IF EXISTS artifacts_touch_updated_at ON artifacts;
CREATE TRIGGER artifacts_touch_updated_at
BEFORE UPDATE ON artifacts FOR EACH ROW EXECUTE FUNCTION meeting_memory_touch_updated_at();
DROP TRIGGER IF EXISTS claims_touch_updated_at ON claims;
CREATE TRIGGER claims_touch_updated_at
BEFORE UPDATE ON claims FOR EACH ROW EXECUTE FUNCTION meeting_memory_touch_updated_at();

COMMIT;
