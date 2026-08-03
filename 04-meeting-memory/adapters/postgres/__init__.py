"""PostgreSQL authoritative-memory adapter.

The module imports no psycopg at import time.  Install ``psycopg[binary]``
only for an actual PostgreSQL deployment.
"""

from .repository import PostgresDependencyError, PostgreSQLRepository

__all__ = ["PostgreSQLRepository", "PostgresDependencyError"]
