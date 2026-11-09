#!/usr/bin/env python3
"""Public ATS-first job discovery. No browser, credentials or private applicant data.

This produces a *discovery feed*, not eligibility decisions or applications.
All ATS boards must be explicitly configured with their verified career URLs.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import signal
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
API_TIMEOUT = 20
MAX_PAGES = 100
MAX_BOARD_SECONDS = 40  # bounded failure isolation on GitHub's Linux runner
USER_AGENT = "job-resources-ats-discovery/1.0 (public-job-board-feed; GitHub Actions)"
ALLOWED_ATS = {"greenhouse", "ashby", "lever", "smartrecruiters", "workday"}
AI_TERMS = re.compile(
    r"\b(llm|nlp|rag|genai|agentic|agents?|mcp|retrieval|"
    r"machine learning|deep learning|artificial intelligence|"
    r"generative ai|ai engineer|ml engineer|mlops|ai platform|"
    r"ai safety|ai evaluation|language model|applied ai|"
    r"data scientist|research engineer)\b|大模型|智能体|机器学习|人工智能|检索|算法|模型评测",
    re.I,
)
TECH_TITLES = re.compile(
    r"\b(software|backend|back.end|full.stack|fullstack|research|"
    r"scientist|data scientist|applied scientist|algorithm|data engineer|"
    r"platform engineer|ai|ml|nlp|engineer)\b|开发|工程师|研究员|科学家|算法",
    re.I,
)
# This is a conservative pre-review gate, not an eligibility decision.
# Seniority, user history and work authorization are decided downstream.
NON_ENGINEERING_TITLE = re.compile(
    r"\b(ceo|chief executive|chief of staff|chief technology|"
    r"vice president|vp|director|head of|business unit head|"
    r"engineering manager|product manager|product owner|product lead|"
    r"recruiter|talent acquisition|account executive|sales|"
    r"business development|designer|design lead|marketing|operations manager|"
    r"intern|internship)\b",
    re.I,
)
# An AI product name does not mean the engineer builds AI.
CORE_AI_ENGINEERING_TITLE = re.compile(
    r"\b(ai|ml|llm|nlp|machine learning|data scientist|research|"
    r"agentic|agents?|rag|retrieval|generative ai|model|algorithm)\b|"
    r"算法|大模型|智能体|机器学习|人工智能|检索|研究",
    re.I,
)

REGIONS = {
    "SG": re.compile(r"\bsingapore\b|\bsg\b|新加坡|ntu main campus", re.I),
    "MY": re.compile(
        r"\bmalaysia\b|\bmy\b|kuala lumpur|petaling jaya|shah alam|cyberjaya|"
        r"penang|selangor|johor|bayan lepas|kulim|george town|ipoh|putrajaya|alor setar",
        re.I,
    ),
    "CN": re.compile(
        r"\bchina\b|\bcn\b|prc|beijing|shanghai|shenzhen|hangzhou|chengdu|"
        r"guangzhou|suzhou|nanjing|wuhan|hefei|tianjin|xian|xi'an|"
        r"中国|北京|上海|深圳|杭州|成都|广州|苏州|南京|武汉|合肥|天津|西安",
        re.I,
    ),
}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain(value: object) -> str:
    value = str(value or "")
    parser = _Text()
    parser.feed(value)
    return " ".join(html.unescape(" ".join(parser.parts)).split())


def request_json(url: str, *, payload: dict | None = None) -> object:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method="POST" if data else "GET")
    for attempt in range(3):
        try:
            with urlopen(req, timeout=API_TIMEOUT) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (TimeoutError, URLError):
            if attempt == 2:
                raise
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("unreachable retry state")


def validate(board: dict) -> None:
    if board.get("ats") not in ALLOWED_ATS:
        raise ValueError("Unsupported ATS")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(board.get("slug", ""))):
        raise ValueError("Invalid board slug")
    if not board.get("company") or not board.get("markets") or not set(board["markets"]) <= set(REGIONS):
        raise ValueError("Missing company or unsupported markets")
    if board["ats"] == "workday":
        parsed = urlparse(board.get("career_url", ""))
        if parsed.scheme != "https" or not re.fullmatch(
            r"[a-z0-9-]+\.wd[0-9]+\.myworkdayjobs\.com", parsed.hostname or ""
        ):
            raise ValueError("Workday URL must be a verified *.myworkdayjobs.com career URL")
        pieces = [p for p in parsed.path.split("/") if p]
        site = pieces[1] if pieces and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", pieces[0]) and len(pieces) > 1 else pieces[0] if pieces else ""
        if not site or not re.fullmatch(r"[A-Za-z0-9_-]+", site):
            raise ValueError("Workday career URL must contain the exact board site")


def listing(board: dict) -> list[dict]:
    validate(board)
    ats, slug = board["ats"], quote(board["slug"])
    if ats == "greenhouse":
        data = request_json("https://boards-api.greenhouse.io/v1/boards/" + slug + "/jobs?content=true")
        rows = data["jobs"]
        return [{"id": str(j["id"]), "title": j.get("title", ""), "location": (j.get("location") or {}).get("name", ""),
                 "description": j.get("content", ""), "url": j.get("absolute_url", ""),
                 "posted_at": j.get("updated_at", ""), "employment": ""} for j in rows]
    if ats == "ashby":
        data = request_json("https://api.ashbyhq.com/posting-api/job-board/" + slug + "?includeCompensation=true")
        rows = data["jobs"]
        return [{"id": str(j.get("id") or j.get("jobId") or ""), "title": j.get("title", ""),
                 "location": j.get("location", ""), "description": j.get("descriptionPlain", ""),
                 "url": j.get("jobUrl", ""), "posted_at": j.get("publishedDate", ""),
                 "employment": j.get("employmentType", "")} for j in rows if j.get("isListed", True)]
    if ats == "lever":
        rows = request_json("https://api.lever.co/v0/postings/" + slug + "?mode=json")
        return [{"id": str(j.get("id", "")), "title": j.get("text", ""),
                 "location": (j.get("categories") or {}).get("location", ""),
                 "description": j.get("descriptionPlain") or j.get("description", ""),
                 "url": j.get("hostedUrl", ""), "posted_at": j.get("createdAt", ""),
                 "employment": (j.get("categories") or {}).get("commitment", "")} for j in rows]
    if ats == "smartrecruiters":
        base = "https://api.smartrecruiters.com/v1/companies/" + slug + "/postings"
        result: list[dict] = []
        offset = 0
        for _ in range(MAX_PAGES):
            data = request_json(base + "?limit=100&offset=" + str(offset))
            if not isinstance(data, dict) or "content" not in data or "totalFound" not in data:
                raise ValueError("SmartRecruiters unexpected listing schema")
            rows = data.get("content") or []
            for j in rows:
                loc = j.get("location") or {}
                result.append({"id": str(j.get("id", "")), "title": j.get("name", ""),
                    "location": ", ".join(str(loc.get(k) or "") for k in ("city", "region", "country") if loc.get(k)),
                    "description": "", "url": j.get("postingUrl") or "https://jobs.smartrecruiters.com/" + slug + "/" + str(j.get("id", "")),
                    "detail_url": j.get("ref") or "",
                    "posted_at": j.get("releasedDate", ""), "employment": j.get("typeOfEmployment", "")})
            offset += len(rows)
            total = int(data.get("totalFound", offset))
            if offset >= total:
                return result
            if not rows:
                raise RuntimeError("SmartRecruiters empty page before total")
        raise RuntimeError("SmartRecruiters page cap reached; do not treat as exhausted")
    # Workday CXS. Huge global boards (e.g. Micron) need smaller, exact
    # public searchText windows to avoid the ~2000-result API search cap.
    # A complete targeted search is NOT a complete employer-wide scan.
    parsed = urlparse(board["career_url"])
    host, tenant = parsed.hostname, parsed.hostname.split(".")[0]
    pieces = [p for p in parsed.path.split("/") if p]
    site = pieces[1] if pieces[0].count("-") == 1 and len(pieces) > 1 else pieces[0]
    api = "https://" + host + "/wday/cxs/" + tenant + "/" + site
    result = {}
    terms = board.get("search_terms") or [""]
    for term in terms:
        offset = 0
        for _ in range(MAX_PAGES):
            data = request_json(api + "/jobs", payload={
                "appliedFacets": {}, "limit": 20, "offset": offset, "searchText": term
            })
            if not isinstance(data, dict) or "jobPostings" not in data or "total" not in data:
                raise ValueError("Workday unexpected listing schema")
            rows = data.get("jobPostings") or []
            for j in rows:
                external = j.get("externalPath", "")
                url = ("https://" + host + "/" + site + external) if external.startswith("/") else ""
                item = {"id": str(j.get("jobId") or external or ""),
                    "title": j.get("title", ""),
                    "location": j.get("locationsText") or ", ".join(j.get("locations") or []),
                    "description": "", "url": url,
                    "detail_url": api + external if external.startswith("/") else "",
                    "posted_at": j.get("postedOn", ""), "employment": ""}
                if item["id"]:
                    result[item["id"]] = item
            offset += len(rows)
            total = int(data.get("total", offset))
            if offset >= total:
                break
            if not rows:
                raise RuntimeError("Workday empty page before total for " + repr(term))
            time.sleep(0.12)
        else:
            raise RuntimeError("Workday search window exceeded page cap: " + repr(term))
    return list(result.values())


def market_for(location: str, board: dict) -> str | None:
    hits = [m for m in board["markets"] if REGIONS[m].search(location)]
    return hits[0] if len(hits) == 1 else None


def normalize(board: dict, raw: dict, now: str, previous: dict | None = None) -> dict | None:
    title = plain(raw.get("title"))
    loc = plain(raw.get("location"))
    market = market_for(loc, board)
    if not market or not TECH_TITLES.search(title) or NON_ENGINEERING_TITLE.search(title):
        return None
    desc = plain(raw.get("description"))
    primary = bool(CORE_AI_ENGINEERING_TITLE.search(title) and AI_TERMS.search(title))
    jd_ai = bool(AI_TERMS.search(desc))
    if not (primary or jd_ai or (market == "MY" and board.get("my_swe") and TECH_TITLES.search(title))):
        return None
    url = str(raw.get("url") or "")
    if not url.startswith("https://") or not raw.get("id"):
        return None
    lane = "AI" if primary or jd_ai else "MY_SWE_SECONDARY"
    # Priority is for cheap downstream review ordering, never an APPLY/eligibility verdict.
    priority = "HIGH" if primary else "MEDIUM" if jd_ai else "LOW"
    key = board["slug"].lower() + "|" + board["ats"] + "|" + str(raw["id"])
    digest = hashlib.sha256(json.dumps([title, loc, desc[:8000], url, str(raw.get("employment") or "")],
                ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:20]
    return {
        "key": key, "company": board["company"], "ats": board["ats"], "market": market,
        "job_id": str(raw["id"]), "title": title, "location": loc, "url": url,
        "employment_type": str(raw.get("employment") or ""),
        "posted_at": str(raw.get("posted_at") or ""), "lane": lane,
        "triage_priority": priority,
        "description_excerpt": desc[:550],
        "description_text": desc[:12000],
        "description_truncated": len(desc) > 12000,
        "evidence": "full_jd" if desc and len(desc) <= 12000 else "partial_jd" if desc else "listing_only",
        "fingerprint": digest,
        "first_seen_at": (previous or {}).get("first_seen_at", now),
    }


def read_json(path: Path, default: dict) -> dict:
    return json.loads(path.read_text()) if path.is_file() else default


def write_if_changed(path: Path, data: dict) -> bool:
    value = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.is_file() and path.read_text() == value:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
    return True



@contextmanager
def board_deadline(seconds: int = MAX_BOARD_SECONDS):
    """Bound one employer board on the Ubuntu Actions runner, not whole ingestion.

    Preserve previous board data on deadline failures. The timer is local to the
    active Python main thread and is unavailable on some non-Unix platforms.
    """
    if not hasattr(signal, "SIGALRM"):
        yield
        return
    prior_handler = signal.getsignal(signal.SIGALRM)

    def expire(_signum, _frame):
        raise TimeoutError("ATS board exceeded " + str(seconds) + "s time budget")

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prior_handler)


def run(root: Path, config: list[dict], *, clock: str | None = None) -> dict:
    clock = clock or datetime.now(timezone.utc).isoformat(timespec="seconds")
    target = root / "feed" / "ats"
    old = read_json(target / "current.json", {"version": 1, "jobs": []})
    old_by = {j["key"]: j for j in old["jobs"]}
    new_by = dict(old_by)
    statuses = {}
    seen_board_ids = set()
    for board in config:
        board_id = str(board.get("ats", "unknown")) + ":" + str(board.get("slug", "unknown")).lower()
        if board_id in seen_board_ids:
            raise ValueError("Duplicate board " + board_id)
        seen_board_ids.add(board_id)
        try:
            validate(board)
            with board_deadline():
                rows = listing(board)  # only a complete enumeration promotes its snapshot
            candidates = {}
            for raw in rows:
                prior_key = board["slug"].lower() + "|" + board["ats"] + "|" + str(raw.get("id"))
                norm = normalize(board, raw, clock, old_by.get(prior_key))
                if norm is not None:
                    candidates[norm["key"]] = norm
            # Replace only the successfully enumerated board; a failed board NEVER creates fake closures.
            for key in list(new_by):
                if key.startswith(board["slug"].lower() + "|" + board["ats"] + "|"):
                    del new_by[key]
            new_by.update(candidates)
            statuses[board_id] = {"status": "COMPLETE", "rows_read": len(rows),
                                  "candidates": len(candidates),
                                  "scope": "targeted_keywords" if board.get("search_terms") else "whole_board"}
        except (ValueError, KeyError, TypeError, HTTPError, URLError, TimeoutError, RuntimeError) as exc:
            statuses[board_id] = {"status": "FAILED", "error": type(exc).__name__ + ": " + str(exc)[:180]}
    events = []
    baseline = not (target / "current.json").exists()
    for key, job in sorted(new_by.items()):
        old_job = old_by.get(key)
        if old_job is None:
            events.append({"kind": "BASELINE" if baseline else "NEW", **job})
        elif old_job["fingerprint"] != job["fingerprint"]:
            events.append({"kind": "CHANGED", **job})
    # Closures only derive from successful, full board snapshots.
    for key, job in sorted(old_by.items()):
        if key not in new_by:
            events.append({"kind": "REMOVED_FROM_FEED", "key": key, "company": job["company"],
                           "market": job["market"], "title": job["title"], "url": job["url"]})
    current = {"version": 1, "jobs": sorted(new_by.values(), key=lambda j: j["key"])}
    change = {"version": 1, "events": events}
    health = {"version": 1, "boards": statuses, "complete": all(x["status"] == "COMPLETE" for x in statuses.values())}
    write_if_changed(target / "current.json", current)
    write_if_changed(target / "changes.json", change)
    write_if_changed(target / "health.json", health)
    print(json.dumps({"boards": len(statuses), "status": health["complete"], "jobs": len(new_by),
                      "events": {k: sum(x["kind"] == k for x in events) for k in ("BASELINE", "NEW", "CHANGED", "REMOVED_FROM_FEED")},
                      "failures": [k for k, v in statuses.items() if v["status"] != "COMPLETE"]}))
    return {"health": health, "events": events, "jobs": len(new_by)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "ats_boards.json")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    result = run(args.root, config["boards"])
    # A partial source scan is visible as workflow failure, but preserves successful board deltas.
    return 0 if result["health"]["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
