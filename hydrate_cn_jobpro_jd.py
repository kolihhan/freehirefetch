#!/usr/bin/env python3
"""Source-only full JD hydration from public employer job-pro adapters.

This is NOT applicant ranking or application execution. The upstream adapter
must return a matching job ID, title, and official exact job URL. If either
JD section is absent, retain only an explicit failure; do not claim full JD.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html import unescape
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qs, urlsplit

PACKAGE = "@ha7ch/job-pro@1.2.1"
MAX_JD_CHARS = 12000
REFRESH_AFTER = timedelta(hours=24)
RETRY_AFTER = timedelta(hours=12)
RETENTION = timedelta(days=7)
# Intentionally restricted to official employer channels documented in
# the private CN canonical-URL transport. Never treat Liepin as first-party.
SUPPORTED = ("bytedance", "agibot", "tencent", "alibaba", "nio", "zerooneai")
FEISHU_HOSTS = {"nio": "nio.jobs.feishu.cn",
                "zerooneai": "01ai.jobs.feishu.cn",
                "agibot": "agirobot.jobs.feishu.cn"}
# Titles such as "embedded software engineer" are not NLP/Agent vacancies.
# Require explicit AI/NLP/agent/retrieval relevance before expensive JD hydration.
SIGNALS = re.compile(
    r"AI|LLM|NLP|RAG|Agent|人工智能|大模型|机器学习|生成式|"
    r"智能体|模型评测|算法评测|语义检索|知识图谱|自然语言|深度学习", re.I)


def checked_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalized_title(title: str) -> str:
    return "".join(re.findall(r"[\w\u4e00-\u9fff]+", str(title or "").casefold()))


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


def substantive_ai_priority(title: str) -> int:
    """Source-only JD fetch order. Never an applicant eligibility decision."""
    score = sum(4 for pattern in (
        r"Agent|智能体",
        r"大模型|LLM|RAG",
        r"后端|研发|工程师|Research|研究",
        r"AI应用|AI全栈|检索|评测|推理",
    ) if re.search(pattern, title, re.I))
    score -= sum(6 for pattern in (
        r"数据运营|产品经理|销售|客户成功|市场",
        r"实习|Intern",
    ) if re.search(pattern, title, re.I))
    return score


def choose_candidates(documents: list[dict], *, limit: int = 10, per_company: int = 6,
                      history: dict | None = None, now: str | None = None) -> list[dict]:
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
    # Never let yesterday's first six titles consume every subsequent budget.
    history = history or {}
    clock = parse_time(now or checked_at())
    tiers = ({}, {})
    for company, entries in groups.items():
        for item in entries:
            old = matching_record(history, item)
            if not old:
                tier = 0
            else:
                last = parse_time(old.get("attempted_at"))
                delay = RETRY_AFTER if old.get("status") != "OK" else REFRESH_AFTER
                if clock - last < delay:
                    continue
                tier = 1
            tiers[tier].setdefault(company, []).append(item)
    rows = []
    counts = defaultdict(int)
    for tier in tiers:
        for entries in tier.values():
            entries.sort(key=lambda item: (
                parse_time(matching_record(history, item).get("attempted_at")),
                -substantive_ai_priority(item["title"]), item["post_id"]))
        for index in range(max((len(x) for x in tier.values()), default=0)):
            for company in SUPPORTED:
                items = tier.get(company, [])
                if index < len(items) and counts[company] < per_company:
                    rows.append(items[index])
                    counts[company] += 1
                    if len(rows) == limit:
                        return rows
    return rows


def parse_time(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else datetime.min.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def identity(item):
    return item["company_key"] + "|" + str(item.get("post_id") or item.get("job_id"))


def matching_record(history, item):
    old = history.get(identity(item), {})
    if (old.get("url") == item["url"]
            and normalized_title(old.get("title")) == normalized_title(item["title"])):
        return old
    return {}


def prior_records(previous, legacy):
    records = previous.get("records", {}) if isinstance(previous, dict) else {}
    if records:
        return records
    # Bootstrap existing verified public evidence without relabeling its date.
    return {identity(row): {"title": row["title"], "url": row["url"],
            "attempted_at": row["checked_at"], "status": "OK", "evidence": row}
            for row in legacy.get("jobs", []) if row.get("full_jd_complete")
            and row.get("company_key") and row.get("job_id") and row.get("checked_at")}


def clean_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = re.sub(r"<(?:br|/p|/li|/div)\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]{1,150}>", " ", text)
    return re.sub(r"[ \t\r]+", " ", unescape(text)).strip()


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
    full = "岗位职责 / Responsibilities\n" + description + "\n任职要求 / Requirements\n" + requirements
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


def hydrate(documents: list[dict], *, detail_fetch=cli_detail, limit: int = 10,
            history: dict | None = None, now: str | None = None) -> dict:
    when = now or checked_at()
    clock = parse_time(when)
    history = {key: record for key, record in (history or {}).items()
               if clock - parse_time(record.get("attempted_at")) < RETENTION}
    # Enumerate every exact supported current identity, even when its JD is cached.
    observed = choose_candidates(documents, limit=100000, per_company=100000, now=when)
    candidates = choose_candidates(documents, limit=limit, history=history, now=when)
    output = {"version": 1, "source": "jobpro-public-employer-detail",
              "checked_at": when, "attempted": 0, "failed": 0,
              "jobs": [], "failures": [],
              "warning": "Official source JDs are not eligibility, current-route or application proof."}
    def fetch_one(item: dict) -> dict | None:
        try:
            detail = detail_fetch(item["company_key"], item["post_id"])
            return detail_evidence(item, detail, when)
        except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired):
            return None

    # Detail lookups are independent HTTP/CLI requests. A bounded pool cuts
    # end-to-end latency without flooding employer public endpoints.
    # executor.map preserves source priority order in the published artifact.
    with ThreadPoolExecutor(max_workers=3) as pool:
        evidence_rows = list(pool.map(fetch_one, candidates))
    for item, evidence in zip(candidates, evidence_rows):
        output["attempted"] += 1
        old = matching_record(history, item)
        history[identity(item)] = {"title": item["title"], "url": item["url"],
                                   "attempted_at": when,
                                   "status": "OK" if evidence else "FAILED",
                                   "evidence": evidence or old.get("evidence")}
        if not evidence:
            output["failed"] += 1
            output["failures"].append({
                "company_key": item["company_key"], "job_id": item["post_id"],
                "reason": "OFFICIAL_DETAIL_NOT_VERIFIED",
            })
    # Only publish fresh, matching, currently observed successful evidence.
    # Failed refreshes or disappeared roles remain in state, not in the live JD list.
    for item in observed:
        old = matching_record(history, item)
        evidence = old.get("evidence")
        if (old.get("status") == "OK" and evidence
                and clock - parse_time(evidence.get("checked_at")) < REFRESH_AFTER):
            output["jobs"].append(evidence)
    output["newly_verified"] = output["attempted"] - output["failed"]
    output["cached_verified"] = len(output["jobs"]) - output["newly_verified"]
    output["observed_distinct"] = len(observed)
    output["not_currently_verified"] = len(observed) - len(output["jobs"])
    output["coverage"] = "PARTIAL" if output["not_currently_verified"] else "OBSERVED_BATCH_VERIFIED"
    output["state"] = {"version": 1, "records": history}
    return output


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source-dir", type=Path, default=Path("feed/cn-native"))
    p.add_argument("--output", type=Path, default=Path("feed/cn-native/jobpro-jd.json"))
    p.add_argument("--limit", type=int, default=10)
    args = p.parse_args()
    inputs = []
    for key in ("ai", "backend", "swe", "agent", "llm"):
        path = args.source_dir / ("jobpro-" + key + ".json")
        try:
            source = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(source, dict) and source.get("ok") is True:
                inputs.append(source)
        except (OSError, ValueError):
            pass
    if not inputs:
        raise SystemExit("No valid public job-pro employer source batch; retaining previous JD evidence")
    state_path = args.output.with_name(args.output.stem + "-state.json")
    def read_previous(path):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}
    history = prior_records(read_previous(state_path), read_previous(args.output))
    result = hydrate(inputs, limit=args.limit, history=history)
    state = result.pop("state")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("attempted", "failed", "checked_at", "newly_verified", "cached_verified", "observed_distinct", "coverage")},
                     ensure_ascii=False))
    print("CN public job-pro official JDs:", len(result["jobs"]),
          "source-only, no applicant decisions")


if __name__ == "__main__":
    main()
