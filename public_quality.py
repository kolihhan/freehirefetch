#!/usr/bin/env python3
"""Read-only, profile-agnostic clean projection of existing public observations."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
import hashlib
import json
import re
import time
from urllib.parse import urlsplit
from application_probe import identity
from hydrate_cn_jobpro_jd import official_url
from candidate_snapshot import _atomic_write_text

MARKETS = {"SG","CN","MY"}
JD_MAX_AGE = timedelta(hours=24)
class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]; self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in {"script","style"}: self.hidden+=1
    def handle_endtag(self,tag):
        if tag in {"script","style"}: self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden: self.parts.append(data)

def clean_text(value):
    if isinstance(value,list): value="; ".join(str(x) for x in value)
    parser=Text()
    parser.feed(str(value or ""))
    return " ".join(" ".join(parser.parts).split())

def timestamp(value):
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return dt if dt.tzinfo else None
    except (ValueError,TypeError): return None

def fresh(value,now):
    dt=timestamp(value)
    return dt is not None and timedelta(0)<=now-dt<=JD_MAX_AGE

def role_identity(row):
    url=row.get("url") or row.get("source_url") or row.get("freehire_url") or ""
    try:
        p=urlsplit(url)
        if p.scheme!="https" or not p.hostname or p.username or p.password or p.port not in (None,443): return None
        exact=identity(url)
    except (TypeError,ValueError,AttributeError): return None
    if exact: return ("exact",*exact)
    if p.hostname in {"freehire.me","www.freehire.me"}:
        m=re.fullmatch(r"/(?:api/v1/go|jobs)/([a-zA-Z0-9_-]+)",p.path.rstrip("/"))
        if m: return ("freehire",m[1].lower())
    # Unknown sites may use query/fragment as identity. Do not strip them.
    return ("literal",url)

def location_markets(value):
    text=clean_text(value)
    result=[]
    for market,pattern in (
      ("SG",r"\bSingapore\b|新加坡"),
      ("MY",r"\b(?:Malaysia|Kuala Lumpur|Penang|Selangor|Johor|Cyberjaya|Putrajaya)\b|马来西亚|吉隆坡|槟城"),
      ("CN",r"\b(?:China|Beijing|Shanghai|Shenzhen|Guangzhou|Hangzhou|Chengdu|Nanjing|Suzhou|Wuhan|Xi.an|Chongqing|Tianjin|Ningbo|Xiamen|Fuzhou|Hefei)\b|中国大陆|中国|北京|上海|深圳|广州|杭州|成都|南京|苏州|武汉|西安|重庆|天津|宁波|厦门|福州|合肥")):
        if re.search(pattern,text,re.I): result.append(market)
    return result

def norm(value):
    return re.sub(r"[^\w]+","",clean_text(value).casefold())

def build(rows,now):
    groups={}; invalid=0; sources=Counter(); missing=Counter()
    for row in rows:
        key=role_identity(row)
        if not key or not clean_text(row.get("title")):
            invalid+=1; continue
        sources[row.get("source","unknown")]+=1
        groups.setdefault(key,[]).append(row)
    jobs=[]
    for key,items in groups.items():
        # The strongest first-party observation supplies display fields, not eligibility.
        items.sort(key=lambda x: (x.get("source") in {"official-ats","jobpro-detail","jobpro-list"},
                    bool(x.get("company")),bool(x.get("location"))),reverse=True)
        primary=items[0]
        titles={norm(x.get("title")) for x in items if x.get("title")}
        conflict=len(titles)>1
        observations=[]
        for x in items:
            observations.append({k:x[k] for k in ("source","source_file","market","url","source_url",
                "key","job_id","event_seq","observed_at","discovery_freshness","jd_kind","jd_checked_at","jd_ref") if x.get(k) is not None})
        markets=sorted({x["market"] for x in items if x.get("market") in MARKETS})
        locations=sorted({clean_text(x.get("location")) for x in items if clean_text(x.get("location"))})
        loc_markets=sorted({m for loc in locations for m in location_markets(loc)})
        full=[x for x in items if x.get("jd_kind")=="full_jd" and x.get("jd_ref") and fresh(x.get("jd_checked_at"),now) and x.get("discovery_freshness")!="RETAINED_UNVERIFIED"]
        jd=max(full,key=lambda x:timestamp(x["jd_checked_at"])) if full and not conflict else None
        job={"id":"job:"+hashlib.sha256(json.dumps(key,ensure_ascii=False).encode()).hexdigest()[:24],
             "title":clean_text(primary.get("title")),"company":next((clean_text(x.get("company")) for x in items if clean_text(x.get("company"))),""),
             "url":primary.get("url") or primary.get("source_url") or primary.get("freehire_url"),
             "locations":locations,"observed_markets":markets,"location_markets":loc_markets,
             "location_status":"EXPLICIT_LOCATION_SIGNAL" if loc_markets else "UNRESOLVED",
             "identity_conflict":conflict,"fresh_full_jd":bool(jd),"jd_ref":jd.get("jd_ref") if jd else None,
             "jd_checked_at":jd.get("jd_checked_at") if jd else None,
             "excerpt":clean_text(primary.get("excerpt"))[:600],
             "observations":observations}
        for field in ("company","locations","location_markets"):
            if not job[field]: missing[field]+=1
        jobs.append(job)
    jobs.sort(key=lambda j:(not j["identity_conflict"],j["fresh_full_jd"],max((o.get("event_seq") or 0 for o in j["observations"]),default=0),j["id"]),reverse=True)
    valid=len(rows)-invalid
    return jobs,{"input_observations":len(rows),"valid_observations":valid,"invalid_observations":invalid,
        "unique_roles":len(jobs),"duplicate_observations":valid-len(jobs),"identity_conflicts":sum(j["identity_conflict"] for j in jobs),
        "fresh_full_jd":sum(j["fresh_full_jd"] for j in jobs),"missing_fields":dict(missing),"source_observations":dict(sources)}

def collect(root):
    rows=[]; health={}
    def read(rel):
        try:
            d=json.loads((root/rel).read_text())
            if not isinstance(d,dict): raise ValueError("not object")
            health[rel]="AVAILABLE"
            return d
        except (OSError,ValueError,TypeError) as exc:
            health[rel]="UNAVAILABLE:"+type(exc).__name__
            return {}
    def add(raw,source,rel,**fields):
        if isinstance(raw,dict):
            rows.append({**raw,**fields,"source":source,"source_file":rel})
    rel="feed/candidates.json"; d=read(rel)
    for x in d.get("candidates",[]):
        add(x,"freehire",rel,observed_at=d.get("generated_at"),excerpt=x.get("description_excerpt"))
    jd_index=read("feed/ats/jd/index.json")
    index={(x.get("key"),x.get("url"),norm(x.get("title"))):x for x in jd_index.get("jobs",[]) if isinstance(x,dict)}
    for market in sorted(MARKETS):
        rel=f"feed/ats/markets/{market}.json"; d=read(rel)
        for x in d.get("jobs",[]):
            meta=index.get((x.get("key"),x.get("url"),norm(x.get("title"))),{})
            part=meta.get("part","")
            valid_part=isinstance(part,str) and re.fullmatch(r"(?:SG|CN|MY)-[0-9]{3}\.json",part)
            add(x,"official-ats",rel,market=market,observed_at=x.get("source_checked_at"),
                jd_kind=x.get("evidence"),jd_checked_at=meta.get("checked_at"),
                jd_ref={"path":"feed/ats/jd/"+part,"key":x.get("key")} if valid_part and meta.get("description_truncated") is False else None,
                excerpt=x.get("description_excerpt"))
        rel=f"feed/market-api/{market}.json"; d=read(rel)
        for x in d.get("jobs",[]):
            add(x,"market-api",rel,market=market,jd_kind="listing_only",excerpt=x.get("description_excerpt"))
    rel="feed/sg-research/current.json"; d=read(rel)
    for group in d.get("sources",[]):
        for x in group.get("jobs",[]):
            add(x,"sg-research",rel,market="SG",company=group.get("source"),observed_at=d.get("observed_at"),jd_kind="listing_only",excerpt=x.get("page_text_excerpt"))
    rel="feed/cn-native/liepin-raw.json"; d=read(rel)
    for x in d.get("jobs",[]): add(x,"liepin",rel,market="CN",jd_kind="listing_only")
    rel="feed/cn-native/platform-public.json"; d=read(rel)
    for group in d.get("sources",[]):
        for x in group.get("jobs",[]): add(x,group.get("source","cn-platform"),rel,market="CN",observed_at=d.get("run_at"),jd_kind="listing_only")
    for name in ("ai","agent","llm","nlp","eval","backend","swe"):
        rel=f"feed/cn-native/jobpro-{name}.json"; d=read(rel)
        for group in d.get("results",[]):
            company=group.get("company")
            for x in group.get("positions",[]):
                url=official_url(company,x)
                if url: add(x,"jobpro-list",rel,url=url,company=company,market="CN",job_id=str(x.get("post_id")),location=x.get("work_cities"),jd_kind="listing_only")
    rel="feed/cn-native/jobpro-jd.json"; d=read(rel)
    for x in d.get("jobs",[]):
        valid=x.get("full_jd_complete") is True and x.get("description_truncated") is False and bool(x.get("full_jd_text"))
        add(x,"jobpro-detail",rel,market="CN",company=x.get("company_key"),jd_kind="full_jd" if valid else "listing_only",
            jd_checked_at=x.get("checked_at"),jd_ref={"path":rel,"job_id":x.get("job_id")} if valid else None,excerpt=x.get("description_text"))
    return rows,health

def main():
    p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,default=Path(".")); args=p.parse_args()
    start=time.monotonic()
    rows,health=collect(args.root)
    jobs,audit=build(rows,datetime.now(timezone.utc))
    if not jobs: raise SystemExit("No valid observations; preserve prior clean projection")
    base=args.root/"feed/clean"; base.mkdir(parents=True,exist_ok=True)
    parts=[]
    for offset in range(0,len(jobs),25):
        subset=jobs[offset:offset+25]; name=f"roles-{offset//25:04d}.json"
        _atomic_write_text(base/name,json.dumps({"version":1,"jobs":subset},ensure_ascii=False,indent=2)+"\n")
        parts.append({"path":"feed/clean/"+name,"count":len(subset)})
    for file in base.glob("roles-*.json"):
        if "feed/clean/"+file.name not in {p["path"] for p in parts}: file.unlink()
    audit.update({"version":1,"generated_at":datetime.now(timezone.utc).isoformat(),"sources":health,"parts":parts,
        "projection_seconds":round(time.monotonic()-start,3),"scope":"latest firehose delta + available source snapshots; not a lossless journal, location signals not work authorization, JD references not live routes"})
    _atomic_write_text(base/"index.json",json.dumps(audit,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:v for k,v in audit.items() if k not in {"sources","parts"}},ensure_ascii=False))
if __name__=="__main__": main()
