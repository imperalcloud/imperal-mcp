"""HealthStatus for extension health checks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class HealthStatus:
    """Returned from @ext.health_check. Kernel calls every 60s."""
    status: Literal["ok", "degraded", "unhealthy"]
    message: str = ""
    details: dict = field(default_factory=dict)

    @staticmethod
    def ok(details: dict | None = None) -> HealthStatus:
        return HealthStatus(status="ok", details=details or {})

    @staticmethod
    def degraded(message: str) -> HealthStatus:
        return HealthStatus(status="degraded", message=message)

    @staticmethod
    def unhealthy(message: str) -> HealthStatus:
        return HealthStatus(status="unhealthy", message=message)
