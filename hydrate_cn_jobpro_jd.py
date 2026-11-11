#!/usr/bin/env python3
"""Source-only full JD hydration from public employer job-pro adapters.

This is NOT applicant ranking or application execution. The upstream adapter
must return a matching job ID, title, and official exact job URL. If either
JD section is absent, retain only an explicit failure; do not claim full JD.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from html import unescape
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qs, urlsplit

PACKAGE = "@ha7ch/job-pro@1.2.1"
MAX_JD_CHARS = 12000
# Intentionally restricted to official employer channels documented in
# the private CN canonical-URL transport. Never treat Liepin as first-party.
SUPPORTED = ("tencent", "bytedance", "alibaba", "nio", "zerooneai")
FEISHU_HOSTS = {"nio": "nio.jobs.feishu.cn",
                "zerooneai": "01ai.jobs.feishu.cn"}
SIGNALS = re.compile(
    r"AI|ML|LLM|NLP|RAG|Agent|人工智能|大模型|机器学习|生成式|"
    r"智能体|研究|算法|模型|检索|后端|软件工程|AI应用", re.I)


def checked_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalized_title(title: str) -> str:
    return "".join(re.findall(r"[\\w\\u4e00-\\u9fff]+", str(title or "").casefold()))


def official_url(company: str, position: dict) -> str | None:
    """Only exact allowlisted employer job URLs with matching advertised IDs."""
    if company not in SUPPORTED:
        return None
    uid = str(position.get("post_id") or "")
    if not re.fullmatch(r"[0-9]{10,20}", uid):
        return None
    url = position.get("apply_url")
    if not isinstance(url, str):
        return None
    try:
        p = urlsplit(url)
    except ValueError:
        return None
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
        return None
    host = p.hostname.lower()
    path = p.path.rstrip("/")
    if company == "tencent" and host == "join.qq.com" and path == "/post_detail.html":
        ids = parse_qs(p.query).get("postid", [])
        if len(ids) == 1 and ids[0] == uid:
            return "https://join.qq.com/post_detail.html?postid=" + uid
    if company == "bytedance" and host == "jobs.bytedance.com":
        if re.fullmatch(r"/(?:campus|experienced)/position/" + uid + r"/detail", path):
            return "https://jobs.bytedance.com" + path
    if company == "alibaba" and host == "campus-talent.alibaba.com":
        if path == "/campus/position/" + uid:
            return "https://campus-talent.alibaba.com" + path
    if host == FEISHU_HOSTS.get(company):
        if re.fullmatch(r"/[A-Za-z0-9_-]+/position/" + uid + r"/detail", path):
            return "https://" + host + path
    return None


def choose_candidates(documents: list[dict], *, limit: int = 10, per_company: int = 3) -> list[dict]:
    if limit < 1 or per_company < 1:
        raise ValueError("positive limits required")
    seen: set[tuple[str, str]] = set()
    groups: dict[str, list[dict]] = defaultdict(list)
    for doc in documents:
        for group in doc.get("results", []):
            if not isinstance(group, dict):
                continue
            company = str(group.get("company") or "")
            for pos in group.get("positions") or []:
                if not isinstance(pos, dict):
                    continue
                title = str(pos.get("title") or "")
                url = official_url(company, pos)
                uid = str(pos.get("post_id") or "")
                if not url or not SIGNALS.search(title) or (company, uid) in seen:
                    continue
                seen.add((company, uid))
                groups[company].append({
                    "company_key": company, "post_id": uid, "title": title,
                    "url": url, "work_cities": pos.get("work_cities") or "",
                })
    # Round-robin: avoids single-company dominance and gives both AI and
    # substantive engineering sources a fair chance under bounded CI budget.
    rows: list[dict] = []
    for index in range(per_company):
        for company in SUPPORTED:
            items = groups.get(company, [])
            if index < len(items):
                rows.append(items[index])
                if len(rows) == limit:
                    return rows
    return rows


def clean_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = re.sub(r"<(?:br|/p|/li|/div)\\s*/?>", "\\n", text, flags=re.I)
    text = re.sub(r"<[^>]{1,150}>", " ", text)
    return re.sub(r"[ \\t\\r]+", " ", unescape(text)).strip()


def detail_evidence(item: dict, detail: dict, when: str) -> dict | None:
    if not isinstance(detail, dict) or detail.get("ok") is not True:
        return None
    company = item.get("company_key")
    uid = item.get("post_id")
    url = item.get("url")
    if str(detail.get("post_id") or "") != uid:
        return None
    if normalized_title(detail.get("title")) != normalized_title(item.get("title")):
        return None
    if official_url(company, {"post_id": uid, "apply_url": detail.get("apply_url")}) != url:
        return None
    description = clean_text(detail.get("description"))
    requirements = clean_text(detail.get("requirements"))
    if not 70 <= len(description) <= MAX_JD_CHARS or not 45 <= len(requirements) <= MAX_JD_CHARS:
        return None
    full = "岗位职责 / Responsibilities\\n" + description + "\\n任职要求 / Requirements\\n" + requirements
    if not 230 <= len(full) <= MAX_JD_CHARS:
        return None
    return {
        "company_key": company, "job_id": uid,
        "title": item["title"], "url": url, "checked_at": when,
        "description_text": description, "requirements_text": requirements,
        "full_jd_text": full, "full_jd_complete": True,
        "description_truncated": False,
        "source": "jobpro-public-employer-detail",
    }


def cli_detail(company: str, uid: str) -> dict:
    command = ["npx", "-y", PACKAGE, company, "detail", uid, "--compact"]
    completed = subprocess.run(command, capture_output=True, text=True,
                               timeout=18, check=False)
    if completed.returncode != 0 or len(completed.stdout) > 120000:
        return {"ok": False, "message": "cli_failed"}
    try:
        return json.loads(completed.stdout)
    except (ValueError, TypeError):
        return {"ok": False, "message": "non_json_result"}


def hydrate(documents: list[dict], *, detail_fetch=cli_detail, limit: int = 10) -> dict:
    candidates = choose_candidates(documents, limit=limit)
    output = {"version": 1, "source": "jobpro-public-employer-detail",
              "checked_at": checked_at(), "attempted": 0, "failed": 0,
              "jobs": [], "failures": [],
              "warning": "Official source JDs are not eligibility, current-route or application proof."}
    for item in candidates:
        output["attempted"] += 1
        try:
            detail = detail_fetch(item["company_key"], item["post_id"])
            evidence = detail_evidence(item, detail, checked_at())
        except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired):
            evidence = None
        if evidence:
            output["jobs"].append(evidence)
        else:
            output["failed"] += 1
            output["failures"].append({
                "company_key": item["company_key"], "job_id": item["post_id"],
                "reason": "OFFICIAL_DETAIL_NOT_VERIFIED",
            })
    return output


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source-dir", type=Path, default=Path("feed/cn-native"))
    p.add_argument("--output", type=Path, default=Path("feed/cn-native/jobpro-jd.json"))
    p.add_argument("--limit", type=int, default=10)
    args = p.parse_args()
    inputs = []
    for key in ("ai", "backend", "swe"):
        path = args.source_dir / ("jobpro-" + key + ".json")
        try:
            source = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(source, dict) and source.get("ok") is True:
                inputs.append(source)
        except (OSError, ValueError):
            pass
    if not inputs:
        raise SystemExit("No valid public job-pro employer source batch; retaining previous JD evidence")
    result = hydrate(inputs, limit=args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\\n",
                           encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("attempted", "failed", "checked_at")},
                     ensure_ascii=False))
    print("CN public job-pro official JDs:", len(result["jobs"]),
          "source-only, no applicant decisions")


if __name__ == "__main__":
    main()
