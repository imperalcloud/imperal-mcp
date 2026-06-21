from __future__ import annotations

from ..sdl.roles import validate_custom_role, RoleError
from ..validator import ValidationIssue


def validate_custom_roles(rows: list[dict]) -> list[ValidationIssue]:
    """Validate inline IR custom_roles against the reserved-namespace rule. Aggregates."""
    issues: list[ValidationIssue] = []
    for row in rows:
        role = row.get("role", "")
        try:
            validate_custom_role(role)
        except RoleError as exc:
            issues.append(ValidationIssue(rule="IR-ROLE", level="ERROR", message=str(exc)))
    return issues
