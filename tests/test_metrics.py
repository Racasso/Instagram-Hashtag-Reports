import json
from datetime import datetime, timezone
from pathlib import Path

from app.models import (
    ReportQuery,
    TagReport,
    actor_item_matches_tag,
    posts_in_period,
    rank_posts,
    report_post_from_actor,
    summarize_posts,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "instagram_tagged_boxpleasepl_sample.json"


def test_sample_posts_are_normalized_filtered_and_ranked() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    query = ReportQuery(
        profile_url="https://www.instagram.com/boxpleasepl/tagged/",
        tag="#smakujemyfivio",
        published_from="2026-10-01T00:00:00Z",
        published_to="2026-10-31T23:59:59Z",
        max_results=50,
    )

    posts = [
        normalized
        for item in fixture["items"]
        if actor_item_matches_tag(item, query.tag)
        if (normalized := report_post_from_actor(item)) is not None
    ]
    in_period = posts_in_period(posts, query)
    ranked = rank_posts(in_period)

    assert len(ranked) == 1
    first_raw = next(item for item in fixture["items"] if actor_item_matches_tag(item, query.tag))
    first_normalized = next(post for post in posts if post.url == first_raw["url"])
    assert first_normalized.metrics.likes == first_raw["likes"]
    assert first_normalized.metrics.comments == first_raw["comments"]
    assert first_normalized.metrics.engagement_count == (
        first_raw["likes"] + first_raw["comments"]
    )
    assert all(post.metrics.engagement_rate_percent is None for post in ranked)
    assert [post.rank for post in ranked] == [1]
    assert [post.metrics.engagement_count for post in ranked] == sorted(
        (post.metrics.engagement_count for post in ranked), reverse=True
    )


def test_zero_and_missing_likes_are_serialized_and_summed_as_zero() -> None:
    posts = []
    for index, likes in enumerate((0, None), start=1):
        post = report_post_from_actor(
            {
                "url": f"https://www.instagram.com/p/zero{index}/",
                "takenAt": "2026-10-20T11:04:26Z",
                "ownerUsername": "creator",
                "ownerFollowers": 100,
                "likes": likes,
                "comments": 4,
            }
        )
        assert post is not None
        assert post.metrics.likes == 0
        assert post.metrics.engagement_count == 4
        assert post.model_dump(mode="json")["metrics"]["likes"] == 0
        posts.append(post)

    summary = summarize_posts(posts, datetime(2026, 11, 5, tzinfo=timezone.utc))
    assert summary.total_likes == 0
    assert summary.total_comments == 8


def test_legacy_report_with_null_likes_serializes_zero_and_recalculates_totals() -> None:
    report = TagReport.model_validate(
        {
            "_id": "legacy-report",
            "created_at": "2026-11-05T00:00:00Z",
            "updated_at": "2026-11-05T00:00:00Z",
            "status": "done",
            "query": {
                "profile_url": "boxpleasepl",
                "tag": "#smakujemyfivio",
                "published_from": "2026-10-01T00:00:00Z",
                "published_to": "2026-10-31T23:59:59Z",
            },
            "summary": {
                "sampled_at": "2026-11-05T00:00:00Z",
                "posts_in_period": 1,
                "ranked_by": "likes_plus_comments",
                "total_likes": None,
                "total_comments": 4,
            },
            "posts": [
                {
                    "rank": 1,
                    "url": "https://www.instagram.com/p/legacy/",
                    "published_at": "2026-10-20T11:04:26Z",
                    "creator": {"username": "creator", "followers_count": None},
                    "metrics": {
                        "likes": None,
                        "comments": 4,
                        "engagement_count": None,
                        "engagement_rate_percent": None,
                    },
                }
            ],
        }
    )

    serialized = report.model_dump(mode="json", by_alias=True)
    assert serialized["posts"][0]["metrics"]["likes"] == 0
    assert serialized["posts"][0]["metrics"]["engagement_count"] == 4
    assert serialized["summary"]["total_likes"] == 0
