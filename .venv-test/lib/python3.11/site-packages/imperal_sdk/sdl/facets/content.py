"""Content & Documents family — body, excerpts, categorization, attachments, editorial.
Namespace content.*"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from imperal_sdk.sdl.entity import Ref
from imperal_sdk.sdl.field import _facet_field


class Bodied(BaseModel):
    body: str | None = _facet_field(role="content.body")
    body_format: Literal["md", "html", "plain", "rich"] | None = _facet_field(role="content.body_format")
    raw_body: str | None = _facet_field(role="content.raw_body")


class Excerptable(BaseModel):
    excerpt: str | None = _facet_field(role="content.excerpt")
    summary: str | None = _facet_field(role="content.summary")
    word_count: int | None = _facet_field(role="content.word_count")
    reading_time_s: int | None = _facet_field(role="content.reading_time_s")


class Categorized(BaseModel):
    tags: list[str] | None = _facet_field(role="content.tags")
    categories: list[Ref] | None = _facet_field(role="content.categories")
    topics: list[str] | None = _facet_field(role="content.topics")
    keywords: list[str] | None = _facet_field(role="content.keywords")
    labels: list[Ref] | None = _facet_field(role="content.labels")


class Attached(BaseModel):
    attachments: list[Ref] | None = _facet_field(role="content.attachments")
    attachment_count: int | None = _facet_field(role="content.attachment_count")
    has_attachments: bool | None = _facet_field(role="content.has_attachments")
    inline_images: list[Ref] | None = _facet_field(role="content.inline_images")


class Editorial(BaseModel):
    editorial_state: Literal["draft", "in_review", "approved", "published", "scheduled", "archived"] | None = _facet_field(role="content.editorial_state")
    # Prefixed to avoid collision with comm.Draftable.is_draft (role comm.is_draft)
    editorial_is_draft: bool | None = _facet_field(role="content.is_draft")
    published_at: datetime | None = _facet_field(role="content.published_at")
    first_published_at: datetime | None = _facet_field(role="content.first_published_at")
