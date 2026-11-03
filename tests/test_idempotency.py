from typing import Any

from app.db import enqueue_report
from app.models import ReportQuery


class MemoryReportsCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    def update_one(
        self,
        selector: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool,
    ) -> None:
        report_id = selector["_id"]
        if upsert and report_id not in self.documents:
            self.documents[report_id] = update["$setOnInsert"]

    def find_one(self, selector: dict[str, Any]) -> dict[str, Any] | None:
        return self.documents.get(selector["_id"])


def test_repeated_enqueue_for_same_query_is_idempotent() -> None:
    collection = MemoryReportsCollection()
    query = ReportQuery(
        profile_url="boxpleasepl",
        tag="#Kawa",
        published_from="2026-10-01T00:00:00Z",
        published_to="2026-10-31T23:59:59Z",
        max_results=50,
    )

    first = enqueue_report(collection, query)  # type: ignore[arg-type]
    second = enqueue_report(collection, query)  # type: ignore[arg-type]

    assert first.id == second.id
    assert first.created_at == second.created_at
    assert len(collection.documents) == 1
