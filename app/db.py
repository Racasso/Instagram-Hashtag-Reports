from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, MongoClient, ReturnDocument
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from app.models import ReportQuery, TagReport, report_id_for_query


_client: MongoClient[dict[str, Any]] | None = None


def reports_collection() -> Collection[dict[str, Any]]:
    global _client
    if _client is None:
        mongo_uri = os.environ["MONGODB_URI"]
        _client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000, tz_aware=True)
    database_name = os.environ["MONGODB_DATABASE"]
    return _client[database_name]["reports"]


def ensure_indexes(collection: Collection[dict[str, Any]]) -> None:
    collection.create_index(
        [("status", ASCENDING), ("created_at", ASCENDING)],
        name="queued_reports_by_age",
    )
    report_query_index = [
        ("query.profile_url", ASCENDING),
        ("query.tag", ASCENDING),
        ("query.published_from", ASCENDING),
        ("query.published_to", ASCENDING),
        ("query.content_type", ASCENDING),
        ("query.max_results", ASCENDING),
    ]
    existing_indexes = collection.index_information()
    old_report_query_index = existing_indexes.get("unique_report_query")
    if old_report_query_index is not None and old_report_query_index.get("key") != report_query_index:
        collection.drop_index("unique_report_query")
    collection.create_index(
        report_query_index,
        unique=True,
        name="unique_report_query",
    )


def enqueue_report(
    collection: Collection[dict[str, Any]], query: ReportQuery
) -> TagReport:
    now = datetime.now(timezone.utc)
    report = TagReport(
        id=report_id_for_query(query),
        created_at=now,
        updated_at=now,
        status="queued",
        query=query,
    )
    try:
        collection.update_one(
            {"_id": report.id},
            {"$setOnInsert": report.model_dump(by_alias=True, mode="python")},
            upsert=True,
        )
    except DuplicateKeyError:
        # A concurrent identical POST may win the insert race on MongoDB's _id index.
        pass
    stored = collection.find_one({"_id": report.id})
    if stored is None:
        raise RuntimeError("report upsert did not create a document")
    return TagReport.model_validate(stored)


def get_report(collection: Collection[dict[str, Any]], report_id: str) -> TagReport | None:
    document = collection.find_one({"_id": report_id})
    return TagReport.model_validate(document) if document is not None else None


def claim_next_report(collection: Collection[dict[str, Any]]) -> TagReport | None:
    document = collection.find_one_and_update(
        {"status": "queued"},
        {
            "$set": {
                "status": "running",
                "updated_at": datetime.now(timezone.utc),
            }
        },
        sort=[("created_at", ASCENDING)],
        return_document=ReturnDocument.AFTER,
    )
    return TagReport.model_validate(document) if document is not None else None


def finish_report(
    collection: Collection[dict[str, Any]],
    report_id: str,
    *,
    posts: list[dict[str, Any]],
    summary: dict[str, Any],
    apify: dict[str, Any],
) -> None:
    collection.update_one(
        {"_id": report_id},
        {
            "$set": {
                "status": "done",
                "posts": posts,
                "summary": summary,
                "apify": apify,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )


def fail_report(collection: Collection[dict[str, Any]], report_id: str) -> None:
    collection.update_one(
        {"_id": report_id},
        {
            "$set": {
                "status": "failed",
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )
