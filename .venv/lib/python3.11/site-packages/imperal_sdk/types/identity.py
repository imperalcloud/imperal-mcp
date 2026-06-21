"""Canonical identity types for the Imperal platform.

Single source of truth for `User`/`Tenant` shapes (W1, 2026-04-27).
AuthGW imports these for FastAPI response models; kernel embeds the lean
variants in KernelContext; extensions receive lean variants via
ctx.user / ctx.tenant.

Two-tier rationale: full models mirror the auth-gw API surface (admin
endpoints, audit fields). Lean *Context models are the runtime view
consumed by kernel + extensions — admin-only fields stay on auth-gw.

Invariants enforced at module import:
    set(UserContext.model_fields)   <= set(User.model_fields)
    set(TenantContext.model_fields) <= set(Tenant.model_fields)

Excluded from canonical wire contract:
    User.id (UUID PK — DB-internal)
    User.password_hash (never leaves DB)
    Tenant.db_config (contains secrets in current schema)
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    """Full User — admin/API-facing. Mirrors auth-gw UserResponse + is_active."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    imperal_id: str
    email: str
    tenant_id: str
    agency_id: str | None = None
    org_id: str | None = None
    role: str
    auth_method: str
    scopes: list[str] = []
    attributes: dict = {}
    is_active: bool = True
    created_at: str
    last_login: str | None = None
    cases_user_id: int | None = None

    def has_scope(self, scope: str) -> bool:
        if "*" in self.scopes:
            return True
        for s in self.scopes:
            if s == scope:
                return True
            if s.endswith(".*"):
                prefix = s[:-2]
                if scope.startswith(prefix + ".") or scope == prefix:
                    return True
        return False

    def has_role(self, role: str) -> bool:
        return self.role == role


class UserContext(BaseModel):
    """Lean User — runtime/extension-facing. Strict subset of `User`."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    imperal_id: str = Field(min_length=1)
    email: str
    tenant_id: str = Field(min_length=1)
    agency_id: str | None = None
    org_id: str | None = None
    role: str
    scopes: list[str] = []
    attributes: dict = {}
    is_active: bool = True

    def has_scope(self, scope: str) -> bool:
        if "*" in self.scopes:
            return True
        for s in self.scopes:
            if s == scope:
                return True
            if s.endswith(".*"):
                prefix = s[:-2]
                if scope.startswith(prefix + ".") or scope == prefix:
                    return True
        return False

    def has_role(self, role: str) -> bool:
        return self.role == role


class Tenant(BaseModel):
    """Full Tenant — admin/API-facing. Mirrors auth-gw TenantResponse."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    tenant_id: str
    name: str
    db_backend: str
    isolation: str
    allowed_auth_methods: str
    max_connections: int
    features: dict = {}
    is_active: bool = True
    created_at: str
    updated_at: str
    parent_tenant_id: str | None = None
    can_resell: bool = False
    custom_pricing: dict = {}
    ui_config: dict = {}


class TenantContext(BaseModel):
    """Lean Tenant — runtime-essential. Strict subset of `Tenant`."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str
    name: str
    is_active: bool = True
    features: dict = {}
    isolation: str = "shared"


def _assert_subset(lean: type[BaseModel], full: type[BaseModel]) -> None:
    lean_fields = set(lean.model_fields.keys())
    full_fields = set(full.model_fields.keys())
    missing = lean_fields - full_fields
    if missing:
        raise RuntimeError(
            f"Identity contract violation: {lean.__name__} has fields "
            f"not in {full.__name__}: {sorted(missing)}"
        )


_assert_subset(UserContext, User)
_assert_subset(TenantContext, Tenant)


__all__ = ["User", "UserContext", "Tenant", "TenantContext"]
