"""Static SQL contracts; no PostgreSQL or pgvector service is required."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SQLContractTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8").lower()

    def test_core_schema_has_authority_tables_and_evidence(self) -> None:
        sql = self.read("postgres/migrations/001_core.sql")
        for table in ("meetings", "segments", "artifacts", "claims", "claim_evidence", "claim_relations"):
            self.assertIn(f"create table if not exists {table}", sql)
        for token in ("tenant_id", "active", "superseded", "primary key", "foreign key", "valid_from", "valid_to"):
            self.assertIn(token, sql)
        self.assertIn("to_tsvector", sql)

    def test_rls_is_force_enabled_for_every_authority_table(self) -> None:
        sql = self.read("postgres/migrations/002_rls.sql")
        for table in ("meetings", "segments", "artifacts", "claims", "claim_evidence", "claim_relations"):
            compact = " ".join(sql.split())
            self.assertIn(f"alter table {table} force row level security", compact)
            self.assertIn(f"create policy {table}_tenant_isolation", sql)
        self.assertIn("current_setting('app.tenant_id', true)", sql)

    def test_vector_projection_is_rebuildable_and_tenant_scoped(self) -> None:
        sql = self.read("pgvector/migrations/003_embeddings.sql")
        for table in ("segment_embeddings", "claim_embeddings"):
            self.assertIn(f"create table if not exists {table}", sql)
            self.assertIn("vector(1536)", sql)
            self.assertIn("foreign key (tenant_id", sql)
        self.assertIn("create extension if not exists vector", sql)
        self.assertIn("vector_cosine_ops", sql)

    def test_runtime_docs_do_not_claim_local_database_is_running(self) -> None:
        postgres_readme = self.read("postgres/README.md")
        vector_readme = self.read("pgvector/README.md")
        for text in (postgres_readme, vector_readme):
            self.assertIn("postgresql", text)
            self.assertIn("sqlite", text)
        self.assertIn("显式", vector_readme)


if __name__ == "__main__":
    unittest.main()
