from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

from app.apify import scrape_tagged_posts
from app.db import (
    claim_next_report,
    ensure_indexes,
    fail_report,
    finish_report,
    reports_collection,
)
from app.models import (
    actor_item_matches_tag,
    posts_in_period,
    rank_posts,
    report_post_from_actor,
    summarize_posts,
)


logging.basicConfig(level=os.environ["LOG_LEVEL"])
logger = logging.getLogger(__name__)


def process_next_report() -> bool:
    collection = reports_collection()
    report = claim_next_report(collection)
    if report is None:
        return False

    try:
        run_id, cost_usd, actor_items = scrape_tagged_posts(report.query)
        unique_by_url = {
            post.url: post
            for item in actor_items
            if actor_item_matches_tag(item, report.query.tag)
            if (post := report_post_from_actor(item)) is not None
        }
        filtered_posts = posts_in_period(unique_by_url.values(), report.query)
        ranked_posts = rank_posts(filtered_posts)
        sampled_at = datetime.now(timezone.utc)
        summary = summarize_posts(ranked_posts, sampled_at)
        finish_report(
            collection,
            report.id,
            posts=[post.model_dump(mode="python") for post in ranked_posts],
            summary=summary.model_dump(mode="python"),
            apify={
                "actor_id": os.environ["APIFY_ACTOR_ID"],
                "run_id": run_id,
                "cost_usd": cost_usd,
            },
        )
        logger.info("report %s completed with %s posts", report.id, len(ranked_posts))
    except Exception as error:
        fail_report(collection, report.id)
        logger.error("report %s failed (%s)", report.id, type(error).__name__)
    return True


def main() -> None:
    collection = reports_collection()
    ensure_indexes(collection)
    poll_seconds = float(os.environ["WORKER_POLL_SECONDS"])
    logger.info("worker started")
    while True:
        if not process_next_report():
            time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
