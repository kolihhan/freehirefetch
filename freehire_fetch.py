#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_URL = "https://freehire.me/api/v1/jobs/search"
API_MAX_ROWS = 10_000
API_MAX_PAGE_SIZE = 100
DELTA_OPEN_WITHIN_DAYS = 2
BOOTSTRAP_EMIT_DAYS = 7
RETENTION_DAYS = 30
DEFAULT_CATEGORIES = (
    "backend",
    "fullstack",
    "data_engineering",
    "ml_ai",
    "ai_engineering",
    "solutions_engineering",
    "devops",
    "sre",
)

_TITLE_HARD_DROP = re.compile(
    r"\b(senior|staff|principal|lead|director|manager|intern|internship)\b|\bhead\s+of\b",
    re.IGNORECASE,
)
_HARD_SENIORITY_HINTS = {"senior", "lead", "staff", "principal", "c_level", "manager", "director"}
_AGENCY_HINTS = {"agency", "outstaff", "outsource", "outsourcing"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def page_offsets(max_rows: int = API_MAX_ROWS, page_size: int = API_MAX_PAGE_SIZE) -> list[int]:
    if page_size < 1 or page_size > API_MAX_PAGE_SIZE:
        raise ValueError("page_size must be between 1 and 100")
    max_rows = max(0, min(max_rows, API_MAX_ROWS))
    return list(range(0, max_rows, page_size))


def build_params(country: str, mode: str, offset: int, page_size: int = API_MAX_PAGE_SIZE) -> dict[str, object]:
    params: dict[str, object] = {
        "countries": country.upper(),
        "category": ",".join(DEFAULT_CATEGORIES),
        "sort": "created_at",
        "order": "desc",
        "limit": page_size,
        "offset": offset,
    }
    if mode == "delta":
        params["open_within_days"] = DELTA_OPEN_WITHIN_DAYS
    elif mode not in {"bootstrap", "full"}:
        raise ValueError(f"unsupported mode: {mode}")
    return params


def http_fetch(params: dict[str, object], timeout: int = 30, retries: int = 2) -> dict:
    url = f"{API_URL}?{urlencode(params)}"
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(url, headers={"User-Agent": "kolihhan-freehirefetch/1.0"})
            with urlopen(request, timeout=timeout) as response:
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(f"FreeHire HTTP {response.status}")
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"FreeHire request failed after {retries + 1} attempts: {last_error}")


def fetch_market(
    fetch_json: Callable[[dict[str, object]], dict],
    country: str,
    mode: str,
    max_rows: int = API_MAX_ROWS,
    page_size: int = API_MAX_PAGE_SIZE,
) -> list[dict]:
    jobs: list[dict] = []
    for offset in page_offsets(max_rows=max_rows, page_size=page_size):
        payload = fetch_json(build_params(country, mode, offset, page_size))
        if not isinstance(payload, dict):
            raise RuntimeError("FreeHire returned malformed payload")
        meta = payload.get("meta")
        data = payload.get("data")
        if not isinstance(meta, dict) or not isinstance(data, list):
            raise RuntimeError("FreeHire response missing data/meta")
        ignored = meta.get("ignored_params") or []
        if ignored:
            raise RuntimeError(f"FreeHire ignored requested params: {', '.join(map(str, ignored))}")
        clean_page = [item for item in data if isinstance(item, dict)]
        jobs.extend(clean_page)
        total = int(meta.get("total", len(jobs)))
        if not data or len(jobs) >= total or len(jobs) >= max_rows:
            break
    return jobs[:max_rows]


def machine_flags(job: dict) -> tuple[bool, list[str]]:
    title = str(job.get("title") or "").strip()
    enrichment = job.get("enrichment") if isinstance(job.get("enrichment"), dict) else {}
    flags: list[str] = []
    hard_drop = bool(_TITLE_HARD_DROP.search(title))
    if hard_drop:
        flags.append("title_hard_drop")

    years = enrichment.get("experience_years_min")
    if isinstance(years, (int, float)) and years >= 5:
        flags.append("experience_5_plus_hint")
    if str(enrichment.get("seniority") or "").lower() in _HARD_SENIORITY_HINTS:
        flags.append("seniority_hint")
    if str(enrichment.get("company_type") or "").lower() in _AGENCY_HINTS:
        flags.append("agency_or_outstaff_hint")
    if any(key in enrichment for key in ("visa_sponsorship", "work_authorization", "sponsorship")):
        flags.append("visa_hint")
    return hard_drop, flags


def _norm(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def job_identity(job: dict) -> str:
    slug = _norm(job.get("public_slug"))
    if slug:
        return slug
    parts = [
        _norm(job.get("company_name") or job.get("company")),
        _norm(job.get("title")),
        _norm(job.get("location") or job.get("market")),
        _norm(job.get("external_id") or job.get("source_job_id") or job.get("source_url")),
    ]
    return "fallback:" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def content_fingerprint(job: dict) -> str:
    enrichment = job.get("enrichment") if isinstance(job.get("enrichment"), dict) else {}
    meaningful = {
        "title": job.get("title"),
        "company": job.get("company_name") or job.get("company"),
        "location": job.get("location") or job.get("market"),
        "description": job.get("description"),
        "source_url": job.get("source_url") or job.get("apply_url") or job.get("application_url"),
        "freehire_url": job.get("freehire_url") or job.get("url"),
        "external_id": job.get("external_id") or job.get("source_job_id"),
        "employment_type": enrichment.get("employment_type") or job.get("employment_type"),
        "seniority": enrichment.get("seniority"),
        "experience_years_min": enrichment.get("experience_years_min"),
        "company_type": enrichment.get("company_type"),
    }
    raw = json.dumps(meaningful, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _bootstrap_recent(job: dict, now: datetime) -> bool:
    first_seen = _parse_iso(job.get("created_at"))
    if first_seen is None:
        return True
    return first_seen >= now - timedelta(days=BOOTSTRAP_EMIT_DAYS)


def classify_events(jobs: list[dict], seen: dict, now_iso: str, bootstrap: bool) -> tuple[list[dict], dict]:
    now = _parse_iso(now_iso) or _utcnow()
    next_seen = {key: dict(value) for key, value in seen.items()}
    events: list[dict] = []
    for job in jobs:
        identity = job_identity(job)
        fingerprint = content_fingerprint(job)
        hard_drop, flags = machine_flags(job)
        previous = next_seen.get(identity)
        kind = None
        if previous is None:
            kind = "NEW"
        elif previous.get("fingerprint") != fingerprint:
            kind = "CHANGED"

        next_seen[identity] = {
            "fingerprint": fingerprint,
            "last_seen": now_iso,
            "public_slug": job.get("public_slug"),
            "market": job.get("market") or job.get("country") or job.get("countries"),
        }
        if hard_drop or kind is None:
            continue
        if bootstrap and kind == "NEW" and not _bootstrap_recent(job, now):
            continue

        events.append(
            {
                "kind": kind,
                "identity": identity,
                "market": job.get("market") or job.get("country") or job.get("countries"),
                "public_slug": job.get("public_slug"),
                "company": job.get("company_name") or job.get("company"),
                "title": job.get("title"),
                "location": job.get("location"),
                "source_url": job.get("source_url") or job.get("apply_url") or job.get("application_url"),
                "freehire_url": job.get("freehire_url") or job.get("url"),
                "detected_at": now_iso,
                "fingerprint": fingerprint,
                "flags": flags,
                "job": job,
            }
        )
    return events, next_seen


def apply_retention(
    seen: dict,
    events: list[dict],
    now: datetime,
    current_identities: set[str],
) -> tuple[dict, list[dict]]:
    cutoff = now.astimezone(timezone.utc) - timedelta(days=RETENTION_DAYS)

    kept_events: list[dict] = []
    for event in events:
        detected = _parse_iso(event.get("detected_at"))
        if detected is None or detected >= cutoff:
            kept_events.append(event)

    kept_seen: dict = {}
    for identity, entry in seen.items():
        last_seen = _parse_iso(entry.get("last_seen")) if isinstance(entry, dict) else None
        if identity in current_identities or last_seen is None or last_seen >= cutoff:
            kept_seen[identity] = entry
    return kept_seen, kept_events


def load_public_state(root: Path) -> tuple[dict, list[dict], dict]:
    seen_path = root / "state" / "seen.json"
    events_path = root / "feed" / "events.jsonl"
    health_path = root / "health.json"

    if seen_path.exists():
        seen = json.loads(seen_path.read_text(encoding="utf-8"))
    else:
        seen = {}

    events: list[dict] = []
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))

    if health_path.exists():
        health = json.loads(health_path.read_text(encoding="utf-8"))
    else:
        health = {}
    return seen, events, health


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


def _events_jsonl(events: list[dict]) -> str:
    return "".join(json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str) + "\n" for event in events)


def run(
    mode: str,
    root: Path,
    fetch_json: Callable[[dict[str, object]], dict] = http_fetch,
    now: datetime | None = None,
) -> dict:
    if mode not in {"bootstrap", "delta", "full"}:
        raise ValueError(f"unsupported mode: {mode}")
    now = (now or _utcnow()).astimezone(timezone.utc)
    now_iso = _iso(now)
    previous_seen, previous_events, previous_health = load_public_state(root)

    market_jobs = {
        "SG": fetch_market(fetch_json, "SG", mode),
        "CN": fetch_market(fetch_json, "CN", mode),
    }

    next_seen = {key: dict(value) for key, value in previous_seen.items()}
    new_events: list[dict] = []
    market_stats: dict[str, dict[str, int]] = {}
    current_identities: set[str] = set()

    for market in ("SG", "CN"):
        jobs = []
        hard_drops = 0
        for source_job in market_jobs[market]:
            job = dict(source_job)
            job.setdefault("market", market)
            jobs.append(job)
            current_identities.add(job_identity(job))
            if machine_flags(job)[0]:
                hard_drops += 1
        classified, next_seen = classify_events(jobs, next_seen, now_iso, bootstrap=(mode == "bootstrap"))
        new_events.extend(classified)
        market_stats[market] = {"fetched": len(jobs), "title_hard_drops": hard_drops}

    last_seq = int(previous_health.get("last_seq") or max((int(e.get("seq", 0)) for e in previous_events), default=0))
    new_count = 0
    changed_count = 0
    for event in new_events:
        last_seq += 1
        event["seq"] = last_seq
        if event["kind"] == "NEW":
            new_count += 1
        elif event["kind"] == "CHANGED":
            changed_count += 1

    combined_events = previous_events + new_events
    next_seen, combined_events = apply_retention(next_seen, combined_events, now, current_identities)
    first_seq = int(combined_events[0]["seq"]) if combined_events else last_seq
    health = {
        "last_success": now_iso,
        "mode": mode,
        "markets": market_stats,
        "new": new_count,
        "changed": changed_count,
        "first_seq": first_seq,
        "last_seq": last_seq,
        "retained_events": len(combined_events),
    }

    _atomic_write_text(root / "state" / "seen.json", json.dumps(next_seen, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n")
    _atomic_write_text(root / "feed" / "events.jsonl", _events_jsonl(combined_events))
    _atomic_write_text(root / "health.json", json.dumps(health, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n")
    return health


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and deduplicate FreeHire SG/CN engineering jobs.")
    parser.add_argument("--mode", choices=["bootstrap", "delta", "full"], default="delta")
    parser.add_argument("--root", default=".", help="Repository root containing feed/, state/, health.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    health = run(args.mode, Path(args.root))
    print(json.dumps(health, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
