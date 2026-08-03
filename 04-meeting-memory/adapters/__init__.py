"""Optional production adapters for the meeting-memory research core.

The deterministic ``baseline`` package remains usable without third-party
services.  Code in this package is deliberately dependency-light: database
drivers and pgvector are imported only when the corresponding adapter is
constructed.
"""

__all__ = ["postgres", "pgvector"]
