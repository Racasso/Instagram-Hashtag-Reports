from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, status

from app.db import enqueue_report, ensure_indexes, get_report, reports_collection
from app.models import ReportQuery, TagReport


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    ensure_indexes(reports_collection())
    yield


app = FastAPI(
    title="Instagram Tagged Hashtag Reports",
    description=(
        "Create engagement reports for posts in an Instagram profile's Tagged tab "
        "that contain a selected hashtag. Submit a request in Swagger at /docs."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/reports", status_code=status.HTTP_202_ACCEPTED)
def create_report(query: ReportQuery) -> dict[str, str]:
    report = enqueue_report(reports_collection(), query)
    return {"id": report.id, "status": report.status}


@app.get("/reports/{report_id}", response_model=TagReport)
def read_report(report_id: str) -> TagReport:
    report = get_report(reports_collection(), report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report
