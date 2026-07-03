"""EXT-SECRETS-V1 — federal per-user per-extension encrypted secrets.

User-facing surfaces:
- ``@ext.secret(name, description, ...)`` declares a secret in the manifest.
- ``ctx.secrets.get(name)`` reads plaintext (only inside handler scope).
- ``ctx.secrets.set(name, value)`` writes (only when write_mode allows).

See: superpowers/specs/2026-05-12-ext-secrets-v1-design.md
"""
from imperal_sdk.secrets.spec import SecretSpec
from imperal_sdk.secrets.client import SecretClient, SecretStatus
from imperal_sdk.secrets.exceptions import (
    SecretNotDeclaredError,
    SecretWriteForbidden,
    SecretVaultUnavailable,
    SecretValueTooLarge,
    SecretDeclarationConflict,
)

__all__ = [
    "SecretSpec",
    "SecretClient",
    "SecretStatus",
    "SecretNotDeclaredError",
    "SecretWriteForbidden",
    "SecretVaultUnavailable",
    "SecretValueTooLarge",
    "SecretDeclarationConflict",
]
