#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

DEFAULT_PAGE_SIZE = 50


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _jsonl(rows: list[dict]) -> str:
    return "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str) + "\n"
        for row in rows
    )


def build_pages(root: Path, page_size: int = DEFAULT_PAGE_SIZE) -> dict:
    if page_size < 1:
        raise ValueError("page_size must be >= 1")

    feed_dir = root / "feed"
    events_path = feed_dir / "events.jsonl"
    health_path = root / "health.json"
    pages_dir = feed_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else {}
    events: list[dict] = []
    if events_path.exists():
        for raw in events_path.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                event = json.loads(raw)
                if not isinstance(event, dict) or not isinstance(event.get("seq"), int):
                    raise ValueError("every feed event must be an object with integer seq")
                events.append(event)

    events.sort(key=lambda event: event["seq"])
    seqs = [event["seq"] for event in events]
    if len(seqs) != len(set(seqs)):
        raise ValueError("duplicate seq in feed/events.jsonl")

    desired_paths: set[Path] = set()
    pages: list[dict] = []
    for start in range(0, len(events), page_size):
        chunk = events[start : start + page_size]
        first_seq = chunk[0]["seq"]
        last_seq = chunk[-1]["seq"]
        rel_path = Path("feed") / "pages" / f"{first_seq:010d}-{last_seq:010d}.jsonl"
        page_path = root / rel_path
        _atomic_write_text(page_path, _jsonl(chunk))
        desired_paths.add(page_path)
        pages.append(
            {
                "path": rel_path.as_posix(),
                "first_seq": first_seq,
                "last_seq": last_seq,
                "count": len(chunk),
            }
        )

    for stale in pages_dir.glob("*.jsonl"):
        if stale not in desired_paths:
            stale.unlink()

    first_seq = events[0]["seq"] if events else int(health.get("first_seq") or 0)
    last_seq = events[-1]["seq"] if events else int(health.get("last_seq") or 0)
    index = {
        "first_seq": first_seq,
        "last_seq": last_seq,
        "page_size": page_size,
        "pages": pages,
    }
    _atomic_write_text(
        feed_dir / "index.json",
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build small sequence-addressable pages from the public FreeHire event feed."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    args = parser.parse_args(argv)
    index = build_pages(Path(args.root), page_size=args.page_size)
    print(json.dumps(index, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
