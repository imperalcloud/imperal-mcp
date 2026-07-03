"""Ratings & Feedback family — ratings, reviews, sentiment, votes. Namespace rating.*"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from imperal_sdk.sdl.field import _facet_field


class Rated(BaseModel):
    rating: float | None = _facet_field(role="rating.rating")
    max_score: float | None = _facet_field(role="rating.max_score")
    rating_count: int | None = _facet_field(role="rating.rating_count")
    distribution: dict[str, int] | None = _facet_field(role="rating.distribution")


class Reviewed(BaseModel):
    review_body: str | None = _facet_field(role="rating.review_body")
    is_verified: bool | None = _facet_field(role="rating.is_verified")
    helpfulness: int | None = _facet_field(role="rating.helpfulness")
    would_recommend: bool | None = _facet_field(role="rating.would_recommend")


class Sentiment(BaseModel):
    sentiment: Literal["positive", "negative", "neutral", "mixed"] | None = _facet_field(role="rating.sentiment")
    sentiment_score: float | None = _facet_field(role="rating.sentiment_score")
    magnitude: float | None = _facet_field(role="rating.magnitude")


class Voted(BaseModel):
    upvotes: int | None = _facet_field(role="rating.upvotes")
    downvotes: int | None = _facet_field(role="rating.downvotes")
    score: int | None = _facet_field(role="rating.score")
    my_vote: Literal["up", "down", "none"] | None = _facet_field(role="rating.my_vote")
