# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Agency theme accessor.

Extensions read the active agency's white-label theme via ``ui.theme(ctx)``
and return a typed, frozen ``AgencyTheme`` dataclass. The theme is populated
by the kernel on workflow start from the agency record; by the time the
extension runs, it is a passthrough with no network round-trip.

For most visual work, an extension does NOT need to read the theme — it
emits semantic intent (``variant='primary'``, ``color='success'``) and the
Panel resolves against the cascaded CSS vars. This helper exists for the
rare case where an extension renders domain-specific pixels (e.g. a
tint-variant swatch) and needs the agency's primary hue directly.

Example:

    from imperal_sdk import ui

    async def my_tool(ctx):
        theme = ui.theme(ctx)
        primary_hex = theme.colors["primary"].light if "primary" in theme.colors else "#2563eb"
        return ui.Card(title="Report", ...)

Contract: mirrors the Auth GW / Panel ``AgencyTheme`` schema — same keys,
same enum values. See ``app/models/agency_theme.py`` on Auth GW for the
authoritative validator; this SDK layer performs no validation (data is
already validated upstream) and falls back to defaults on any type mismatch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from imperal_sdk.context import Context


@dataclass(frozen=True, slots=True)
class ColorPair:
    """Light / dark colour pair. Values are CSS-valid strings (hex, rgb, oklch)."""
    light: str
    dark: str


@dataclass(frozen=True, slots=True)
class AgencyTheme:
    """Typed view over ``Context.agency_theme``. Empty = Imperal defaults."""
    colors: dict[str, ColorPair] = field(default_factory=dict)
    density: Literal["compact", "default", "spacious"] = "default"
    radius:  Literal["sharp", "default", "rounded"]    = "default"


def _from_dict(data: dict | None) -> AgencyTheme:
    """Convert a raw dict (as stored in agencies.theme) into an AgencyTheme.

    Unrecognised fields are ignored; mismatched types fall back to defaults.
    This is a passthrough — validation happens upstream at the Auth GW
    boundary (``AgencyTheme`` Pydantic model) before the payload ever
    reaches the kernel.
    """
    if not data or not isinstance(data, dict):
        return AgencyTheme()

    colors_raw = data.get("colors") or {}
    colors: dict[str, ColorPair] = {}
    if isinstance(colors_raw, dict):
        for key, pair in colors_raw.items():
            if isinstance(pair, dict) and "light" in pair and "dark" in pair:
                light = pair["light"]
                dark = pair["dark"]
                if isinstance(light, str) and isinstance(dark, str):
                    colors[key] = ColorPair(light=light, dark=dark)

    density_raw = data.get("density", "default")
    density: Literal["compact", "default", "spacious"] = (
        density_raw if density_raw in ("compact", "default", "spacious") else "default"
    )

    radius_raw = data.get("radius", "default")
    radius: Literal["sharp", "default", "rounded"] = (
        radius_raw if radius_raw in ("sharp", "default", "rounded") else "default"
    )

    return AgencyTheme(colors=colors, density=density, radius=radius)


def theme(ctx: "Context | None" = None) -> AgencyTheme:
    """Return the active agency's theme, or an empty theme if none is set.

    ``ctx`` is the extension's current ``Context``. Passing ``None`` returns
    the default Imperal theme — handy in unit tests where no context exists.
    """
    if ctx is None:
        return AgencyTheme()
    return _from_dict(getattr(ctx, "agency_theme", None))
