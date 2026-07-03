# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""MockContext — drop-in Context replacement for unit testing extensions.

Usage:
    from imperal_sdk.testing import MockContext

    async def test_create_deal():
        ctx = MockContext(user_id="test_user", role="admin")
        result = await fn_create_deal(ctx, params)
        assert result.status == "success"
        assert "deals" in ctx.store._data
"""
from __future__ import annotations

import uuid
from typing import Any

from imperal_sdk.types.identity import UserContext
from imperal_sdk.context import Context, TimeContext
from imperal_sdk.errors import ExtensionError
from imperal_sdk.types.models import (
    BalanceInfo, CompletionResult, Document, FileInfo,
    HTTPResponse, LimitsResult, SubscriptionInfo,
)
from imperal_sdk.types.pagination import Page


class MockStore:
    """In-memory store for testing. Supports all StoreProtocol methods."""

    def __init__(self):
        self._data: dict[str, dict[str, dict]] = {}

    async def create(self, collection: str, data: dict) -> Document:
        if collection not in self._data:
            self._data[collection] = {}
        doc_id = str(uuid.uuid4())[:8]
        self._data[collection][doc_id] = dict(data)
        return Document(id=doc_id, collection=collection, data=dict(data))

    async def get(self, collection: str, doc_id: str) -> Document | None:
        coll = self._data.get(collection, {})
        data = coll.get(doc_id)
        if data is None:
            return None
        return Document(id=doc_id, collection=collection, data=dict(data))

    async def query(
        self,
        collection: str,
        where: dict | None = None,
        order_by: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Page[Document]:
        coll = self._data.get(collection, {})
        docs = [
            Document(id=doc_id, collection=collection, data=dict(data))
            for doc_id, data in coll.items()
        ]
        if where:
            docs = [d for d in docs if all(d.data.get(k) == v for k, v in where.items())]
        return Page(data=docs[:limit], has_more=len(docs) > limit)

    async def update(self, collection: str, doc_id: str, data: dict) -> Document:
        if collection not in self._data:
            self._data[collection] = {}
        if doc_id in self._data[collection]:
            self._data[collection][doc_id].update(data)
        else:
            self._data[collection][doc_id] = dict(data)
        return Document(
            id=doc_id,
            collection=collection,
            data=dict(self._data[collection][doc_id]),
        )

    async def delete(self, collection: str, doc_id: str) -> bool:
        coll = self._data.get(collection, {})
        if doc_id in coll:
            del coll[doc_id]
            return True
        return False

    async def count(self, collection: str, where: dict | None = None) -> int:
        coll = self._data.get(collection, {})
        if not where:
            return len(coll)
        return sum(
            1 for data in coll.values()
            if all(data.get(k) == v for k, v in where.items())
        )


class MockAI:
    """Mock AI client. Set responses per prompt pattern."""

    def __init__(self):
        self._responses: list[tuple[str, str]] = []
        self._default_response = "Mock AI response"

    def set_response(self, pattern: str, response: str) -> None:
        self._responses.append((pattern, response))

    async def complete(self, prompt: str, model: str = "", **kwargs) -> CompletionResult:
        for pattern, response in self._responses:
            if pattern in prompt:
                return CompletionResult(text=response, model=model or "mock")
        return CompletionResult(text=self._default_response, model=model or "mock")


class MockBilling:
    """Mock billing client. Always allows by default."""

    def __init__(self, balance: int = 50000, plan: str = "pro"):
        self.balance = balance
        self.plan = plan

    async def check_limits(self) -> LimitsResult:
        return LimitsResult(allowed=True, balance=self.balance, plan=self.plan)

    async def get_subscription(self) -> SubscriptionInfo:
        return SubscriptionInfo(
            plan_id=self.plan,
            plan_name=self.plan.title(),
            status="active",
        )

    async def track_usage(self, meter: str, quantity: int = 1, user=None) -> bool:
        self.balance = max(0, self.balance - quantity)
        return True

    async def get_balance(self) -> BalanceInfo:
        return BalanceInfo(balance=self.balance, plan=self.plan, cap=250000)


class MockSkeleton:
    """Mock skeleton client. In-memory sections."""

    def __init__(self):
        self._sections: dict[str, dict] = {}

    async def get(self, section: str) -> dict | None:
        return self._sections.get(section)

    def _seed(self, section: str, data: dict) -> None:
        """Test-only: preload a skeleton section. NOT part of SkeletonProtocol
        (the real client is read-only since v1.6.0; kernel skeleton_save_section
        is the sole writer)."""
        self._sections[section] = data


class MockNotify:
    """Mock notify client. Records sent notifications.

    Both invocation styles — ``await ctx.notify(msg)`` and
    ``await ctx.notify.send(msg)`` — populate ``self.sent`` identically so a
    test asserting against the recorded list is agnostic to the call-style.
    """

    def __init__(self):
        self.sent: list[dict] = []

    async def __call__(self, message: str, **kwargs) -> None:
        channel = kwargs.pop("channel", "in_app")
        self.sent.append({"message": message, "channel": channel, **kwargs})

    async def send(self, message: str, channel: str = "in_app", **kwargs) -> None:
        # Alias — matches NotifyClient.send semantics.
        await self(message, channel=channel, **kwargs)


class MockStorage:
    """Mock storage client. In-memory files."""

    def __init__(self):
        self._files: dict[str, bytes] = {}

    async def upload(
        self, path: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> FileInfo:
        self._files[path] = data
        return FileInfo(path=path, size=len(data), content_type=content_type)

    async def download(self, path: str) -> bytes:
        if path not in self._files:
            raise FileNotFoundError(f"Mock file not found: {path}")
        return self._files[path]

    async def delete(self, path: str) -> bool:
        if path in self._files:
            del self._files[path]
            return True
        return False

    async def list(self, prefix: str = "") -> Page[FileInfo]:
        files = [
            FileInfo(path=p, size=len(d))
            for p, d in self._files.items()
            if p.startswith(prefix)
        ]
        return Page(data=files)


class MockHTTP:
    """Mock HTTP client. Register responses per URL pattern."""

    def __init__(self):
        self._mocks: list[tuple[str, str, dict, int, dict]] = []

    def mock_get(self, url_pattern: str, response: dict, status: int = 200,
                 headers: dict | None = None) -> None:
        self._mocks.append(("GET", url_pattern, response, status, headers or {}))

    def mock_post(self, url_pattern: str, response: dict, status: int = 200,
                  headers: dict | None = None) -> None:
        self._mocks.append(("POST", url_pattern, response, status, headers or {}))

    async def _find(self, method: str, url: str) -> HTTPResponse:
        for entry in self._mocks:
            m, pattern, resp, status = entry[0], entry[1], entry[2], entry[3]
            hdrs = entry[4] if len(entry) > 4 else {}  # tolerate legacy 4-tuples
            if m == method and pattern in url:
                return HTTPResponse(status_code=status, body=resp, headers=dict(hdrs))
        return HTTPResponse(status_code=404, body={"error": "No mock registered"})

    async def get(self, url: str, **kwargs) -> HTTPResponse:
        return await self._find("GET", url)

    async def post(self, url: str, **kwargs) -> HTTPResponse:
        return await self._find("POST", url)

    async def put(self, url: str, **kwargs) -> HTTPResponse:
        return await self._find("PUT", url)

    async def patch(self, url: str, **kwargs) -> HTTPResponse:
        return await self._find("PATCH", url)

    async def delete(self, url: str, **kwargs) -> HTTPResponse:
        return await self._find("DELETE", url)


class MockConfig:
    """Mock config client. Reads from a nested dict with dot-path support."""

    def __init__(self, data: dict | None = None):
        self._data = data or {}

    def get(self, key: str, default: Any = None) -> Any:
        parts = key.split(".")
        current: Any = self._data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    def get_section(self, section: str) -> dict:
        return dict(self._data.get(section, {}))

    def all(self) -> dict:
        return dict(self._data)


class MockExtensions:
    """Mock inter-extension client."""

    def __init__(self):
        self._handlers: dict[str, dict[str, Any]] = {}
        self._emitted: list[dict] = []

    def register(self, app_id: str, method: str, handler: Any) -> None:
        if app_id not in self._handlers:
            self._handlers[app_id] = {}
        self._handlers[app_id][method] = handler

    async def call(self, app_id: str, method: str, **kwargs) -> Any:
        handlers = self._handlers.get(app_id, {})
        handler = handlers.get(method)
        if handler is None:
            raise ExtensionError(app_id, f"Method '{method}' not found")
        import asyncio
        if asyncio.iscoroutinefunction(handler):
            return await handler(**kwargs)
        return handler(**kwargs)

    async def emit(self, event_type: str, data: dict) -> None:
        self._emitted.append({"event_type": event_type, "data": data})


def MockContext(
    user_id: str = "test_user",
    email: str = "test@test.com",
    role: str = "user",
    scopes: list[str] | None = None,
    tenant_id: str = "default",
    extension_id: str = "test-ext",
    config: dict | None = None,
    tool_type: str = "tool",
) -> Context:
    """Create a MockContext for testing. Drop-in replacement for Context.

    Args:
        user_id: User ID. Defaults to "test_user".
        email: User email. Defaults to "test@test.com".
        role: User role ("user" or "admin"). Defaults to "user".
        scopes: User scopes. Defaults to ["*"] (all scopes allowed).
        tenant_id: Tenant ID. Defaults to "default".
        extension_id: Extension ID set on _extension_id. Defaults to "test-ext".
        config: Config dict for MockConfig. Supports dot-path access.
        tool_type: Dispatch surface — ``"tool"`` (default) / ``"skeleton"`` /
            ``"panel"`` / ``"chat_fn"``. In v1.6.0 only ``"skeleton"`` may read
            ``ctx.skeleton``; other types raise ``SkeletonAccessForbidden``.
            Pass ``"skeleton"`` in tests that exercise skeleton reads.

    Returns:
        A fully populated Context with all mock clients.
    """
    user = UserContext(
        imperal_id=user_id,
        email=email,
        role=role,
        scopes=scopes if scopes is not None else ["*"],
        tenant_id=tenant_id,
    )
    return Context(
        user=user,
        store=MockStore(),
        ai=MockAI(),
        skeleton=MockSkeleton(),
        billing=MockBilling(),
        notify=MockNotify(),
        storage=MockStorage(),
        http=MockHTTP(),
        config=MockConfig(config or {}),
        extensions=MockExtensions(),
        time=TimeContext(
            timezone="UTC",
            now_utc="2026-01-01T00:00:00Z",
            now_local="2026-01-01T00:00:00",
            hour_local=0,
        ),
        _extension_id=extension_id,
        _tool_type=tool_type,
    )
