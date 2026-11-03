from __future__ import annotations

import os
from datetime import timedelta
from decimal import Decimal
from typing import Any

from apify_client import ApifyClient

from app.models import ReportQuery


_client: ApifyClient | None = None


def apify_client() -> ApifyClient:
    global _client
    if _client is None:
        _client = ApifyClient(os.environ["APIFY_TOKEN"])
    return _client


def scrape_tagged_posts(query: ReportQuery) -> tuple[str, float | None, list[dict[str, Any]]]:
    actor_id = os.environ["APIFY_ACTOR_ID"]
    max_cost = Decimal(os.environ["MAX_APIFY_COST_USD"])
    price_per_result = Decimal(os.environ["APIFY_PRICE_PER_1000_RESULTS_USD"]) / 1000
    run_timeout_seconds = int(os.environ["APIFY_RUN_TIMEOUT_SECONDS"])
    wait_seconds = int(os.environ["APIFY_WAIT_SECONDS"])
    if max_cost <= 0 or price_per_result <= 0:
        raise ValueError("Apify cost settings must be greater than zero")
    affordable_results = int(max_cost / price_per_result)
    result_limit = min(query.max_results, affordable_results)
    if result_limit < 1:
        raise ValueError("Apify cost cap is below the estimated price of one result")

    client = apify_client()
    run = client.actor(actor_id).call(
        run_input={
            "usernames": [query.profile_url.rstrip("/").rsplit("/", 1)[-1]],
            "maxPostsPerProfile": result_limit,
            "newerThan": query.published_from.date().isoformat(),
            "olderThan": query.published_to.date().isoformat(),
            "onlyNew": False,
        },
        max_items=result_limit,
        max_total_charge_usd=max_cost,
        run_timeout=timedelta(seconds=run_timeout_seconds),
        wait_duration=timedelta(seconds=wait_seconds),
    )
    if run is None:
        raise RuntimeError("Apify did not return a run")
    if run.status != "SUCCEEDED":
        raise RuntimeError("Apify run did not succeed")
    if not run.default_dataset_id:
        raise RuntimeError("Apify run did not return a dataset ID")

    response = client.dataset(run.default_dataset_id).list_items(limit=result_limit)
    items = response.items
    cost = float(run.usage_total_usd) if run.usage_total_usd is not None else None
    return run.id, cost, items
