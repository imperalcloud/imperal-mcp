from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_API_URL = "https://auth.imperal.io"


@dataclass(frozen=True)
class Config:
    api_url: str
    token: str | None

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            api_url=os.environ.get("IMPERAL_API_URL", DEFAULT_API_URL).rstrip("/"),
            token=os.environ.get("IMPERAL_TOKEN") or None,
        )
