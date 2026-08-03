"""Secret-safe metadata helpers.

Only non-sensitive operational metadata is returned by adapters.  This module
also protects callers that pass a vendor error or endpoint containing an
accidentally embedded credential.
"""

from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit


SECRET_KEYS = {
    "api_key", "apikey", "authorization", "auth_token", "token", "secret",
    "password", "client_secret", "private_key", "access_token", "refresh_token",
}
_BEARER = re.compile(r"(?i)(bearer\s+)[^\s,;]+")
_KEYLIKE = re.compile(r"(?i)(sk-[a-z0-9_-]{8,}|eyJ[a-z0-9_-]{12,}\.[a-z0-9_.-]+)")


def redact_text(value: str) -> str:
    value = _BEARER.sub(r"\1[REDACTED]", value)
    return _KEYLIKE.sub("[REDACTED]", value)


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if str(key).lower() in SECRET_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def safe_url(value: str) -> str:
    """Remove query/fragment and credentials from URLs stored in metadata."""

    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.port:
            host += ":" + str(parsed.port)
        netloc = host
        return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    except ValueError:
        return redact_text(value).split("?", 1)[0].split("#", 1)[0]
