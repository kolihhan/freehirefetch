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
    parser.close()
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

def build(rows,now,probes=()):
    groups={}; invalid=[]; sources=Counter(); missing=Counter(); conflicts=[]
    route_index={}
    for probe in probes:
        key=role_identity(probe)
        checked=timestamp(probe.get("checked_at"))
        if not key or key[0]!="exact" or not checked or checked>now:
            continue
        k=(key,norm(probe.get("title")),probe.get("evidence_source"))
        if k not in route_index or timestamp(route_index[k]["checked_at"])<checked:
            route_index[k]=probe
    for row in rows:
        key=role_identity(row)
        if not key or not clean_text(row.get("title")):
            invalid.append({"source":row.get("source"),"source_file":row.get("source_file"),"title":row.get("title"),"url":row.get("url") or row.get("source_url"),"reason":"MISSING_TITLE" if not clean_text(row.get("title")) else "INVALID_URL"}); continue
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
        if conflict: conflicts.append({"identity":list(key),"titles":sorted({clean_text(x.get("title")) for x in items}),"sources":sorted({x.get("source","unknown") for x in items})})
        observations=[]
        for x in items:
            observations.append({k:x[k] for k in ("source","source_file","market","url","source_url",
                "key","job_id","event_seq","observed_at","discovery_freshness","source_run_status","jd_kind","jd_checked_at","jd_ref","posted_at","salary","salary_summary","salary_components","experience","education","employment_type","recruit_label","apply_url","location","company","title") if x.get(k) is not None})
        markets=sorted({x["market"] for x in items if x.get("market") in MARKETS})
        locations=sorted({clean_text(x.get("location")) for x in items if clean_text(x.get("location"))})
        loc_markets=sorted({m for loc in locations for m in location_markets(loc)})
        full=[x for x in items if x.get("jd_kind")=="full_jd" and x.get("jd_ref") and fresh(x.get("jd_checked_at"),now) and x.get("discovery_freshness")!="RETAINED_UNVERIFIED"]
        jd=max(full,key=lambda x:timestamp(x["jd_checked_at"])) if full and not conflict else None
        routes=[]
        if not conflict:
            for evidence_source in ("api","browser"):
                p=route_index.get((key,norm(primary.get("title")),evidence_source))
                if p:
                    routes.append({"source":evidence_source,"status":p.get("status"),"checked_at":p["checked_at"],"fresh":fresh(p["checked_at"],now),"apply_url":p.get("apply_url_observed") or p.get("apply_url"),"title_match":p.get("title_match")})
        job={"id":"job:"+hashlib.sha256(json.dumps(key,ensure_ascii=False).encode()).hexdigest()[:24],
             "title":clean_text(primary.get("title")),"company":next((clean_text(x.get("company")) for x in items if clean_text(x.get("company"))),""),
             "url":primary.get("url") or primary.get("source_url") or primary.get("freehire_url"),
             "locations":locations,"observed_markets":markets,"location_markets":loc_markets,
             "location_status":"EXPLICIT_LOCATION_SIGNAL" if loc_markets else "UNRESOLVED",
             "identity_conflict":conflict,"identity_quality":"EXACT_ROLE" if key[0]=="exact" else ("AGGREGATOR_ID" if key[0]=="freehire" else "UNVERIFIED_URL"),"fresh_full_jd":bool(jd),"jd_ref":jd.get("jd_ref") if jd else None,
             "jd_checked_at":jd.get("jd_checked_at") if jd else None,
             "excerpt":clean_text(primary.get("excerpt"))[:600],
             "observations":observations,"application_evidence":routes}
        # Digest substantive evidence, not run time or mutable shard number.
        job["content_fingerprint"]=hashlib.sha256(json.dumps({"title":job["title"],"company":job["company"],"locations":locations,"markets":markets,"conflict":conflict,"jd":(jd or {}).get("jd_ref",{}),"routes":[(p["source"],p["status"],p["fresh"]) for p in routes],"metadata":sorted({json.dumps({k:x.get(k) for k in ("salary","salary_summary","salary_components","employment_type","experience","education","posted_at","recruit_label")},ensure_ascii=False,sort_keys=True) for x in items})},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        for field in ("company","locations","location_markets"):
            if not job[field]: missing[field]+=1
        jobs.append(job)
    jobs.sort(key=lambda j:(not j["identity_conflict"],j["fresh_full_jd"],max((o.get("event_seq") or 0 for o in j["observations"]),default=0),j["id"]),reverse=True)
    valid=len(rows)-len(invalid)
    return jobs,{"input_observations":len(rows),"valid_observations":valid,"invalid_observations":len(invalid),"invalid_details":invalid,"conflict_details":conflicts,
        "unique_roles":len(jobs),"duplicate_observations":valid-len(jobs),"identity_conflicts":sum(j["identity_conflict"] for j in jobs),
        "fresh_full_jd":sum(j["fresh_full_jd"] for j in jobs),"unverified_url_roles":sum(j["identity_quality"]=="UNVERIFIED_URL" for j in jobs),"fresh_api_evidence":sum(any(p["source"]=="api" and p["fresh"] for p in j["application_evidence"]) for j in jobs),"fresh_browser_evidence":sum(any(p["source"]=="browser" and p["fresh"] for p in j["application_evidence"]) for j in jobs),"missing_fields":dict(missing),"source_observations":dict(sources)}

def collect(root):
    rows=[]; health={}; cache={}; run_health={}; probes=[]
    def read(rel):
        if rel in cache: return cache[rel]
        try:
            d=json.loads((root/rel).read_text())
            if not isinstance(d,dict): raise ValueError("not object")
            health[rel]="FILE_READ"
            cache[rel]=d
            return d
        except (OSError,ValueError,TypeError) as exc:
            health[rel]="UNAVAILABLE:"+type(exc).__name__
            cache[rel]={}
            return {}
    def add(raw,source,rel,**fields):
        if isinstance(raw,dict):
            rows.append({**raw,**fields,"source":source,"source_file":rel})
    ats_health=read("feed/ats/health.json"); api_health=read("feed/market-api/health.json"); cn_health=read("feed/cn-native/health.json")
    run_health["ats"]={k:{"status":v.get("status"),"rows_read":v.get("rows_read")} for k,v in ats_health.get("boards",{}).items() if isinstance(v,dict)}
    run_health["market_api"]={m:{k:{f:v.get(f) for f in ("status","successful_pages","accepted_exact_urls")} for k,v in api_health.get(m,{}).items() if isinstance(v,dict)} for m in sorted(MARKETS)}
    run_health["cn_native"]=cn_health
    rel="feed/candidates.json"; d=read(rel)
    for x in d.get("candidates",[]):
        add(x,"freehire",rel,observed_at=d.get("generated_at"),excerpt=x.get("description_excerpt"))
    jd_index=read("feed/ats/jd/index.json")
    index={(x.get("key"),x.get("url"),norm(x.get("title"))):x for x in jd_index.get("jobs",[]) if isinstance(x,dict)}
    jd_parts={}
    for market in sorted(MARKETS):
        rel=f"feed/ats/markets/{market}.json"; d=read(rel)
        for x in d.get("jobs",[]):
            meta=index.get((x.get("key"),x.get("url"),norm(x.get("title"))),{})
            part=meta.get("part","")
            valid_part=isinstance(part,str) and re.fullmatch(r"(?:SG|CN|MY)-[0-9]{3}\.json",part)
            body={}
            if valid_part and part.startswith(market+"-"):
                if part not in jd_parts:
                    jd_parts[part]={ (j.get("key"),j.get("url"),norm(j.get("title"))):j for j in read("feed/ats/jd/"+part).get("jobs",[]) if isinstance(j,dict)}
                body=jd_parts[part].get((x.get("key"),x.get("url"),norm(x.get("title"))),{})
            description=body.get("description_text")
            complete=(x.get("evidence")=="full_jd" and meta.get("description_truncated") is False
                and body.get("description_truncated") is False and isinstance(description,str) and len(description.strip())>=350)
            board=str(x.get("key","")).split("|")
            board_key=board[1]+":"+board[0] if len(board)>=3 else ""
            board_status=run_health["ats"].get(board_key,{}).get("status","UNKNOWN")
            add(x,"official-ats",rel,market=market,observed_at=x.get("source_checked_at"),source_run_status=board_status,
                jd_kind="full_jd" if complete else ("partial_jd" if x.get("evidence")=="full_jd" else x.get("evidence")),jd_checked_at=meta.get("checked_at"),
                jd_ref={"path":"feed/ats/jd/"+part,"key":x.get("key"),"sha256":hashlib.sha256(description.encode()).hexdigest()} if complete else None,
                excerpt=x.get("description_excerpt"))
        rel=f"feed/market-api/{market}.json"; d=read(rel)
        for x in d.get("jobs",[]):
            provider=str(x.get("source","")).split(":")[0]
            add(x,"market-api",rel,market=market,source_run_status=run_health["market_api"].get(market,{}).get(provider,{}).get("status","UNKNOWN"),jd_kind="listing_only",excerpt=x.get("description_excerpt"))
    rel="feed/sg-research/current.json"; d=read(rel)
    for group in d.get("sources",[]):
        for x in group.get("jobs",[]):
            add(x,"sg-research",rel,market="SG",company=group.get("source"),observed_at=d.get("observed_at"),jd_kind="listing_only",excerpt=x.get("page_text_excerpt"))
    rel="feed/cn-native/liepin-raw.json"; d=read(rel)
    latest=cn_health.get("liepin",{})
    retained=(timestamp(cn_health.get("checked_at")) is not None and timestamp(d.get("generatedAt")) is not None and timestamp(cn_health["checked_at"])>timestamp(d["generatedAt"]) and latest.get("jobs")==0)
    for x in d.get("jobs",[]): add(x,"liepin",rel,market="CN",observed_at=d.get("generatedAt"),source_run_status=latest.get("status","UNKNOWN"),discovery_freshness="RETAINED_UNVERIFIED" if retained else "UNKNOWN",posted_at=x.get("date"),jd_kind="listing_only")
    rel="feed/cn-native/platform-public.json"; d=read(rel)
    for group in d.get("sources",[]):
        for x in group.get("jobs",[]): add(x,group.get("source","cn-platform"),rel,market="CN",observed_at=d.get("run_at"),jd_kind="listing_only")
    for name in ("ai","agent","llm","nlp","eval","backend","swe"):
        rel=f"feed/cn-native/jobpro-{name}.json"; d=read(rel)
        for group in d.get("results",[]):
            company=group.get("company")
            for x in group.get("positions",[]):
                url=official_url(company,x)
                if url: add(x,"jobpro-list",rel,url=url,company=company,market="CN",job_id=str(x.get("post_id")),location=x.get("work_cities"),source_run_status="COMPLETE" if d.get("ok") is True and not d.get("failed") else "PARTIAL_OR_UNKNOWN",jd_kind="listing_only")
    rel="feed/cn-native/jobpro-jd.json"; d=read(rel)
    for x in d.get("jobs",[]):
        valid=x.get("full_jd_complete") is True and x.get("description_truncated") is False and bool(x.get("full_jd_text"))
        add(x,"jobpro-detail",rel,market="CN",company=x.get("company_key"),jd_kind="full_jd" if valid else "listing_only",
            jd_checked_at=x.get("checked_at"),jd_ref={"path":rel,"job_id":x.get("job_id"),"sha256":hashlib.sha256(x["full_jd_text"].encode()).hexdigest()} if valid else None,excerpt=x.get("description_text"))
    for kind,rel in (("api","feed/ats/api-liveness.json"),("browser","feed/ats/application-probes.json")):
        for item in read(rel).get("jobs",[]):
            if isinstance(item,dict): probes.append({**item,"evidence_source":kind})
    return rows,health,run_health,probes

def main():
    p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,default=Path(".")); args=p.parse_args()
    start=time.monotonic()
    rows,health,run_health,probes=collect(args.root)
    jobs,audit=build(rows,datetime.now(timezone.utc),probes)
    if not jobs: raise SystemExit("No valid observations; preserve prior clean projection")
    base=args.root/"feed/clean"; base.mkdir(parents=True,exist_ok=True)
    parts=[]
    for offset in range(0,len(jobs),25):
        subset=jobs[offset:offset+25]; name=f"roles-{offset//25:04d}.json"
        payload=json.dumps({"version":1,"jobs":subset},ensure_ascii=False,indent=2)+"\n"
        _atomic_write_text(base/name,payload)
        parts.append({"path":"feed/clean/"+name,"count":len(subset),"sha256":hashlib.sha256(payload.encode()).hexdigest()})
    for file in base.glob("roles-*.json"):
        if "feed/clean/"+file.name not in {p["path"] for p in parts}: file.unlink()
    audit.update({"version":1,"generated_at":datetime.now(timezone.utc).isoformat(),"file_reads":health,"source_run_health":run_health,"parts":parts,"snapshot_id":hashlib.sha256(json.dumps(parts,sort_keys=True).encode()).hexdigest(),"consumption":"Pin one repository commit for index and shards; dedupe on id + content_fingerprint, never use ordinal shard as a durable cursor.",
        "projection_seconds":round(time.monotonic()-start,3),"scope":"latest firehose delta + available source snapshots; not a lossless journal, location signals not work authorization, JD references not live routes"})
    _atomic_write_text(base/"index.json",json.dumps(audit,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:v for k,v in audit.items() if k not in {"file_reads","source_run_health","parts"}},ensure_ascii=False))
if __name__=="__main__": main()
