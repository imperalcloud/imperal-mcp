from __future__ import annotations

from typing import Any, Callable

from .schema import IR_VERSION

_MIGRATORS: dict[str, Callable[[dict], dict]] = {
    "1.0": lambda d: d,   # identity; future N.x migrators chain forward additively
}


def migrate_ir(data: dict[str, Any], to: str = IR_VERSION) -> dict[str, Any]:
    """Migrate an IR envelope to the target ir_version (additive chain).

    The registry ``_MIGRATORS`` is keyed by SOURCE ir_version.  To add a new
    version N+1 add a migrator keyed by N that returns a N+1 envelope, then
    update IR_VERSION in schema.py.  Chains are resolved additively: if
    migrators exist for 1.0→2.0 and 2.0→3.0, calling ``migrate_ir(data,
    to="3.0")`` will apply both in sequence (once chaining is needed; current
    release only carries 1.0).

    Raises:
        ValueError: unknown target version or no migrator registered for the
                    source ir_version found in *data*.
    """
    if to != IR_VERSION:
        raise ValueError(f"Unknown target ir_version {to!r} (current {IR_VERSION})")
    src = data.get("ir_version", IR_VERSION)
    migrate = _MIGRATORS.get(src)
    if migrate is None:
        raise ValueError(f"No migrator for ir_version {src!r}")
    return migrate(dict(data))
