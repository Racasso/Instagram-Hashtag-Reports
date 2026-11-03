import json
from pathlib import Path

from app.models import (
    ReportQuery,
    actor_item_matches_tag,
    posts_in_period,
    rank_posts,
    report_post_from_actor,
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
