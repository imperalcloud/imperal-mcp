"""SecretSpec — declarative shape of one @ext.secret declaration."""
import re
from dataclasses import dataclass
from typing import Literal, Optional

SECRET_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
ALLOWED_WRITE_MODES = frozenset({"user", "extension", "both"})


@dataclass(frozen=True)
class SecretSpec:
    """One secret an extension declares it needs.

    Federal contract:
    - ``name`` is snake_case; auth-gw stores it scoped under (user_id, ext_id, name)
    - ``write_mode`` determines who can write the value: 'user' (Panel UI only),
      'extension' (ctx.secrets.set only), or 'both'
    - ``required=True`` triggers a dispatch-time gate — kernel blocks handler
      and emits secret_missing_card chat message if value not set
    - ``max_bytes`` caps both write payload and storage; hard ceiling 65536
    """

    name: str
    description: str
    required: bool = False
    write_mode: Literal["user", "extension", "both"] = "user"
    max_bytes: int = 4096
    rotation_hint_days: Optional[int] = None

    def __post_init__(self) -> None:
        if not SECRET_NAME_RE.match(self.name):
            raise ValueError(
                f"SecretSpec.name {self.name!r} fails regex "
                f"{SECRET_NAME_RE.pattern!r} (snake_case, start-letter, ≤63 chars)"
            )
        if self.write_mode not in ALLOWED_WRITE_MODES:
            raise ValueError(
                f"SecretSpec.write_mode {self.write_mode!r} must be one of "
                f"{sorted(ALLOWED_WRITE_MODES)}"
            )
        if not (1 <= self.max_bytes <= 65536):
            raise ValueError(
                f"SecretSpec.max_bytes {self.max_bytes!r} must be in [1, 65536]"
            )
        if self.rotation_hint_days is not None and self.rotation_hint_days < 1:
            raise ValueError(
                f"SecretSpec.rotation_hint_days {self.rotation_hint_days!r} "
                f"must be a positive integer or None"
            )
        if not self.description.strip():
            raise ValueError(
                "SecretSpec.description must be non-empty — Panel UI shows it "
                "to the user when they're entering the value"
            )

    def to_manifest_dict(self) -> dict:
        d = {
            "name": self.name,
            "description": self.description,
            "required": self.required,
            "write_mode": self.write_mode,
            "max_bytes": self.max_bytes,
        }
        if self.rotation_hint_days is not None:
            d["rotation_hint_days"] = self.rotation_hint_days
        return d
