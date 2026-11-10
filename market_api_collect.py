#!/usr/bin/env python3
"""Batch public jobs-API discovery upstream. No private applicant data.

FreeHire and AI Dev Jobs source signals are never eligibility / APPLY decisions.
Consumer-owned GitHub Issues, Gmail dedupe and candidate value remain downstream.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError

# Source-only exact-role normalization. No applicant / job-resources dependency.
from urllib.parse import parse_qs

def canonical(url, market):
    p = urlsplit(str(url or "").strip())
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
        return None
    host = p.hostname.lower()
    path = p.path.rstrip("/")
    if host in ("sg.jobstreet.com", "my.jobstreet.com"):
        match = re.fullmatch(r"/job/(\d{6,12})", path)
        if match and host.startswith(market.lower()+".") and market in ("SG","MY"):
            return f"https://{host}/job/{match.group(1)}"
    if host in ("sg.linkedin.com","my.linkedin.com","www.linkedin.com","linkedin.com"):
        match = re.search(r"/jobs/view/(?:[^/?]*-)?(\d{7,13})$", path)
        if match and market in ("SG","MY"):
            return "https://www.linkedin.com/jobs/view/"+match.group(1)
    if host in ("sg.indeed.com","malaysia.indeed.com","my.indeed.com") and path == "/viewjob":
        jk = parse_qs(p.query).get("jk", [""])[0]
        if re.fullmatch(r"[a-zA-Z0-9]{12,24}",jk) and (
            market=="SG" and host=="sg.indeed.com" or
            market=="MY" and host in ("my.indeed.com","malaysia.indeed.com")):
            return "https://"+("sg.indeed.com" if market=="SG" else "malaysia.indeed.com")+"/viewjob?jk="+jk
    if market == "MY" and host == "my.hiredly.com" and re.fullmatch(r"/jobs/(?:[^/]+/)?[\w-]{7,}",path):
        return "https://my.hiredly.com"+path
    if market == "CN" and host in ("www.liepin.com","liepin.com"):
        match = re.fullmatch(r"/job/(\d{5,16})\.shtml",path)
        if match:return "https://www.liepin.com/job/"+match.group(1)+".shtml"
    if host == "jobs.ashbyhq.com":
        match = re.fullmatch(r"/([A-Za-z0-9_.-]+)/([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})",path)
        if match:
            owner_markets={"gen-digital":{"MY"},"abound":{"CN"}}
            if market not in owner_markets.get(match.group(1).lower(),{"SG","MY","CN"}):return None
            return "https://jobs.ashbyhq.com/"+match.group(1)+"/"+match.group(2).lower()
    if host in ("job-boards.greenhouse.io","job-boards.eu.greenhouse.io"):
        match=re.fullmatch(r"/([A-Za-z0-9_-]+)/jobs/(\d{5,12})",path)
        if match:return f"https://{host}/{match.group(1)}/jobs/{match.group(2)}"
    if host=="jobs.lever.co":
        match=re.fullmatch(r"/([A-Za-z0-9_.-]+)/([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})",path)
        if match:return "https://jobs.lever.co/"+match.group(1)+"/"+match.group(2).lower()
    if host=="jobs.smartrecruiters.com":
        match=re.fullmatch(r"/([A-Za-z0-9_-]+)/([A-Za-z0-9-]{6,90})",path)
        if match:return "https://jobs.smartrecruiters.com/"+match.group(1)+"/"+match.group(2)
    if re.fullmatch(r"[a-z0-9-]+\.wd[0-9]+\.myworkdayjobs\.com",host):
        if host=="ntu.wd3.myworkdayjobs.com" and market!="SG":return None
        match=re.fullmatch(r"/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)/job/([A-Za-z0-9_-]+)/([^/]+_[A-Za-z]{1,5}\d{4,12}(?:-\d+)?)",path)
        if match:return "https://"+host+"/"+match.group(1)+"/job/"+match.group(2)+"/"+match.group(3)
    return None

MARKETS = {"SG": "Singapore", "MY": "Malaysia", "CN": "China"}
QUERIES = ("AI Engineer", "LLM", "Research Engineer")
CN_EXTRA = ("大模型", "算法工程师")
TITLE = re.compile(
    r"\b(?:AI|ML|LLM|NLP|RAG|agentic|agents?|machine learning|"
    r"applied scientist|research engineer|research assistant|"
    r"research associate|data scientist|retrieval|ranking)\b"
    r"|人工智能|大模型|智能体|算法|机器学习|检索|研究工程师", re.I)
LOCATIONS = {
    "SG": re.compile(r"\bsingapore\b|新加坡", re.I),
    "MY": re.compile(r"\bmalaysia\b|kuala lumpur|petaling jaya|selangor|"
                     r"penang|johor|cyberjaya|putrajaya|bayan lepas|槟城|马来西亚", re.I),
    "CN": re.compile(r"\bchina\b|beijing|shanghai|shenzhen|guangzhou|hangzhou|"
                     r"chengdu|wuhan|nanjing|suzhou|tianjin|中国|北京|上海|深圳|广州|杭州|成都|南京|武汉", re.I),
}
MAX_BYTES = 3_000_000
LIMIT = 50
# Unverified third-party source text is useful for review, NEVER a verified JD.
MAX_API_DESCRIPTION_CHARS = 12000


def get_json(url):
    req = Request(url, headers={"Accept": "application/json",
                                 "User-Agent": "FreeHireFetchMarketAPI/1.0"})
    with urlopen(req, timeout=18) as response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("API response exceeds size bound")
    return json.loads(raw)


def canonical_apply(url, market):
    """Strip an exact Ashby application suffix, not arbitrary URL paths."""
    p = urlsplit(str(url or "").strip())
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        return None
    if p.hostname == "jobs.ashbyhq.com" and p.path.endswith("/application"):
        path = p.path[:-len("/application")]
        p = p._replace(path=path, query="", fragment="")
    return canonical(urlunsplit(p), market)


def platform_family(url):
    """Recognize the platform of the exact linked posting, never scan ownership."""
    host = (urlsplit(str(url or "")).hostname or "").lower()
    if host.endswith(".jobstreet.com"):
        return "JobStreet"
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "LinkedIn"
    if host.endswith(".indeed.com"):
        return "Indeed"
    if host == "my.hiredly.com":
        return "Hiredly"
    if host.endswith(".mycareersfuture.gov.sg"):
        return "MyCareersFuture"
    return "Employer ATS / other"


# Coverage requirements from source-routing.md: these are NOT satisfied by
# seeing a single API-proxy link on the relevant native hiring platform.
PLATFORM_FAMILIES = {
    "SG": ("LinkedIn", "JobStreet", "Indeed", "MyCareersFuture"),
    "MY": ("LinkedIn", "JobStreet", "Indeed", "Hiredly"),
    "CN": ("BOSS直聘", "牛客", "猎聘", "智联", "51job"),
}


def platform_coverage(results):
    """Read-only proxy evidence, not a claim of direct/native platform search."""
    lines = ["# Platform coverage: API proxy ≠ native search", "",
             "Native/platform-wide scans are not performed by this Action. "
             "All source hits below are exact role URLs found *through an API*; "
             "a count does not establish full platform recall or current job liveness.",
             "", "| Market | Named platform | API-proxy exact links | Native verified here | Status |",
             "|---|---|---:|---:|---|"]
    for market in MARKETS:
        jobs = results[market]["jobs"]
        for name in PLATFORM_FAMILIES[market]:
            count = sum(x.get("source_platform") == name for x in jobs)
            status = "API_PROXY_ONLY" if count else "NOT_VERIFIED_BY_THIS_ACTION"
            lines.append(f"| {market} | {name} | {count} | 0 | {status} |")
        others = sum(x.get("source_platform") == "Employer ATS / other" for x in jobs)
        lines.append(f"| {market} | Employer ATS / other | {others} | 0 | API_PROXY_ONLY |")
    lines.extend(["", "**Outstanding duties:** SG/MY broad-platform rotations, "
                  "CN BOSS/牛客/猎聘/智联/51job rotations, SG university/PI research. "
                  "Separate native-collection runs must report their own independently "
                  "verified exact IDs; none is credited by this API report.",
                  "",
                  "No source row here is an eligible APPLY or permission to submit."])
    return "\n".join(lines)+"\n"


def normalized(title, company, url, market, *, source, key, uid, location, excerpt):
    if not (title and company and uid and TITLE.search(title)):
        return None
    exact = canonical_apply(url, market)
    if not exact:
        return None
    # Preserve more API-supplied context for downstream *research only*.
    # This does not establish author, completeness, liveness or eligibility.
    description = excerpt if isinstance(excerpt, str) else ""
    # FreeHire's search/list API can return a description clipped near 1,000
    # characters without a truncation flag. This is source uncertainty,
    # *not* a full employer-authored JD. Be conservative for near-cap bodies.
    upstream_cap_suspected = (source.startswith("freehire:") and
                              len(description) >= 950)
    return {
        "market": market, "ats": "external-api",
        "company": str(company)[:150], "title": str(title)[:180],
        "job_id": str(uid)[:128], "key": str(key)[:180],
        "url": exact, "location": str(location or "")[:150],
        "source": source, "source_listing_url": "",
        "source_platform": platform_family(exact),
        "discovery_access": "API_PROXY_ONLY",
        "evidence": "listing_only", "lane": "AI", "triage_priority": "MEDIUM",
        "description_excerpt": description[:240],
        "api_description_text": description[:MAX_API_DESCRIPTION_CHARS],
        "api_description_truncated": (len(description) > MAX_API_DESCRIPTION_CHARS or
                                      upstream_cap_suspected),
        "api_description_cap_suspected": upstream_cap_suspected,
        "api_description_provenance": "UNVERIFIED_THIRD_PARTY_API",
    }


def normalize_freehire(row, market):
    if not isinstance(row, dict):
        return None
    countries = row.get("countries") or []
    if isinstance(countries, str):
        countries = [countries]
    codes = {str(c).strip().upper() for c in countries}
    aliases = {"SG": {"SG", "SINGAPORE"},
               "MY": {"MY", "MALAYSIA"},
               "CN": {"CN", "CHINA"}}
    if codes and not (codes & aliases[market]):
        return None
    location = str(row.get("location") or "")
    if not codes and not LOCATIONS[market].search(location):
        return None
    job = normalized(str(row.get("title") or ""),
                     str(row.get("company") or ""), row.get("url"), market,
                     source=f"freehire:public-api:{market}",
                     uid=row.get("public_slug"), key="freehire|"+str(row.get("public_slug") or ""),
                     location=location, excerpt=row.get("description"))
    if job and not str(row.get("public_slug") or "").strip():
        return None
    return job

def normalize_freehire_full(row, market):
    """Full-text public agent API; still THIRD PARTY and never an official JD."""
    job = normalize_freehire(row, market)
    if job:
        description = row.get("description")
        # The agent endpoint documents full-text results. Only our local 12k
        # output bound can truncate it; the search/list 1k cap does not.
        job["api_description_truncated"] = (
            isinstance(description, str) and
            len(description) > MAX_API_DESCRIPTION_CHARS
        )
        job["api_description_cap_suspected"] = False
        job["api_description_provenance"] = "UNVERIFIED_THIRD_PARTY_API_FULL_TEXT"
    return job


def normalize_aidevboard(row, market):
    if not isinstance(row, dict):
        return None
    loc = str(row.get("location") or "")
    if not LOCATIONS[market].search(loc):
        return None
    if row.get("job_type") in ("contract", "part-time", "internship"):
        if not re.search(r"\bresearch\b|研究", str(row.get("title") or ""), re.I):
            return None
    uid = str(row.get("id") or "")
    if not uid:
        return None
    job = normalized(str(row.get("title") or ""), str(row.get("company_name") or ""),
                     row.get("apply_url"), market,
                     source=f"aidevboard:public-api:{market}",
                     uid=uid, key="aidevboard|"+uid,
                     location=loc, excerpt=row.get("description"))
    if job:
        job["source_listing_url"] = str(row.get("url") or "")[:300]
    return job


def request_page(provider, market, query, page, fetch):
    if provider == "freehire":
        params = urlencode({
            "countries": market, "q": query, "limit": LIMIT,
            "offset": (page-1)*LIMIT, "description_format": "html",
        })
        full_url = "https://freehire.me/api/v1/agent/jobs/search?" + params
        preview_url = ("https://freehire.me/api/v1/jobs/search?" +
                       urlencode({"countries": market, "q": query, "limit": LIMIT,
                                  "offset": (page-1)*LIMIT}))
        converter = normalize_freehire_full
        try:
            payload = fetch(full_url)
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError("FreeHire full-text data[] missing")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as e:
            # On shared 429/rate-limit, do not retry a different FreeHire
            # endpoint. The collector must report this as partial.
            if isinstance(e, HTTPError) and e.code == 429:
                raise
            payload = fetch(preview_url)
            converter = normalize_freehire
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("FreeHire data[] missing")
        meta = payload.get("meta") or {}
        if not isinstance(meta, dict) or not isinstance(meta.get("total"), int):
            raise ValueError("FreeHire total missing")
        ignored = meta.get("ignored_params") or []
        if "countries" in str(ignored).lower():
            raise ValueError("FreeHire geography filter ignored")
        total = meta["total"]
        if total < 0:
            raise ValueError("negative total")
        start = (page-1)*LIMIT
        rows = payload["data"]
        if rows and start >= total:
            raise ValueError("FreeHire page outside total")
        # A suspicious short/empty page must not be silently called exhausted.
        if not rows and start < total:
            raise ValueError("FreeHire inconsistent empty page")
        return rows, (start + len(rows) < total), converter

    url = "https://aidevboard.com/api/v1/jobs?" + urlencode({
        "q": query, "location": MARKETS[market], "limit": LIMIT, "page": page,
    })
    payload = fetch(url)
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError("AI Dev Jobs jobs[] missing")
    if not isinstance(payload.get("has_next"), bool):
        raise ValueError("AI Dev Jobs has_next missing")
    if payload.get("degraded"):
        raise ValueError("AI Dev Jobs degraded response")
    return payload["jobs"], payload["has_next"], normalize_aidevboard


def collect(market, *, fetch=get_json, max_pages=2):
    if market not in MARKETS or max_pages < 1:
        raise ValueError("unsupported market or page budget")
    jobs = {}
    reports = {}
    queries = QUERIES + (CN_EXTRA if market == "CN" else ())
    for provider in ("freehire", "aidevboard"):
        successful_pages, errors, windows, seen_urls = 0, [], [], set()
        full_text_fallback_pages = 0
        for q in queries:
            rows_seen, truncated = 0, False
            for page in range(1, max_pages+1):
                try:
                    rows, has_next, converter = request_page(provider,market,q,page,fetch)
                    successful_pages += 1
                    if provider == "freehire" and converter is normalize_freehire:
                        full_text_fallback_pages += 1
                    rows_seen += len(rows)
                    signatures = set()
                    for row in rows:
                        cand = converter(row,market)
                        if cand:
                            signatures.add(cand["url"])
                            jobs.setdefault(cand["url"], cand)
                            seen_urls.add(cand["url"])
                    if page > 1 and signatures and signatures.issubset(previous_urls):
                        raise ValueError("repeated API page")
                    previous_urls = signatures
                    if not has_next:
                        break
                    if page == max_pages:
                        truncated = True
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as e:
                    errors.append(f"{q}:page{page}:{type(e).__name__}:{str(e)[:110]}")
                    truncated = True
                    # Shared GitHub runner IP might already be throttled.
                    # Do NOT retry 429 across every query window.
                    if isinstance(e, HTTPError) and e.code == 429:
                        windows.append({"q":q,"rows":rows_seen,"truncated":True})
                        break
                    break
            else:
                truncated = True
            if not windows or windows[-1].get("q") != q:
                windows.append({"q":q,"rows":rows_seen,"truncated":truncated})
            if errors and "HTTPError:HTTP Error 429" in errors[-1]:
                break
        reports[provider] = {
            "status": ("UNAVAILABLE" if not successful_pages else
                       "PARTIAL" if (errors or full_text_fallback_pages or
                                     any(w["truncated"] for w in windows))
                       else "COMPLETE"),
            "full_text_fallback_pages": full_text_fallback_pages,
            "successful_pages": successful_pages, "accepted_exact_urls": len(seen_urls),
            "queries": windows, "errors": errors,
        }
    return {"market":market,"jobs":list(jobs.values()),"providers":reports}


def run(out_dir, *, fetch=get_json, max_pages=2):
    out_dir.mkdir(parents=True, exist_ok=True)
    health = {}
    market_results = {}
    for market in MARKETS:
        result = collect(market,fetch=fetch,max_pages=max_pages)
        market_results[market] = result
        health[market] = result["providers"]
        # Preserve the last usable public candidate snapshot on a complete outage.
        # Health still exposes current unavailability; consumer must not interpret
        # a retained snapshot as freshly verified employment.
        if any(p["status"] != "UNAVAILABLE" for p in result["providers"].values()):
            (out_dir / f"{market}.json").write_text(
                json.dumps({"market":market, "jobs":result["jobs"]},indent=2,ensure_ascii=False)+"\n")
        for provider, stats in result["providers"].items():
            print(f"API {market} {provider}: {stats['status']}, "
                  f"trusted exact employer URLs={stats['accepted_exact_urls']}, "
                  f"successful pages={stats['successful_pages']}, "
                  f"first_error={stats['errors'][:1]}")
    (out_dir / "health.json").write_text(json.dumps(health,indent=2)+"\n")
    (out_dir / "platform-coverage.md").write_text(platform_coverage(market_results))
    if all(health[m][p]["status"] == "UNAVAILABLE"
           for m in MARKETS for p in ("freehire", "aidevboard")):
        raise RuntimeError("All API markets unavailable; NOT a zero-job result")
    return health


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out-dir",type=Path,required=True)
    p.add_argument("--max-pages",type=int,choices=(1,2,3),default=2)
    args=p.parse_args()
    run(args.out_dir,max_pages=args.max_pages)


if __name__=="__main__":
    main()
