"""Identity & Provenance family — localization, versioning, icons, lifecycle. Namespace core.*"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from imperal_sdk.sdl.entity import Ref
from imperal_sdk.sdl.field import _facet_field


class Localized(BaseModel):
    language: str | None = _facet_field(role="core.language")
    languages: list[str] | None = _facet_field(role="core.languages")
    text_direction: Literal["ltr", "rtl", "auto"] | None = _facet_field(role="core.text_direction")
    locale: str | None = _facet_field(role="core.locale")
    localized_title: dict[str, str] | None = _facet_field(role="core.localized_title")
    localized_description: dict[str, str] | None = _facet_field(role="core.localized_description")
    available_locales: list[str] | None = _facet_field(role="core.available_locales")


class Versioned(BaseModel):
    version: str | None = _facet_field(role="core.version")
    semver: str | None = _facet_field(role="core.semver")
    revision: int | None = _facet_field(role="core.revision")
    revision_of: Ref | None = _facet_field(role="core.revision_of")
    is_latest: bool | None = _facet_field(role="core.is_latest")
    content_hash: str | None = _facet_field(role="core.content_hash")
    channel: Literal["stable", "beta", "rc", "nightly", "dev"] | None = _facet_field(role="core.channel")
    released_at: datetime | None = _facet_field(role="core.released_at")


class Iconified(BaseModel):
    icon: str | None = _facet_field(role="core.icon")
    emoji: str | None = _facet_field(role="core.emoji")
    color_hex: str | None = _facet_field(role="core.color_hex")
    avatar_url: str | None = _facet_field(role="core.avatar_url")


class Lifecycle(BaseModel):
    is_archived: bool | None = _facet_field(role="core.is_archived")
    is_pinned: bool | None = _facet_field(role="core.is_pinned")
    is_favorite: bool | None = _facet_field(role="core.is_favorite")
    is_deleted: bool | None = _facet_field(role="core.is_deleted")
    visibility: Literal["private", "team", "organization", "public"] | None = _facet_field(role="core.visibility")
