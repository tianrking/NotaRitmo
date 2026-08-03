-- 04-meeting-memory PostgreSQL authority, migration 002.
-- The application must set SET LOCAL app.tenant_id = '<tenant>' per transaction.
-- Use a runtime role that is not table owner and does not have BYPASSRLS.

BEGIN;

ALTER TABLE meetings       ENABLE ROW LEVEL SECURITY;
ALTER TABLE meetings       FORCE ROW LEVEL SECURITY;
ALTER TABLE segments       ENABLE ROW LEVEL SECURITY;
ALTER TABLE segments       FORCE ROW LEVEL SECURITY;
ALTER TABLE artifacts      ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifacts      FORCE ROW LEVEL SECURITY;
ALTER TABLE claims         ENABLE ROW LEVEL SECURITY;
ALTER TABLE claims         FORCE ROW LEVEL SECURITY;
ALTER TABLE claim_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE claim_evidence FORCE ROW LEVEL SECURITY;
ALTER TABLE claim_relations ENABLE ROW LEVEL SECURITY;
ALTER TABLE claim_relations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS meetings_tenant_isolation ON meetings;
CREATE POLICY meetings_tenant_isolation ON meetings
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS segments_tenant_isolation ON segments;
CREATE POLICY segments_tenant_isolation ON segments
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS artifacts_tenant_isolation ON artifacts;
CREATE POLICY artifacts_tenant_isolation ON artifacts
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS claims_tenant_isolation ON claims;
CREATE POLICY claims_tenant_isolation ON claims
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS claim_evidence_tenant_isolation ON claim_evidence;
CREATE POLICY claim_evidence_tenant_isolation ON claim_evidence
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS claim_relations_tenant_isolation ON claim_relations;
CREATE POLICY claim_relations_tenant_isolation ON claim_relations
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

COMMIT;
