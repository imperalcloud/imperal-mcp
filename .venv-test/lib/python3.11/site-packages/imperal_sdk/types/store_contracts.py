"""
Wire contract for SDK ↔ Auth Gateway store endpoints.

Serialization: JSON (UTF-8).
Transport: HTTP (httpx in SDK, FastAPI in Auth GW).

I-SDK-GW-CONTRACT-1 — Auth Gateway maintains a duplicate of these Pydantic
classes in ``/opt/imperal-auth-gateway/.../app/store/schemas.py`` with IDENTICAL
JSON Schema. A CI gate compares ``model_json_schema()`` of both sides; any
drift fails the build. (The venv on Auth Gateway host does not ship
imperal-sdk, so file-identity import is not available; schema compare gives
equivalent drift-proofing.)
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ListUsersRequest(BaseModel):
    """Shape of SDK's query-param-based GET /v1/internal/store/{coll}/list_users."""
    collection: str
    extension_id: str
    tenant_id: str
    cursor: str | None = None
    limit: int = Field(500, ge=1, le=10000)


class ListUsersResponse(BaseModel):
    user_ids: list[str]
    next_cursor: str | None = None
    truncated: bool = False  # reserved; always False for cursor-paginated endpoint
