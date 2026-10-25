#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import candidate_snapshot
import freehire_fetch as worker

SG_CATEGORY_SHARDS = (
    (
        "software_engineering",
        "backend",
        "frontend",
        "fullstack",
        "mobile",
    ),
    (
        "data_engineering",
        "data_science",
        "data_analytics",
        "ml_ai",
        "ai_engineering",
    ),
    ("qa",),
    (
        "security",
        "solutions_engineering",
        "devops",
        "sre",
        "network_engineering",
    ),
)
BROAD_CATEGORIES = tuple(
    category
    for shard in SG_CATEGORY_SHARDS
    for category in shard
)
BOOTSTRAP_EMIT_DAYS = 30

AI_CANDIDATE_MIN_SCORE = candidate_snapshot.AI_CANDIDATE_MIN_SCORE
AI_CANDIDATE_LIMIT_PER_MARKET = candidate_snapshot.AI_CANDIDATE_LIMIT_PER_MARKET
AI_CANDIDATE_EXCERPT_CHARS = candidate_snapshot.AI_CANDIDATE_EXCERPT_CHARS
ai_relevance = candidate_snapshot.ai_relevance
build_candidate_snapshot = candidate_snapshot.build_candidate_snapshot

_ORIGINAL_FETCH_MARKET = worker.fetch_market
_ORIGINAL_RUN = worker.run
_CAPTURED_JOBS: dict[str, list[dict]] = {}


def _capturing_fetch_market(
    fetch_json: Callable[[dict[str, object]], dict],
    country: str,
    mode: str,
    max_rows: int = worker.API_MAX_ROWS,
    page_size: int = worker.API_MAX_PAGE_SIZE,
) -> list[dict]:
    jobs = _ORIGINAL_FETCH_MARKET(
        fetch_json,
        country,
        mode,
        max_rows=max_rows,
        page_size=page_size,
    )
    _CAPTURED_JOBS[country.upper()] = [dict(job) for job in jobs]
    return jobs


def _run_with_candidate_snapshot(
    mode: str,
    root: Path,
    fetch_json: Callable[[dict[str, object]], dict] = worker.http_fetch,
    now=None,
) -> dict:
    _CAPTURED_JOBS.clear()
    health = _ORIGINAL_RUN(mode, root, fetch_json=fetch_json, now=now)

    eligible_jobs: dict[str, list[dict]] = {}
    for market in ("SG", "CN", "MY"):
        prepared: list[dict] = []
        for source_job in _CAPTURED_JOBS.get(market, []):
            hard_drop, flags = worker.machine_flags(source_job)
            if hard_drop:
                continue
            job = dict(source_job)
            job["_flags"] = flags
            prepared.append(job)
        eligible_jobs[market] = prepared

    snapshot = candidate_snapshot.build_candidate_snapshot(
        eligible_jobs,
        generated_at=str(health.get("last_success") or ""),
        mode=mode,
    )
    candidate_snapshot.write_candidate_snapshot(Path(root), snapshot)
    return health


def configure_worker() -> None:
    worker.DEFAULT_CATEGORIES = BROAD_CATEGORIES
    worker.MARKET_CATEGORY_SHARDS = {"SG": SG_CATEGORY_SHARDS}
    worker.BOOTSTRAP_EMIT_DAYS = BOOTSTRAP_EMIT_DAYS
    worker.fetch_market = _capturing_fetch_market
    worker.run = _run_with_candidate_snapshot


def main(argv: list[str] | None = None) -> int:
    configure_worker()
    return worker.main(argv)


if __name__ == "__main__":
    sys.exit(main())
