# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
from __future__ import annotations
from dataclasses import dataclass, field
import httpx


@dataclass
class CompletionResult:
    text: str
    model: str = ""
    usage: dict = field(default_factory=dict)
    stop_reason: str = ""
    # Backward compat: tokens_used mirrors usage total_tokens when available
    tokens_used: int = 0


class AIClient:
    """AI completion client. Usage auto-metered by platform."""

    def __init__(self, gateway_url: str, auth_token: str = "", extension_id: str = "", service_token: str = ""):
        self._gateway_url = gateway_url.rstrip("/")
        self._service_token = service_token
        self._auth_token = auth_token
        self._extension_id = extension_id

    async def complete(self, prompt: str, model: str = "claude-sonnet-4-6", **kwargs) -> CompletionResult:
        headers = {}
        if self._service_token:
            headers["X-Service-Token"] = self._service_token
        elif self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._gateway_url}/v1/internal/ai/complete",
                json={
                    "prompt": prompt,
                    "model": model,
                    "extension_id": self._extension_id,
                    **kwargs,
                },
                headers=headers,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage", {})
            tokens_used = data.get("tokens_used", usage.get("total_tokens", 0))
            return CompletionResult(
                text=data.get("text", ""),
                model=data.get("model", model),
                usage=usage,
                stop_reason=data.get("stop_reason", ""),
                tokens_used=tokens_used,
            )
