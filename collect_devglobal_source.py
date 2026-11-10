#!/usr/bin/env python3
"""Fetch bounded SG/MY AI-engineering source signals from Dev Global Jobs' public API.

Source is an aggregator, NOT JobStreet/LinkedIn native market coverage.
Its documented free API permits noncommercial internal/research use with
attribution. Each candidate preserves the original Dev Global Jobs URL.
No logins, employer actions, hidden browser scraping, or API keys.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode
from urllib.request import Request,urlopen

URL="https://devglobaljobs.com/api/v1/jobs"
COUNTRIES={"SG":"Singapore","MY":"Malaysia"}
TITLE_DOMAIN=re.compile(r"(?i)(?:\bAI\b|\bML\b|LLM|GenAI|NLP|Agentic|Machine Learning|Deep Learning|RAG|Retrieval|Data Science)")
ENGINEERING=re.compile(r"(?i)engineer|developer|research|scientist|software|backend|platform|systems|inference|architecture|data science|data scientist")
MATURE=re.compile(r"(?i)^\s*(?:senior|staff|principal|lead|director|head|vp|chief|manager)\b")
LIMIT=50
MAX_PAGES=2

def fetch_api(market,offset,fetch=None):
    url=URL+"?"+urlencode({"country":market.lower(),"search":"AI","limit":LIMIT,"offset":offset})
    if fetch is not None:
        return fetch(url)
    req=Request(url,headers={"Accept":"application/json","User-Agent":"FreeHireFetchDevGlobalPublic/1.0"})
    with urlopen(req,timeout=18) as r:
        if r.status!=200:raise ValueError("API returned HTTP "+str(r.status))
        content=r.read(4_000_001)
    if len(content)>4_000_000:raise ValueError("oversized API response")
    return json.loads(content.decode("utf-8"))

def parse_roles(data,market):
    if not isinstance(data,dict) or not isinstance(data.get("jobs"),list):
        raise ValueError("missing structured jobs list")
    rows=[]
    for j in data["jobs"]:
        if not isinstance(j,dict):continue
        jid=str(j.get("id") or "").strip()
        title=str(j.get("title") or "").strip()
        company=j.get("companyName") or j.get("company") or j.get("organisation") or j.get("organization") or ""
        if isinstance(company,dict):company=company.get("name","")
        location=str(j.get("location") or j.get("city") or "")
        original=j.get("url") or j.get("link") or ""
        if not (jid.isdigit() and title and COUNTRIES[market].lower() in location.lower()):
            continue
        if not (TITLE_DOMAIN.search(title) and ENGINEERING.search(title)):
            continue
        if MATURE.search(title):
            continue
        source_url=f"https://devglobaljobs.com/jobs/detail/{jid}"
        # Do not trust a second-party record to confirm the employer's own JD.
        rows.append({"market":market,"platform":"Dev Global Jobs (public aggregator)",
             "url":source_url,"source_id":jid,"title":title[:160],
             "company":str(company)[:150],"location":location[:140],
             "query":"SG/MY AI software engineering / NLP / Agent public-feed AI",
             "source_kind":"aggregator_feed","exact_jd_unverified":True,
             "source_page_url":source_url})
    return rows

def scan(market,fetch=None):
    rows=[]
    pages=[]
    failed=[]
    for page in range(MAX_PAGES):
        try:
            data=fetch_api(market,page*LIMIT,fetch)
            raw=data["jobs"] if isinstance(data,dict) else None
            if not isinstance(raw,list):raise ValueError("missing jobs array")
            found=parse_roles(data,market)
            rows.extend(found)
            pages.append({"offset":page*LIMIT,"raw_rows":len(raw),
                "eligible_title_location_rows":len(found),
                "source_ids":[r["source_id"] for r in found[:25]]})
            if len(raw)<LIMIT:break  # API actually returned fewer than page limit
        except Exception as e:
            failed.append({"offset":page*LIMIT,"reason":str(e)[:150]})
            break
        time.sleep(0.4)
    unique={r["url"]:r for r in rows}
    page_ids=[set(p["source_ids"]) for p in pages]
    return {"source":"devglobal:public-api:"+market,"market":market,
        "source_credit":"Powered by Dev Global Jobs — https://devglobaljobs.com",
        "observed_at":datetime.now(timezone.utc).isoformat(),
        "coverage":"PARTIAL_COVERAGE" if failed or (len(pages)==MAX_PAGES and pages[-1]["raw_rows"]==LIMIT) else "BOUNDED_SOURCE_END",
        "pages":pages,"failed_pages":failed,
        "observed_unique_candidates":len(unique),
        "items":list(unique.values())}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out-dir",type=Path,required=True)
    args=ap.parse_args()
    args.out_dir.mkdir(parents=True,exist_ok=True)
    health={}
    for market in ("SG","MY"):
        s=scan(market)
        health[market]={"coverage":s["coverage"],"pages":len(s["pages"]),
                        "failed_pages":len(s["failed_pages"]),
                        "observed_at":s["observed_at"],
                        "usable_candidates":len(s["items"])}
        f=args.out_dir/f"devglobal-{market.lower()}-candidates.json"
        if s["pages"]:
            # Failed entire listing: preserve previous source snapshot.
            f.write_text(json.dumps(s,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps({"market":market,"coverage":s["coverage"],"pages":s["pages"],
          "failed":s["failed_pages"],"eligible_candidates":len(s["items"])},
          ensure_ascii=False),flush=True)
    (args.out_dir/"health.json").write_text(json.dumps(health,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    main()
