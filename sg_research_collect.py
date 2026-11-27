#!/usr/bin/env python3
"""Bounded public SG university/research portal collector (NOT an APPLY feed).

Tests SuccessFactors employer-public HTML sources without authentication or
browser workarounds. A source is undercovered unless real role links and
documented pagination/exhaustion are observed. Publishes public source evidence only. Source content is untrusted.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

SOURCES = (
    ("SUTD Research", "https://careers.sutd.edu.sg/go/Researchers-Jobs/653644/"),
    ("NUS Research", "https://careers.nus.edu.sg/NUS/go/Research-%26-Other-Teaching-Positions-All/733244/"),
    ("A*STAR Agent", "https://careers.a-star.edu.sg/search/?q=agent"),
    ("A*STAR LLM", "https://careers.a-star.edu.sg/search/?q=LLM"),
)
HOSTS = frozenset(("careers.sutd.edu.sg", "careers.nus.edu.sg", "careers.a-star.edu.sg"))
ROLE = re.compile(r"\b(?:research (?:assistant|associate|engineer|officer|scientist|fellow)|"
                  r"ai engineer|applied scientist|nlp engineer|machine learning engineer)\b", re.I)
TECH = re.compile(r"\b(?:LLM|RAG|NLP|agentic|agent(?:s)?|natural language processing|"
                  r"retrieval|machine learning|generative AI|knowledge graph|AI systems)\b", re.I)
REQ = re.compile(r"\b(?:Job Req ID|Requisition ID)\s*:\s*(\d{2,10})\b", re.I)
MAX_HTML_BYTES = 2_000_000
MAX_DETAILS_PER_SOURCE = 12


class JobHTML(HTMLParser):
    """Capture visible link text + href, rather than counting arbitrary URLs."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.text = []
        self._href = None
        self._label = []
        self._hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._hidden += 1
        if tag == "a" and not self._hidden:
            self._href = dict(attrs).get("href")
            self._label = []

    def handle_data(self, data):
        if self._hidden:
            return
        self.text.append(data)
        if self._href is not None:
            self._label.append(data)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._hidden = max(0, self._hidden - 1)
        if tag == "a" and self._href is not None and not self._hidden:
            self.links.append((self._href, " ".join(self._label).strip()))
            self._href = None
            self._label = []


def text_of(html):
    parser = JobHTML()
    parser.feed(html)
    return re.sub(r"\s+", " ", " ".join(parser.text)).strip()


def fetch_html(url):
    if urlparse(url).scheme != "https" or urlparse(url).hostname not in HOSTS:
        raise ValueError("non-official portal host")
    request = Request(url, headers={"User-Agent": "FreeHireResearchCollector/1.0",
                                    "Accept": "text/html"})
    with urlopen(request, timeout=20) as response:
        if urlparse(response.geturl()).hostname not in HOSTS:
            raise ValueError("source redirected away from official research portal")
        if response.status != 200:
            raise ValueError("HTTP " + str(response.status))
        data = response.read(MAX_HTML_BYTES + 1)
    if len(data) > MAX_HTML_BYTES:
        raise ValueError("source HTML exceeded bounded read")
    return data.decode("utf-8", errors="replace")


def candidates(html, base):
    p = JobHTML()
    p.feed(html)
    urls = {}
    for href, label in p.links:
        url = urljoin(base, href)
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.hostname != urlparse(base).hostname
                or "/job/" not in parsed.path or not re.search(r"/\d+(?:-[A-Za-z_]+)?/?$", parsed.path)
                or not ROLE.search(label)):
            continue
        urls[url.split("?", 1)[0]] = label[:180]
    return [{"url": u, "title": t} for u, t in urls.items()]


def inspect_detail(role, source_host, fetch=fetch_html):
    html = fetch(role["url"])
    data = text_of(html)
    if urlparse(role["url"]).hostname != source_host:
        raise ValueError("job host not same as source")
    if role["title"].casefold() not in data.casefold():
        raise ValueError("role title not visible in detail")
    req = REQ.search(data)
    if not req:
        raise ValueError("exact employer requisition not printed in detail")
    if not re.search(r"Apply now", data, re.I):
        raise ValueError("no employer application control in detail")
    return {"title": role["title"], "url": role["url"],
            "requisition": req.group(1), "job_page_verified": True,
            "apply_control_seen": True, "page_text_chars": len(data),
            "technical_signals": sorted(set(m.group(0).lower() for m in TECH.finditer(data))),
            "page_text_excerpt": data[:16000], "page_text_complete": len(data) <= 16000}


def probe(source, fetch=fetch_html, pause=False):
    name, url = source
    result = {"source": name, "url": url, "status": "SOURCE_ERROR",
              "listing_identified": 0, "detail_verified": 0,
              "jobs": [], "errors": [], "pagination_exhausted": False}
    try:
        html = fetch(url)
        rows = candidates(html, url)
        result["listing_identified"] = len(rows)
        text = text_of(html)
        result["pagination_exhausted"] = bool(re.search(
            r"Page\s+1\s+of\s+1\b", text, re.I))
        if not rows:
            result["status"] = "UNDERCOVERED"
            result["errors"].append("No job-detail links in actual HTML; JS shell is not job coverage")
            return result
        for role in rows[:MAX_DETAILS_PER_SOURCE]:
            try:
                result["jobs"].append(inspect_detail(role, urlparse(url).hostname, fetch))
            except Exception as exc:
                result["errors"].append(role["url"] + ": " + type(exc).__name__ + ":" + str(exc)[:140])
            if pause:
                time.sleep(0.3)
        result["detail_verified"] = len(result["jobs"])
        result["status"] = ("VERIFIED_BOUNDED_SOURCE_END" if
             result["pagination_exhausted"] and len(rows) <= MAX_DETAILS_PER_SOURCE and not result["errors"]
             else "PARTIAL_COVERAGE")
    except Exception as exc:
        result["errors"].append(type(exc).__name__ + ":" + str(exc)[:180])
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    sources = [probe(src, pause=True) for src in SOURCES]
    output = {"observed_at": datetime.now(timezone.utc).isoformat(),
              "mode": "READ_ONLY_SOURCE_PROBE_NOT_APPLY_OR_MARKET_COVERAGE",
              "sources": sources}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for x in sources:
        print(json.dumps({k: v for k, v in x.items() if k != "jobs"}, ensure_ascii=False))
    if not any(x["detail_verified"] for x in sources):
        print("NO_VERIFIED_SOURCE_JOBS: all sources are unproven; no job coverage claimed.")


if __name__ == "__main__":
    main()
