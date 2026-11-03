from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReportQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "profile_url": "https://www.instagram.com/boxpleasepl/tagged/",
                    "tag": "#smakujemyfivio",
                    "published_from": "2025-01-01T00:00:00Z",
                    "published_to": "2026-12-31T23:59:59Z",
                    "max_results": 50,
                }
            ]
        },
    )

    platform: Literal["instagram"] = "instagram"
    source: Literal["tagged"] = "tagged"
    profile_url: str = Field(
        description="Instagram profile URL or username. A /tagged/ URL is accepted."
    )
    tag: str = Field(description="Hashtag to match within posts from the profile's Tagged tab.")
    published_from: datetime = Field(description="Inclusive UTC start of the publication window.")
    published_to: datetime = Field(description="Inclusive UTC end of the publication window.")
    content_type: Literal["posts"] = Field(
        default="posts", description="Tagged feed entries (posts, videos, and reels)."
    )
    max_results: int = Field(default=50, ge=1, le=100)

    @field_validator("profile_url")
    @classmethod
    def normalize_profile_url(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            raise ValueError("profile_url is required")

        if "://" not in candidate and "/" not in candidate:
            username = candidate.removeprefix("@").strip()
        else:
            parsed = urlsplit(candidate if "://" in candidate else f"https://{candidate}")
            if parsed.netloc.casefold() not in {"instagram.com", "www.instagram.com"}:
                raise ValueError("profile_url must point to instagram.com")
            path_parts = [part for part in parsed.path.split("/") if part]
            if not path_parts or (len(path_parts) > 1 and path_parts[1] != "tagged"):
                raise ValueError("profile_url must be a profile URL or its /tagged/ tab")
            if len(path_parts) > 2:
                raise ValueError("profile_url contains an unsupported Instagram path")
            username = path_parts[0]

        if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", username):
            raise ValueError("profile_url must contain a valid Instagram username")
        return f"https://www.instagram.com/{username}/"

    @field_validator("tag")
    @classmethod
    def normalize_tag(cls, value: str) -> str:
        normalized = value.strip().lstrip("#").strip().casefold()
        if not normalized or any(char.isspace() or char in "#/?" for char in normalized):
            raise ValueError("tag must be one hashtag without spaces")
        return f"#{normalized}"

    @field_validator("published_from", "published_to")
    @classmethod
    def normalize_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("date bounds must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_period(self) -> ReportQuery:
        if self.published_from > self.published_to:
            raise ValueError("published_from must be earlier than published_to")
        return self


class Creator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    followers_count: int | None = None


class PostMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    likes: int | None = None
    comments: int | None = None
    engagement_count: int | None = None
    engagement_rate_percent: float | None = None


class ReportPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = 0
    url: str
    published_at: datetime
    creator: Creator
    metrics: PostMetrics


class ReportSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sampled_at: datetime
    posts_in_period: int
    ranked_by: Literal["likes_plus_comments"] = "likes_plus_comments"
    total_likes: int | None
    total_comments: int | None


class ApifyRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str
    run_id: str
    cost_usd: float | None = None


class TagReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(alias="_id")
    type: Literal["tag_report"] = "tag_report"
    schema_version: Literal[1] = 1
    created_at: datetime
    updated_at: datetime
    status: Literal["queued", "running", "done", "failed"] = "queued"
    query: ReportQuery
    summary: ReportSummary | None = None
    posts: list[ReportPost] = Field(default_factory=list)
    apify: ApifyRun | None = None


def report_id_for_query(query: ReportQuery) -> str:
    canonical_query = json.dumps(
        query.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_query.encode("utf-8")).hexdigest()


def _optional_count(value: Any) -> int | None:
    if value is None:
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


def report_post_from_actor(item: dict[str, Any]) -> ReportPost | None:
    """Normalize the confirmed fields in the saved tagged-post sample."""
    url = item.get("url")
    timestamp = item.get("takenAt")
    username = item.get("ownerUsername")
    if not all(isinstance(value, str) and value for value in (url, timestamp, username)):
        return None

    try:
        published_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if published_at.tzinfo is None or published_at.utcoffset() is None:
            return None
        published_at = published_at.astimezone(timezone.utc)
    except ValueError:
        return None

    likes = _optional_count(item.get("likes"))
    comments = _optional_count(item.get("comments"))
    followers = _optional_count(item.get("ownerFollowers"))
    engagement = likes + comments if likes is not None and comments is not None else None
    engagement_rate = (
        engagement / followers * 100
        if engagement is not None and followers is not None and followers > 0
        else None
    )

    return ReportPost(
        url=url,
        published_at=published_at,
        creator=Creator(username=username, followers_count=followers),
        metrics=PostMetrics(
            likes=likes,
            comments=comments,
            engagement_count=engagement,
            engagement_rate_percent=engagement_rate,
        ),
    )


def actor_item_matches_tag(item: dict[str, Any], tag: str) -> bool:
    target = tag.removeprefix("#").casefold()
    item_tags = item.get("hashtags")
    if isinstance(item_tags, list) and any(
        str(value).removeprefix("#").casefold() == target for value in item_tags
    ):
        return True
    if isinstance(item_tags, str) and any(
        value.removeprefix("#").casefold() == target
        for value in re.split(r"[\s,]+", item_tags)
    ):
        return True
    caption = item.get("caption")
    pattern = rf"(?<!\w)\#{re.escape(target)}(?!\w)"
    return isinstance(caption, str) and re.search(pattern, caption, flags=re.IGNORECASE) is not None


def rank_posts(posts: Iterable[ReportPost]) -> list[ReportPost]:
    ordered = sorted(
        posts,
        key=lambda post: (
            post.metrics.engagement_count is not None,
            post.metrics.engagement_count if post.metrics.engagement_count is not None else -1,
            post.metrics.likes if post.metrics.likes is not None else -1,
            post.metrics.comments if post.metrics.comments is not None else -1,
        ),
        reverse=True,
    )
    return [post.model_copy(update={"rank": index}) for index, post in enumerate(ordered, 1)]


def posts_in_period(posts: Iterable[ReportPost], query: ReportQuery) -> list[ReportPost]:
    return [
        post
        for post in posts
        if query.published_from <= post.published_at <= query.published_to
    ]


def summarize_posts(posts: list[ReportPost], sampled_at: datetime) -> ReportSummary:
    def complete_total(field: Literal["likes", "comments"]) -> int | None:
        values = [getattr(post.metrics, field) for post in posts]
        if not values:
            return 0
        if any(value is None for value in values):
            return None
        return sum(value for value in values if value is not None)

    return ReportSummary(
        sampled_at=sampled_at,
        posts_in_period=len(posts),
        total_likes=complete_total("likes"),
        total_comments=complete_total("comments"),
    )
