"""Event types for the Imperal SDK event system and webhook ingestion."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Event:
    """Base event type. All platform events carry this structure."""
    event_type: str
    timestamp: str = ""
    user_id: str = ""
    tenant_id: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class WebhookRequest:
    """Incoming webhook request from external service."""
    method: str
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    query_params: dict = field(default_factory=dict)

    def json(self) -> dict:
        import json
        return json.loads(self.body)

    def text(self) -> str:
        return self.body.decode("utf-8")


@dataclass
class WebhookResponse:
    """Response to return from a webhook handler."""
    status_code: int = 200
    body: dict | str = ""
    headers: dict = field(default_factory=dict)

    @staticmethod
    def ok(body: dict | str = "OK") -> WebhookResponse:
        return WebhookResponse(status_code=200, body=body)

    @staticmethod
    def error(message: str, status: int = 400) -> WebhookResponse:
        return WebhookResponse(status_code=status, body={"error": message})
