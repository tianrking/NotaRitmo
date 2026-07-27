from __future__ import annotations

import hashlib
import hmac
import time
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, Request

from app.config import settings
from app.db import SessionLocal
from app.models import Tenant, User


@dataclass(frozen=True)
class HeraPrincipal:
    tenant_id: UUID
    user_id: UUID
    permissions: frozenset[str]
    request_id: str
    authenticated: bool

    def allows(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions


_principal: ContextVar[HeraPrincipal | None] = ContextVar(
    "hera_principal", default=None
)


def current_principal() -> HeraPrincipal:
    return _principal.get() or HeraPrincipal(
        tenant_id=settings.default_tenant_id,
        user_id=settings.default_user_id,
        permissions=frozenset({"*"}),
        request_id="local-development",
        authenticated=False,
    )


def current_tenant_id() -> UUID:
    return current_principal().tenant_id


def current_user_id() -> UUID:
    return current_principal().user_id


def activate_internal_principal(tenant_id: UUID, user_id: UUID) -> None:
    """Set trusted workflow context inside an isolated Temporal activity task."""

    _principal.set(
        HeraPrincipal(
            tenant_id=tenant_id,
            user_id=user_id,
            permissions=frozenset({"*"}),
            request_id="temporal-workflow",
            authenticated=True,
        )
    )


def _required_permission(request: Request) -> str | None:
    path = request.url.path
    if (
        path in {"/health", "/ready", "/openapi.json"}
        or path.startswith(("/docs", "/redoc", "/v1/providers/"))
    ):
        return None
    if path.startswith("/v1/hera/outbox"):
        return "integration:ack" if request.method != "GET" else "integration:read"
    if path.startswith(("/v1/voiceprints", "/v1/people")):
        return "voiceprint:manage"
    if path.startswith(
        (
            "/v1/search",
            "/v1/agent",
            "/v1/analysis",
            "/v1/memory",
            "/v1/graph",
            "/v1/conversations",
        )
    ):
        return "meeting:query"
    if request.method == "GET":
        return "meeting:read"
    return "meeting:write"


def _ensure_identity(principal: HeraPrincipal) -> None:
    with SessionLocal() as db:
        tenant = db.get(Tenant, principal.tenant_id)
        if tenant is None:
            db.add(Tenant(id=principal.tenant_id, name=f"Hera {principal.tenant_id}"))
            db.flush()
        user = db.get(User, principal.user_id)
        if user is None:
            db.add(
                User(
                    id=principal.user_id,
                    tenant_id=principal.tenant_id,
                    display_name=f"Hera User {principal.user_id}",
                )
            )
        elif user.tenant_id != principal.tenant_id:
            raise HTTPException(status_code=403, detail="user does not belong to tenant")
        db.commit()


async def hera_request_context(request: Request):
    tenant = request.headers.get("X-Hera-Tenant-ID")
    user = request.headers.get("X-Hera-User-ID")
    timestamp = request.headers.get("X-Hera-Timestamp")
    request_id = request.headers.get("X-Hera-Request-ID")
    permissions_value = request.headers.get("X-Hera-Permissions", "")
    signature = request.headers.get("X-Hera-Signature")
    supplied = any((tenant, user, timestamp, request_id, permissions_value, signature))
    service_exempt = (
        request.url.path in {"/health", "/ready", "/openapi.json"}
        or request.url.path.startswith(("/docs", "/redoc", "/v1/providers/"))
    )

    if not supplied and (not settings.hera_auth_required or service_exempt):
        principal = HeraPrincipal(
            tenant_id=settings.default_tenant_id,
            user_id=settings.default_user_id,
            permissions=frozenset({"*"}),
            request_id="local-development",
            authenticated=False,
        )
    else:
        if not all((tenant, user, timestamp, request_id, signature)):
            raise HTTPException(status_code=401, detail="incomplete Hera identity headers")
        try:
            tenant_id = UUID(tenant)
            user_id = UUID(user)
            timestamp_value = int(timestamp)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="invalid Hera identity headers") from exc
        if abs(int(time.time()) - timestamp_value) > settings.hera_signature_max_skew_seconds:
            raise HTTPException(status_code=401, detail="expired Hera request signature")
        message = "\n".join(
            [
                request.method.upper(),
                request.url.path,
                str(tenant_id),
                str(user_id),
                str(timestamp_value),
                request_id,
                permissions_value,
            ]
        )
        expected = hmac.new(
            settings.hera_signing_secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=401, detail="invalid Hera request signature")
        permissions = frozenset(
            item.strip() for item in permissions_value.split(",") if item.strip()
        )
        principal = HeraPrincipal(
            tenant_id=tenant_id,
            user_id=user_id,
            permissions=permissions,
            request_id=request_id,
            authenticated=True,
        )
        _ensure_identity(principal)

    required = _required_permission(request)
    if required and not principal.allows(required):
        raise HTTPException(status_code=403, detail=f"missing permission: {required}")
    token = _principal.set(principal)
    try:
        yield principal
    finally:
        _principal.reset(token)
