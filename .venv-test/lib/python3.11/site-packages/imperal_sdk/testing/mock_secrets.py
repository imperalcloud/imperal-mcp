# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""MockSecretStore — pytest-friendly in-memory backend for ctx.secrets.

Canonical pattern::

    @pytest.fixture
    def secrets():
        return MockSecretStore({"openai_api_key": "sk-test"})

    async def test_my_handler(ctx_factory, secrets):
        ctx = ctx_factory(secrets=secrets)
        ...
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class _Status:
    name: str
    description: str
    is_set: bool
    last_accessed_at: Optional[int]


class MockSecretStore:
    """Drop-in replacement for SecretClient in pytest. No HTTP, no Vault.

    Validates name-not-declared semantics if ``declared`` set is passed
    (raises ImportError-style ValueError to mirror SecretNotDeclaredError).
    Otherwise accepts any name (looser default for fixture ergonomics).
    """

    def __init__(
        self,
        initial: dict[str, str] | None = None,
        *,
        declared: set[str] | None = None,
    ):
        self._store: dict[str, str] = dict(initial or {})
        self._declared = declared  # if None, all names allowed

    def _check_declared(self, name: str) -> None:
        if self._declared is not None and name not in self._declared:
            raise ValueError(
                f"MockSecretStore: name {name!r} not in declared set "
                f"(declared={sorted(self._declared)})"
            )

    async def get(self, name: str) -> Optional[str]:
        self._check_declared(name)
        return self._store.get(name)

    async def set(self, name: str, value: str) -> None:
        self._check_declared(name)
        self._store[name] = value

    async def delete(self, name: str) -> bool:
        self._check_declared(name)
        return self._store.pop(name, None) is not None

    async def is_set(self, name: str) -> bool:
        self._check_declared(name)
        return name in self._store

    async def list(self) -> list[_Status]:
        return [
            _Status(
                name=n,
                description="(mock)",
                is_set=True,
                last_accessed_at=None,
            )
            for n in self._store
        ]
