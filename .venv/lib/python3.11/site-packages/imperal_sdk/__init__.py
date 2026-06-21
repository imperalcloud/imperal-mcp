"""Imperal Cloud SDK — build extensions for the Imperal platform."""
from typing import TYPE_CHECKING

__version__ = "5.7.3"

# 5.2.2 (2026-06-11): the package root resolves its public surface lazily
# (PEP 562). The eager imports pulled the HTTP transport (Context / client
# modules -> httpx) into EVERY consumer of ANY submodule — including
# platform execution code that lazily imports transport-free helpers such as
# ``imperal_sdk.chat.filters`` (httpx subclasses urllib.request.Request,
# which the platform's execution sandbox restricts; live incident
# 2026-06-10). The public surface is unchanged: every name resolves to the
# same object, star-import honors __all__, and resolved names are cached
# back into module globals.

# name -> defining module (resolved on first attribute access)
_LAZY_ATTRS = {
    # Core
    "Extension": "imperal_sdk.extension",
    "ToolDef": "imperal_sdk.extension",
    "SignalDef": "imperal_sdk.extension",
    "ScheduleDef": "imperal_sdk.extension",
    "LifecycleHook": "imperal_sdk.extension",
    "HealthCheckDef": "imperal_sdk.extension",
    "WebhookDef": "imperal_sdk.extension",
    "EventHandlerDef": "imperal_sdk.extension",
    "ExposedMethod": "imperal_sdk.extension",
    "TrayDef": "imperal_sdk.extension",
    "Context": "imperal_sdk.context",
    "ImperalAuth": "imperal_sdk.auth",
    "AuthError": "imperal_sdk.auth",
    "User": "imperal_sdk.types.identity",
    "UserContext": "imperal_sdk.types.identity",
    "Tenant": "imperal_sdk.types.identity",
    "TenantContext": "imperal_sdk.types.identity",
    "generate_manifest": "imperal_sdk.manifest",
    "save_manifest": "imperal_sdk.manifest",
    "ChatExtension": "imperal_sdk.chat",
    "ActionResult": "imperal_sdk.chat.action_result",
    # LLM
    "get_llm_provider": "imperal_sdk.runtime.llm_provider",
    "LLMProvider": "imperal_sdk.runtime.llm_provider",
    "LLMConfig": "imperal_sdk.runtime.llm_provider",
    "LLMUsage": "imperal_sdk.runtime.llm_provider",
    "MessageAdapter": "imperal_sdk.runtime.message_adapter",
    # Engine SPI
    "KernelEngine": "imperal_sdk.runtime.engine",
    "LocalDevEngine": "imperal_sdk.runtime.local_engine",
    "HostedClient": "imperal_sdk.runtime.hosted_client",
    # IPC
    "ExtensionsClient": "imperal_sdk.extensions.client",
    "CircularCallError": "imperal_sdk.extensions.client",
    # Errors
    "ImperalError": "imperal_sdk.errors",
    "APIError": "imperal_sdk.errors",
    "NotFoundError": "imperal_sdk.errors",
    "RateLimitError": "imperal_sdk.errors",
    "ValidationError": "imperal_sdk.errors",
    "ExtensionError": "imperal_sdk.errors",
    "QuotaExceededError": "imperal_sdk.errors",
    "SkeletonAccessForbidden": "imperal_sdk.errors",
    # Types
    "Page": "imperal_sdk.types",
    "ChatResult": "imperal_sdk.types",
    "FunctionCall": "imperal_sdk.types",
    "Document": "imperal_sdk.types",
    "CompletionResult": "imperal_sdk.types",
    "LimitsResult": "imperal_sdk.types",
    "SubscriptionInfo": "imperal_sdk.types",
    "BalanceInfo": "imperal_sdk.types",
    "FileInfo": "imperal_sdk.types",
    "HTTPResponse": "imperal_sdk.types",
    "MeteredEvent": "imperal_sdk.types.metered_event",
    "Event": "imperal_sdk.types",
    "WebhookRequest": "imperal_sdk.types",
    "WebhookResponse": "imperal_sdk.types",
    "HealthStatus": "imperal_sdk.types",
    # Protocol + Validator
    "ExtensionProtocol": "imperal_sdk.protocols",
    "validate_extension": "imperal_sdk.validator",
    "ValidationReport": "imperal_sdk.validator",
    "ValidationIssue": "imperal_sdk.validator",
    "validate_source_tree": "imperal_sdk.validator_v1_6_0",
    "validate_manifest_v1_6_0": "imperal_sdk.validator_v1_6_0",
    # Secrets (importable from the root since 5.1.0; not in __all__ —
    # preserved as-is)
    "SecretSpec": "imperal_sdk.secrets",
    "SecretClient": "imperal_sdk.secrets",
    "SecretStatus": "imperal_sdk.secrets",
    "SecretNotDeclaredError": "imperal_sdk.secrets",
    "SecretWriteForbidden": "imperal_sdk.secrets",
    "SecretVaultUnavailable": "imperal_sdk.secrets",
    "SecretValueTooLarge": "imperal_sdk.secrets",
    "SecretDeclarationConflict": "imperal_sdk.secrets",
}

# Any imperal_sdk submodule also resolves as a root attribute (the eager
# imports used to expose chat/context/errors/ui/sdl/... as side effects;
# the generic fallback in __getattr__ preserves that surface).

if TYPE_CHECKING:  # pragma: no cover — IDE / type-checker surface only
    from imperal_sdk.extension import (
        Extension, ToolDef, SignalDef, ScheduleDef,
        LifecycleHook, HealthCheckDef, WebhookDef, EventHandlerDef, ExposedMethod, TrayDef,
    )
    from imperal_sdk.context import Context
    from imperal_sdk.auth import ImperalAuth, AuthError
    from imperal_sdk.types.identity import User, UserContext, Tenant, TenantContext
    from imperal_sdk.manifest import generate_manifest, save_manifest
    from imperal_sdk.chat import ChatExtension
    from imperal_sdk.chat.action_result import ActionResult
    from imperal_sdk import ui
    from imperal_sdk import sdl
    from imperal_sdk.runtime.llm_provider import get_llm_provider, LLMProvider, LLMConfig, LLMUsage
    from imperal_sdk.runtime.message_adapter import MessageAdapter
    from imperal_sdk.extensions.client import ExtensionsClient, CircularCallError
    from imperal_sdk.errors import (
        ImperalError, APIError, NotFoundError, RateLimitError,
        ValidationError, ExtensionError, QuotaExceededError,
        SkeletonAccessForbidden,
    )
    from imperal_sdk.types import (
        Page, ChatResult, FunctionCall,
        Document, CompletionResult, LimitsResult, SubscriptionInfo,
        BalanceInfo, FileInfo, HTTPResponse,
        Event, WebhookRequest, WebhookResponse, HealthStatus,
    )
    from imperal_sdk.types.metered_event import MeteredEvent
    from imperal_sdk.protocols import ExtensionProtocol
    from imperal_sdk.validator import validate_extension, ValidationReport, ValidationIssue
    from imperal_sdk.validator_v1_6_0 import (
        validate_source_tree,
        validate_manifest_v1_6_0,
    )
    from imperal_sdk.secrets import (
        SecretSpec, SecretClient, SecretStatus,
        SecretNotDeclaredError, SecretWriteForbidden, SecretVaultUnavailable,
        SecretValueTooLarge, SecretDeclarationConflict,
    )


def __getattr__(name: str):
    import importlib

    src = _LAZY_ATTRS.get(name)
    if src is not None:
        obj = getattr(importlib.import_module(src), name)
        globals()[name] = obj
        return obj
    if name.startswith("_"):
        raise AttributeError(f"module 'imperal_sdk' has no attribute {name!r}")
    try:
        mod = importlib.import_module(f"imperal_sdk.{name}")
    except ImportError:
        raise AttributeError(
            f"module 'imperal_sdk' has no attribute {name!r}"
        ) from None
    globals()[name] = mod
    return mod


def __dir__():
    return sorted(set(globals()) | set(_LAZY_ATTRS) | {"ui", "sdl"})


__all__ = [
    # Core
    "Extension", "ToolDef", "SignalDef", "ScheduleDef",
    "LifecycleHook", "HealthCheckDef", "WebhookDef", "EventHandlerDef", "ExposedMethod", "TrayDef",
    "Context", "ImperalAuth", "AuthError",
    "User", "UserContext", "Tenant", "TenantContext",
    "ChatExtension", "ActionResult",
    "generate_manifest", "save_manifest",
    # IPC
    "ExtensionsClient", "CircularCallError",
    # LLM
    "get_llm_provider", "LLMProvider", "LLMConfig", "LLMUsage", "MessageAdapter",
    # Errors
    "ImperalError", "APIError", "NotFoundError", "RateLimitError",
    "ValidationError", "ExtensionError", "QuotaExceededError",
    "SkeletonAccessForbidden",
    # Types
    "Page", "ChatResult", "FunctionCall",
    "Document", "CompletionResult", "LimitsResult", "SubscriptionInfo",
    "BalanceInfo", "FileInfo", "HTTPResponse",
    "MeteredEvent",
    "Event", "WebhookRequest", "WebhookResponse", "HealthStatus",
    # Protocol + Validator
    "ExtensionProtocol", "validate_extension", "ValidationReport", "ValidationIssue",
    "validate_source_tree", "validate_manifest_v1_6_0",
    # UI
    "ui",
    # SDL — Structured Data Layer
    "sdl",
]
