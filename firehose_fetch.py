#!/usr/bin/env python3
from __future__ import annotations

import sys

import freehire_fetch as worker

BROAD_CATEGORIES = (
    "software_engineering",
    "backend",
    "frontend",
    "fullstack",
    "mobile",
    "data_engineering",
    "data_science",
    "data_analytics",
    "ml_ai",
    "ai_engineering",
    "qa",
    "security",
    "solutions_engineering",
    "developer_relations",
    "technical_writing",
    "devops",
    "sre",
    "network_engineering",
)
BOOTSTRAP_EMIT_DAYS = 30


def configure_worker() -> None:
    worker.DEFAULT_CATEGORIES = BROAD_CATEGORIES
    worker.BOOTSTRAP_EMIT_DAYS = BOOTSTRAP_EMIT_DAYS


def main(argv: list[str] | None = None) -> int:
    configure_worker()
    return worker.main(argv)


if __name__ == "__main__":
    sys.exit(main())
