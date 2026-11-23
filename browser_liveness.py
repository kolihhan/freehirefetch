#!/usr/bin/env python3
"""Public-only Playwright check of employer-authored job pages (no applications).

Input is public official role URLs (curated + rotating public ATS feed). All
personal data, Gmail dedupe and application decisions live in job-resources.
An Apply button is an OPEN_SIGNAL, never verified application eligibility.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "feed/browser-liveness/current.json"
APPLY_RE = re.compile(r"(?i)\bapply(?: now| for (?:this|the) (?:job|position))?\b|立即申请|申请职位|立即投递|投递简历|立即应聘|申请该职位")
CLOSED_RE = re.compile(
    r"(?i)\b(?:this (?:job|position|vacancy) (?:is |has been )?(?:closed|filled)|"
    r"(?:job|position) (?:is )?no longer (?:available|accepting applications)|"
    r"applications (?:are )?closed|posting has expired)\b|职位已(?:下线|过期|关闭|结束)|招聘已结束|停止招聘"
)
BLOCKED_RE = re.compile(
    r"(?i)service unavailable|access denied|checking your browser|"
    r"verify you are human|captcha|security check|request blocked|暂时无法访问"
)
TOPIC_RE = re.compile(r"(?i)\b(?:AI|LLM|NLP|RAG|GenAI|Agent|ML Engineer|"
                      r"Machine Learning|Retrieval|Research Engineer|Applied Scientist|"
                      r"Generative AI|Model Evaluation)\b|大模型|智能体|自然语言处理|算法工程师")
SENIOR_RE = re.compile(r"(?i)\b(?:principal|staff|director|head of|senior manager)\b|首席科学家|架构师")
ALLOWED_EXACT = {
    "jobs.ashbyhq.com", "job-boards.greenhouse.io",
    "job-boards.eu.greenhouse.io", "boards.greenhouse.io",
    "jobs.lever.co", "jobs.eu.lever.co", "jobs.smartrecruiters.com",
    "careers.micron.com",
}
GENERICS = {"careers", "jobs", "job openings", "join us", "open positions",
            "career opportunities", "工作机会", "招聘职位", "职位列表"}


def safe_public_role(url: str) -> bool:
    if not isinstance(url, str) or len(url) > 1300:
        return False
    try:
        p = urlsplit(url.strip())
        if (p.scheme != "https" or p.username or p.password or
                p.port not in (None, 443) or p.fragment):
            return False
    except ValueError:
        return False
    host = (p.hostname or "").lower()
    if (host in ALLOWED_EXACT or
            re.fullmatch(r"[a-z0-9-]+\.jobs\.feishu\.cn", host) or
            re.fullmatch(r"[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com", host)):
        return bool(p.path.strip("/")) and len(p.path) > 15
    return False


def select_targets(config: dict, feed: dict, *, rotation: int = 1,
                   max_feed: int = 5) -> list[dict]:
    """Curated public examples plus a deterministic, rotating feed slice."""
    if config.get("version") != 1 or not isinstance(config.get("targets"), list):
        raise ValueError("Invalid browser target configuration")
    if max_feed < 0 or rotation < 1:
        raise ValueError("Invalid rotation/max_feed")
    chosen, seen = [], set()
    for source in config["targets"][:12]:
        if not isinstance(source, dict):
            continue
        url = source.get("url")
        if (not safe_public_role(url) or url in seen or
                source.get("market") not in ("SG", "CN")):
            continue
        seen.add(url)
        chosen.append({"url": url, "market": source["market"],
                       "source": "curated_public_role"})
    candidates = []
    for job in feed.get("jobs", [])[:3000]:
        if not isinstance(job, dict):
            continue
        url, title, market = job.get("url"), job.get("title", ""), job.get("market")
        if (market not in ("SG", "CN") or not safe_public_role(url) or
                not TOPIC_RE.search(str(title)) or SENIOR_RE.search(str(title)) or
                url in seen):
            continue
        candidates.append({"url": url, "market": market,
                           "source": "ats_public_feed",
                           "company": str(job.get("company") or "")[:100]})
    # Pick one role per employer before rotating; no user profile or application state.
    candidates.sort(key=lambda x: (x["market"] != "SG", x["company"].lower(), x["url"]))
    by_company, diverse = set(), []
    for job in candidates:
        ident = (job["market"], job["company"].casefold())
        if ident not in by_company:
            diverse.append(job)
            by_company.add(ident)
    if diverse and max_feed:
        index = ((rotation - 1) * max_feed) % len(diverse)
        for i in range(min(max_feed, len(diverse))):
            job = diverse[(index + i) % len(diverse)]
            if job["url"] not in seen:
                chosen.append(job)
                seen.add(job["url"])
    return chosen


def assess_page(*, requested_url: str, final_url: str, http_status: int | None,
                heading: str, body: str, apply_controls: int) -> tuple[str, str]:
    """Fail closed. Only an exact role page with a visible Apply is an open signal."""
    if http_status in (401, 403, 429):
        return "UNKNOWN_BLOCKED", "HTTP access restriction"
    if http_status is None or http_status >= 400:
        return "UNKNOWN_HTTP", f"HTTP {http_status}"
    if not safe_public_role(final_url):
        return "UNKNOWN_REDIRECT", "Redirected to unapproved or generic URL"
    req, final = urlsplit(requested_url), urlsplit(final_url)
    # Workday may add locale/remove slug, but the final path must retain the
    # original exact requisition ID whenever one is visible in the URL.
    tokens = re.findall(r"(?i)(?:R\d{7,10}|JR\d{5,10}|\d{15,20}|"
                        r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})", req.path)
    if tokens and not any(token.lower() in final.path.lower() for token in tokens):
        return "UNKNOWN_REDIRECT", "Exact requisition ID lost after navigation"
    text = body[:10000]
    if BLOCKED_RE.search(text[:4000]):
        return "UNKNOWN_BLOCKED", "Browser challenge or unavailable service"
    h = heading.strip()
    role_heading = len(h) >= 8 and h.casefold() not in GENERICS
    if CLOSED_RE.search(text[:6000]) and final.path.strip("/"):
        return "CLOSED_EXPLICIT", "Official role page displays an explicit closed/expired message"
    if not role_heading:
        return "UNKNOWN_NO_ROLE_HEADING", "No specific job heading; generic page is not proof of vacancy"
    if apply_controls:
        return "OPEN_SIGNAL_FORM_UNTESTED", "Exact role heading plus visible Apply control (not submitted)"
    return "UNKNOWN_NO_APPLY", "Role rendered but no visible current Apply control"


def probe(browser, target: dict, *, timeout_ms: int = 16000) -> dict:
    """Open only public pages and inspect controls; never click or send a form."""
    url = target["url"]
    result = {**target, "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "status": "UNKNOWN_ERROR", "http_status": None,
              "apply_control_visible": False, "final_form_tested": False}
    page = browser.new_page()
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        result["http_status"] = response.status if response else None
        # Let client-rendered Workday/Feishu/ATS pages hydrate, bounded.
        page.wait_for_timeout(1800)
        final_url = page.url
        heading = (page.locator("h1").first.inner_text(timeout=2000)
                   if page.locator("h1").count() else "")
        text = page.locator("body").inner_text(timeout=2500)
        controls = page.get_by_role("button", name=APPLY_RE).count()
        controls += page.get_by_role("link", name=APPLY_RE).count()
        result.update({"final_url": final_url, "role_heading": heading[:180],
                       "apply_control_visible": controls > 0})
        status, reason = assess_page(
            requested_url=url, final_url=final_url,
            http_status=result["http_status"], heading=heading,
            body=text, apply_controls=controls)
        result.update({"status": status, "reason": reason})
    except Exception as exc:
        result.update({"status": "UNKNOWN_ERROR",
                       "reason": type(exc).__name__ + ": " + str(exc).splitlines()[0][:150]})
    finally:
        page.close()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "browser_liveness_targets.json")
    parser.add_argument("--feed", type=Path, default=ROOT / "feed/ats/current.json")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--rotation", type=int, default=1)
    parser.add_argument("--max-feed", type=int, default=5)
    parser.add_argument("--timeout-ms", type=int, default=16000)
    args = parser.parse_args(argv)
    if not 3000 <= args.timeout_ms <= 45000:
        parser.error("timeout must be 3000..45000 ms")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    feed = json.loads(args.feed.read_text(encoding="utf-8"))
    targets = select_targets(config, feed, rotation=args.rotation, max_feed=args.max_feed)
    from playwright.sync_api import sync_playwright  # only runtime needs Chromium
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            results = [probe(browser, target, timeout_ms=args.timeout_ms) for target in targets[:16]]
        finally:
            browser.close()
    summary = {}
    for row in results:
        summary[row["status"]] = summary.get(row["status"], 0) + 1
    artifact = {
        "version": 1, "source": "freehirefetch-public-playwright-rendered",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "HEADLESS_CHROMIUM_READ_ONLY_ROLE_PAGE",
        "limitations": ("Open Apply control is not proof of accepting completed applications; "
                        "never implies pay, indefinite term or sponsorship. "
                        "Blocked/404/redirect/no control are UNKNOWN, not automatically expired. "
                        "No links are clicked, no form submitted and no candidate data."),
        "rotation": args.rotation, "summary": summary, "roles": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({"targets": len(results), "status": summary, "output": str(args.output)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
