#!/usr/bin/env python3
"""Read-only public application evidence. No applicants, login, form submission,
CAPTCHA bypass, or eligibility decisions. Feed consumers must check freshness.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import re
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin, unquote, parse_qs
from hydrate_cn_jobpro_jd import official_url, FEISHU_HOSTS, normalized_title

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "feed/ats/application-probes.json"
HOSTS = {
    "jobs.ashbyhq.com", "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io",
    "boards.greenhouse.io", "boards.eu.greenhouse.io", "jobs.lever.co",
    "jobs.smartrecruiters.com", "sg.jobstreet.com", "www.linkedin.com",
    "sg.linkedin.com", "my.linkedin.com", "sg.indeed.com", "malaysia.indeed.com", "my.indeed.com",
    "my.jobstreet.com", "my.hiredly.com", "abnormal.ai", "www.liepin.com",
    "join.qq.com", "jobs.bytedance.com", "campus-talent.alibaba.com",
    "careers.sutd.edu.sg", "careers.nus.edu.sg", "careers.a-star.edu.sg",
    *FEISHU_HOSTS.values(),
}
CORE = re.compile(r"\b(llm|nlp|rag|agentic|agents?|retrieval|generative ai|genai|machine learning|ai (?:software |application |research |systems? |platform )?engineer|research (?:engineer|assistant|associate|officer|scientist|fellow)|data scientist|applied ai|ai developer|ml engineer)\b|大模型|智能体|自然语言|检索|模型评测", re.I | re.ASCII)
HARD_TITLE = re.compile(r"\b(intern(ship)?|principal|staff|director|head of|manager|vice president|chief)\b|实习|派遣", re.I)
CONTRACT = re.compile(r"\b(?:fixed[- ]term|temporary|[1-9][0-9]*[- ](?:year|month)[- ]contract|contract role|contract position)\b|劳务派遣|短期合同", re.I)
RESEARCH_ROLE = re.compile(r"\bresearch (?:assistant|associate|engineer|officer|scientist|fellow)\b|研究助理|研究工程师|研究员", re.I | re.ASCII)

def excluded_contract(title, employment=""):
    text = title + " " + str(employment or "")
    # Research appointments often use fixed terms; outsourcing remains excluded.
    return bool(re.search(r"劳务派遣|\b(?:outsourced|staff augmentation)\b", text, re.I)
                or (CONTRACT.search(text) and not RESEARCH_ROLE.search(title)))

CLOSED = re.compile(r"(?:this (?:job|position|vacancy|posting) (?:is|has been) (?:closed|filled|removed|expired|no longer available)|(?:no longer accepting|not currently accepting) applications|this job is no longer accepting applications|job posting not found|this job has expired|该职位已下线|职位已关闭|职位已过期)", re.I)
BLOCKED = re.compile(r"verify (?:that )?you are human|access denied|unusual traffic|security verification|checking your browser|captcha|just a moment", re.I)
AUTH = re.compile(r"sign in|log in|login|create (?:an |your )?account|register to apply", re.I)
APPLY = re.compile(r"^\s*(?:apply(?: now| for this (?:job|position)| to this job| on company site)?|i['’]m interested|申请职位|立即申请|立即投递|投递简历)\s*$", re.I)

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def allowed(url):
    try:
        p = urlparse(url)
        return (p.scheme == "https" and not p.username and not p.password
                and p.port in (None, 443)
                and (p.hostname in HOSTS or bool(re.fullmatch(r"[a-z0-9-]+\.wd[0-9]+\.myworkdayjobs\.com", p.hostname or ""))))
    except ValueError:
        return False

def identity(url):
    """Only identify exact known role paths, never a generic careers homepage."""
    if not allowed(url):
        return None
    p = urlparse(url)
    path = unquote(p.path).rstrip("/")
    h = p.hostname
    if h == "join.qq.com":
        ids = parse_qs(p.query).get("postid", [])
        return (h, ids[0]) if path == "/post_detail.html" and len(ids) == 1 and re.fullmatch(r"\d{10,20}", ids[0]) else None
    if h == "jobs.bytedance.com":
        m = re.fullmatch(r"/(?:campus|experienced)/position/(\d{10,20})/detail", path)
        return (h, m[1]) if m else None
    if h == "campus-talent.alibaba.com":
        m = re.fullmatch(r"/campus/position/(\d{10,20})", path)
        return (h, m[1]) if m else None
    if h in FEISHU_HOSTS.values():
        m = re.fullmatch(r"/[A-Za-z0-9_-]+/position/(\d{10,20})/detail", path)
        return (h, m[1]) if m else None
    if h in {"careers.sutd.edu.sg", "careers.nus.edu.sg", "careers.a-star.edu.sg"}:
        m = re.search(r"/job/.+/(\d{2,12})(?:-[A-Za-z_]+)?$", path)
        return (h, m[1]) if m else None
    if h == "www.liepin.com":
        m = re.fullmatch(r"/job/(\d{5,16})\.shtml", path)
        return (h, m[1]) if m else None
    if h in {"sg.indeed.com", "malaysia.indeed.com", "my.indeed.com"}:
        key = parse_qs(p.query).get("jk", [""])[0]
        return ("malaysia.indeed.com" if h == "my.indeed.com" else h, key) if path == "/viewjob" and re.fullmatch(r"[a-f0-9]{16}", key) else None
    if h in {"www.linkedin.com", "sg.linkedin.com", "my.linkedin.com"}:
        m = re.search(r"/jobs/view/(?:[^/]*-)?(\d+)(?:/|$)", path)
        return ("linkedin", m[1]) if m else None
    if h in {"sg.jobstreet.com", "my.jobstreet.com"}:
        m = re.search(r"/job/(\d+)(?:/|$)", path)
        return (h, m[1]) if m else None
    if h == "my.hiredly.com":
        m = re.fullmatch(r"/jobs/(?:[^/]+/)?[\w-]{7,}", path)
        return (h, path) if m else None
    if h.endswith(".myworkdayjobs.com"):
        m = re.search(r"/job/[^?]+_([A-Za-z0-9-]+)(?:/|$)", path)
        return (h, m[1].lower()) if m else None
    if h in {"jobs.ashbyhq.com", "jobs.lever.co"}:
        m = re.match(r"/([^/]+)/([0-9a-fA-F-]{36})(?:/|$)", path)
        return (h, m[1].lower()+"/"+m[2].lower()) if m else None
    if h == "jobs.smartrecruiters.com":
        m = re.match(r"/([^/]+)/(\d{10,})(?:-|/|$)", path)
        return (h, m[1].lower()+"/"+m[2]) if m else None
    if "greenhouse.io" in h:
        m = re.search(r"/([^/]+)/jobs/(\d+)(?:/|$)", path)
        return ("greenhouse", m[1].lower()+"/"+m[2]) if m else None
    if h == "abnormal.ai":
        m = re.search(r"/careers/jobs/(\d+)(?:/|$)", path)
        return (h, m[1]) if m else None
    return None

def classify(expected, current, status, body, title_present, fields, controls):
    """Pure classification; only affirmative role-specific form evidence is LIVE_FORM."""
    if status in (401, 403, 429) or BLOCKED.search(body[:1500]):
        return "BLOCKED"
    if status in (404, 410) and identity(current) == expected:
        return "NOT_FOUND_HTTP"
    if identity(current) != expected:
        return "IDENTITY_UNCONFIRMED"
    if CLOSED.search(body):
        return "CLOSED_EXPLICIT"
    if status is None or status >= 400:
        return "UNKNOWN_HTTP"
    if not title_present:
        return "IDENTITY_UNCONFIRMED"
    # Form inputs must be visible and belong to a public application, not a sign-in.
    if {"email", "resume", "name"} <= set(fields) and "password" not in fields:
        return "LIVE_FORM"
    if "password" in fields or (AUTH.search(body[:1800]) and not controls):
        return "AUTH_REQUIRED"
    if controls:
        return "APPLY_CONTROL_ONLY"
    return "JD_ONLY"

def norm(s):
    return " ".join(re.findall(r"\w+", str(s or "").casefold()))

async def observe(page, job, expected, url):
    response = await page.goto(url, wait_until="domcontentloaded", timeout=14000)
    # An arbitrary h1 (including a loading screen) is not the role title.
    # Wait for exact normalized title or a terminal public-page signal.
    title = norm(job.get("title"))
    try:
        await page.wait_for_function("""title => {
          const body = document.body?.innerText || "";
          const norm = s => (s.toLowerCase().match(/[\\p{L}\\p{N}_]+/gu) || []).join(" ");
          return (title && norm(body).includes(title)) || /no longer accepting|no longer available|job posting not found|access denied|verify you are human|职位已关闭/i.test(body);
        }""", arg=title, timeout=7500)
        if urlparse(url).hostname == "jobs.ashbyhq.com" and urlparse(url).path.rstrip("/").endswith("/application"):
            await page.locator("input:not([type=hidden]), textarea").first.wait_for(state="visible", timeout=4500)
    except Exception:
        pass
    body = (await page.locator("body").inner_text(timeout=4000))[:35000]
    present = bool(title and title in norm(body))
    data = await page.evaluate("""() => {
      const visible = e => !!(e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
      const allFields = [];
      const groups = new Map();
      for (const e of document.querySelectorAll('input,textarea,select')) {
        if (!visible(e)) continue;
        const labels = Array.from(e.labels || []).map(x => x.innerText).join(' ');
        const name = [e.name,e.id,e.type,e.placeholder,e.getAttribute('aria-label'),labels].join(' ').toLowerCase();
        const owner = e.form || e.closest('form, [role=form]');
        const fields = [];
        if (/email/.test(name)) fields.push('email');
        if (/password/.test(name)) fields.push('password');
        if (/resume|résumé|curriculum|\\bcv\\b/.test(name)) fields.push('resume');
        if (/first.?name|last.?name|full.?name|given.?name|family.?name/.test(name) || [e.name,e.id,e.placeholder,e.getAttribute('aria-label'),labels].some(x => (x || '').trim().toLowerCase() === 'name')) fields.push('name');
        allFields.push(...fields);
        if (owner) groups.set(owner, [...(groups.get(owner) || []), ...fields]);
      }
      const application = Array.from(groups.values()).find(xs => ['email','name','resume'].every(x=>xs.includes(x)) && !xs.includes('password'));
      const fields = application || allFields.filter(x => x === 'password');
      return {fields, controls: Array.from(document.querySelectorAll('a,button,[role=button]')).filter(visible)
        .map(e => ({text:(e.innerText || e.getAttribute('aria-label') || '').trim(),href:e.getAttribute('href') || ''})).slice(0,500)};
    }""")
    controls = [c for c in data["controls"] if APPLY.fullmatch(c["text"])]
    state = classify(expected, page.url, response.status if response else None, body, present, data["fields"], controls)
    return {"status":state, "final_url":page.url, "http_status":response.status if response else None,
            "title_match":present, "visible_field_types":sorted(set(data["fields"])),
            "apply_controls":[c["text"][:120] for c in controls][:5]}, controls

async def probe(browser, job, sem):
    url = job["url"]
    expected = identity(url)
    result = {"key":job["key"], "market":job.get("market"), "company":job.get("company"), "title":job.get("title"),
              "url":url, "checked_at":now(), "status":"UNKNOWN"}
    for field in ("source","location","recruit_label","batch_name","jd_evidence","jd_checked_at"):
        if field in job:
            result[field] = job[field]
    async with sem:
        context = await browser.new_context(accept_downloads=False)
        page = await context.new_page()
        # Restrict all top-level navigation to known public job providers.
        async def guard(route):
            req = route.request
            if req.is_navigation_request() and req.frame == page.main_frame and not allowed(req.url):
                await route.abort()
            else:
                await route.continue_()
        await page.route("**/*", guard)
        try:
            result["checked_at"] = now()
            info, controls = await observe(page, job, expected, url)
            result.update(info)
            if info["status"] == "APPLY_CONTROL_ONLY":
                # GET-only exact-requisition links; never press a button, fill,
                # submit, login, follow arbitrary redirects or upload a file.
                urls = [job.get("apply_url") or ""] + [urljoin(page.url,c["href"]) for c in controls if c["href"]]
                target = next((u for u in urls if u and identity(u) == expected and u != page.url and u != url), None)
                if target:
                    result["apply_url_observed"] = target
                    second, _ = await observe(page, job, expected, target)
                    result["apply_page"] = second
                    if second["status"] in ("LIVE_FORM","AUTH_REQUIRED","CLOSED_EXPLICIT","NOT_FOUND_HTTP"):
                        result["status"] = second["status"]
        except Exception as e:
            result["status"] = "UNKNOWN_ERROR"
            result["error"] = type(e).__name__
        finally:
            await context.close()
    return result

def load_jobs(root):
    rows = {}
    # ATS market indexes deliberately omit full JD text; restore it by exact key.
    jd_dir = root/"feed/ats/jd"
    index = jd_dir/"index.json"
    descriptions = {}
    if index.exists():
        for part in json.loads(index.read_text()).get("parts", []):
            rel = part.get("path", "")
            if not re.fullmatch(r"(?:SG|CN|MY)-[0-9]{3}\.json", rel):
                continue
            file = jd_dir/rel
            if file.exists():
                for item in json.loads(file.read_text()).get("jobs", []):
                    descriptions[(item.get("key"), item.get("url"))] = item.get("description_text", "")
    for market in ("SG","CN","MY"):
        for p in (root/"feed/ats/markets"/(market+".json"), root/"feed/market-api"/(market+".json")):
            if not p.exists():
                continue
            for j in json.loads(p.read_text()).get("jobs",[]):
                url = j.get("url","")
                ident = identity(url)
                title = j.get("title","")
                desc = str(j.get("description_text") or j.get("api_description_text") or descriptions.get((j.get("key"), url)) or j.get("description_excerpt") or "")
                technical = re.search(r"\b(?:software|backend|full.stack|research|engineer|scientist|developer)\b|开发|工程师|研究", title, re.I)
                signals = {m.group(0).casefold() for m in CORE.finditer(desc)}
                if not ident or not j.get("key") or not (CORE.search(title) or (technical and len(signals) >= 3)) or HARD_TITLE.search(title):
                    continue
                if excluded_contract(title, j.get("employment_type","")):
                    continue
                # Preserve primary-source representation, also index aliases.
                k = (market, ident)
                if k not in rows:
                    rows[k] = dict(j, aliases=[])
                elif j["key"] != rows[k]["key"]:
                    rows[k]["aliases"].append(j["key"])
    research = root/"feed/sg-research/current.json"
    if research.exists():
        report = json.loads(research.read_text())
        for source in report.get("sources", []):
            for job in source.get("jobs", []):
                url = job.get("url", "")
                ident = identity(url)
                title = job.get("title", "")
                if (not ident or not job.get("job_page_verified") or not job.get("apply_control_seen")
                        or not job.get("technical_signals") or HARD_TITLE.search(title)):
                    continue
                k = ("SG", ident)
                if k not in rows:
                    rows[k] = {"key": "sg-research|" + "|".join(ident), "market":"SG",
                               "title":title, "company":source.get("source",""), "url":url,
                               "source":"sg-research-public-portal", "aliases":[],
                               "job_id":job.get("requisition",""), "jd_evidence":"listing_only",
                               "source_checked_at":report.get("observed_at","")}
    # CN native public sources were previously disconnected from browser probes.
    # Retain source metadata; exact employer role identity, not candidate eligibility.
    src = root/"feed/cn-native"
    liepin = src/"liepin-raw.json"
    if liepin.exists():
        for j in json.loads(liepin.read_text()).get("jobs", []):
            title = str(j.get("title") or "")
            ident = identity(j.get("url", ""))
            if not ident or ident[0] != "www.liepin.com" or not CORE.search(title) or HARD_TITLE.search(title) or excluded_contract(title):
                continue
            if re.search(r"产品经理|销售|运营|设计师|客户成功", title):
                continue
            key = "liepin|" + ident[1]
            url = f"https://www.liepin.com/job/{ident[1]}.shtml"
            k = ("CN", ident)
            if k in rows:
                if key != rows[k]["key"] and key not in rows[k]["aliases"]:
                    rows[k]["aliases"].append(key)
                continue
            rows[k] = {"key":key, "market":"CN", "title":title, "company":j.get("company",""),
                       "url":url, "location":j.get("location",""), "job_id":ident[1],
                       "source":"liepin-public-api", "aliases":[], "jd_evidence":"listing_only"}
    detail_file = src/"jobpro-jd.json"
    details = {}
    if detail_file.exists():
        for d in json.loads(detail_file.read_text()).get("jobs", []):
            if d.get("full_jd_complete") is True and not d.get("description_truncated") and d.get("full_jd_text"):
                details[(d.get("company_key"),str(d.get("job_id")),d.get("url"))] = d
    for name in ("agent","llm","ai","backend","swe"):
        p = src/f"jobpro-{name}.json"
        if not p.exists():
            continue
        for group in json.loads(p.read_text()).get("results", []):
            company = group.get("company","")
            for pos in group.get("positions", []):
                title = str(pos.get("title") or "")
                label = str(pos.get("recruit_label") or "")
                uid = str(pos.get("post_id") or "")
                url = official_url(company,pos)
                if not url or not identity(url) or not CORE.search(title) or HARD_TITLE.search(title+" "+label) or excluded_contract(title, label):
                    continue
                if re.search(r"产品经理|销售|运营|设计师|客户成功", title):
                    continue
                key = f"jobpro|{company}|{uid}"
                k = ("CN",identity(url))
                detail = details.get((company,uid,url),{})
                matched = bool(detail and normalized_title(detail.get("title")) == normalized_title(title))
                if k in rows:
                    if key != rows[k]["key"] and key not in rows[k]["aliases"]:
                        rows[k]["aliases"].append(key)
                    continue
                rows[k] = {"key":key,"market":"CN","company":company,"title":title,
                           "url":url,"location":pos.get("work_cities",""),"job_id":uid,
                           "source":"jobpro-public-employer", "aliases":[],
                           "recruit_label":label,"batch_name":pos.get("batch_name",""),
                           "jd_evidence":"full_jd" if matched else "listing_only",
                           "jd_checked_at":detail.get("checked_at","") if matched else ""}
    return list(rows.values())

MARKETPLACE_HOSTS = {"sg.jobstreet.com", "my.jobstreet.com", "www.linkedin.com", "sg.linkedin.com", "my.linkedin.com", "sg.indeed.com", "my.indeed.com", "malaysia.indeed.com", "my.hiredly.com", "www.liepin.com"}


def select(rows, previous, limit, fresh_keys=()):
    # Protect the public browser budget: marketplaces frequently block CI.
    # Keep a bounded sample, never bypass access controls, and prioritize
    # newly discovered employer roles within the never-checked cohort.
    fresh_keys = set(fresh_keys)
    def priority(j):
        old = previous.get(j["key"],{})
        return (old.get("checked_at",""), j["key"] not in fresh_keys, j.get("jd_evidence") != "full_jd" and j.get("evidence") != "full_jd", j.get("title","").casefold(), j["key"])
    def balanced(pool, budget):
        if budget <= 0:
            return []
        sg = sorted((j for j in pool if j.get("market")=="SG"), key=priority)
        cn = sorted((j for j in pool if j.get("market")=="CN"), key=priority)
        my = sorted((j for j in pool if j.get("market")=="MY"), key=priority)
        my_n = min(len(my), int(budget*.1))
        sg_n = min(len(sg), max(1, int((budget-my_n)*.8)))
        cn_n = min(len(cn),budget-my_n-sg_n)
        return sg[:sg_n] + cn[:cn_n] + my[:my_n] + (sg[sg_n:]+cn[cn_n:]+my[my_n:])[:budget-sg_n-cn_n-my_n]
    direct = [j for j in rows if urlparse(j.get("url","")).hostname not in MARKETPLACE_HOSTS]
    proxy = [j for j in rows if urlparse(j.get("url","")).hostname in MARKETPLACE_HOSTS]
    proxy_cap = min(len(proxy), max(1, int(limit*.15)))
    chosen = balanced(direct, limit - proxy_cap)
    sample = balanced(proxy, min(proxy_cap, limit-len(chosen)))
    seen = {j["key"] for j in chosen}
    return chosen + sample + balanced([j for j in direct if j["key"] not in seen], limit-len(chosen)-len(sample))

async def run(root, limit, workers):
    from playwright.async_api import async_playwright
    target = root/"feed/ats/application-probes.json"
    old = json.loads(target.read_text()) if target.exists() else {}
    prev = {j["key"]:j for j in old.get("jobs",[])}
    rows = load_jobs(root)
    changes = root/"feed/ats/changes.json"
    fresh_keys = {j["key"] for j in json.loads(changes.read_text()).get("events", []) if j.get("kind") == "NEW" and j.get("key")} if changes.exists() else set()
    selected = select(rows,prev,limit,fresh_keys)
    async with async_playwright() as p:
        launch = {"headless":True}
        if os.getenv("CHROMIUM_EXECUTABLE"):
            launch["executable_path"] = os.environ["CHROMIUM_EXECUTABLE"]
        browser = await p.chromium.launch(**launch)
        sem = asyncio.Semaphore(workers)
        tasks = [asyncio.create_task(probe(browser,j,sem)) for j in selected]
        # Keep completed evidence even if slow or blocked pages exceed the run budget.
        done, pending = await asyncio.wait(tasks, timeout=350) if tasks else (set(), set())
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        completed = [(j, t.result()) for j,t in zip(selected,tasks)
                     if t in done and not t.cancelled() and t.exception() is None]
        results = [r for _,r in completed]
        await browser.close()
    current = {}
    for j in rows:
        prior = prev.get(j["key"])
        if prior and prior.get("url")==j["url"]:
            current[j["key"]] = dict(prior, fresh_this_run=False, aliases=j["aliases"])
    for j,r in completed:
        current[j["key"]] = dict(r,fresh_this_run=True,aliases=j["aliases"])
    report={"version":1,"run_at":now(),"eligible_public_urls":len(rows),"attempted":len(results),
            "counts_this_run":dict(Counter(r["status"] for r in results)),
            "host_counts_this_run": {host: dict(Counter(r["status"] for r in results if urlparse(r["url"]).hostname == host)) for host in sorted({urlparse(r["url"]).hostname for r in results})},
            "selected":len(selected), "incomplete":len(selected)-len(results),
            "new_ats_attempted":sum(j["key"] in fresh_keys for j,_ in completed),
            "never_checked_attempted":sum(j["key"] not in prev for j,_ in completed),
            "pending_never_checked":sum(j["key"] not in current for j in rows),
            "market_counts_this_run":dict(Counter(r["market"] for r in results)),
            "note":"LIVE_FORM = public exact-role form seen, not eligibility, sponsorship, prior-application status or submitted application. Older probes must be rechecked.",
            "jobs":sorted(current.values(),key=lambda j:j["key"])}
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:v for k,v in report.items() if k!="jobs"},indent=2))
    if not selected:
        raise RuntimeError("No eligible public URLs; check source coverage")

class Tests(unittest.TestCase):
    def setUp(self):
        self.url="https://job-boards.greenhouse.io/example/jobs/1234"
        self.id=identity(self.url)
    def test_api_liveness_requires_exact_title_and_role(self):
        row = {"key":"a","title":"AI Engineer","market":"SG","url":self.url}
        listed = {"id":1234,"title":"AI Engineer","absolute_url":self.url}
        self.assertEqual(api_match(row,[listed],"greenhouse")["status"],"API_LISTED")
        self.assertIsNone(api_match(row,[dict(listed,title="Different role")],"greenhouse"))
        self.assertIsNone(api_match(row,[dict(listed,id=4321,absolute_url=self.url.replace("1234","4321"))],"greenhouse"))

    def test_api_does_not_replace_browser_form_evidence(self):
        url = "https://jobs.ashbyhq.com/example/02234e0a-e1fc-4b23-b3e6-513200e4ff80"
        row = {"key":"a","title":"AI Engineer","market":"SG","url":url}
        item = {"title":"AI Engineer","jobUrl":url,"applyUrl":url+"/application","isListed":False}
        match = api_match(row,[item],"ashby")
        self.assertEqual(match["status"],"API_DIRECT_LINK")
        self.assertEqual(match["apply_url"],url+"/application")
        self.assertNotEqual(match["status"],"LIVE_FORM")
        recent = {"url":url,"title":"AI Engineer","status":"LIVE_FORM","checked_at":now()}
        self.assertTrue(recent_form(row,recent,match))
        self.assertFalse(recent_form(row,dict(recent,status="APPLY_CONTROL_ONLY"),match))
        self.assertFalse(recent_form(row,dict(recent,checked_at="2020-01-01T00:00:00+00:00"),match))

    def test_api_board_groups_exact_supported_paths(self):
        self.assertEqual(api_board(self.url),("greenhouse","example"))
        self.assertIsNone(api_board("https://job-boards.greenhouse.io/example"))
        self.assertIsNone(api_board("https://www.liepin.com/job/1982484575.shtml"))

    def test_classification(self):
        c=lambda body="", fields=(), controls=(), url=self.url, code=200, title=True: classify(self.id,url,code,body,title,fields,controls)
        self.assertEqual(c(fields=["email","name","resume"]),"LIVE_FORM")
        self.assertEqual(c(fields=["email","name"]),"JD_ONLY")
        self.assertEqual(c(fields=["email","password","name"]),"AUTH_REQUIRED")
        self.assertEqual(c(controls=["Apply"]),"APPLY_CONTROL_ONLY")
        self.assertEqual(c("This job is no longer available",fields=["email","name"]),"CLOSED_EXPLICIT")
        self.assertEqual(c("Verify you are human",fields=["email","name"]),"BLOCKED")
        self.assertEqual(c(url="https://job-boards.greenhouse.io/example/jobs/4321",fields=["email","name"]),"IDENTITY_UNCONFIRMED")
        self.assertEqual(c(code=404),"NOT_FOUND_HTTP")
        self.assertEqual(c(title=False,fields=["email","name"]),"IDENTITY_UNCONFIRMED")
    def test_identity(self):
        self.assertEqual(identity("https://jobs.ashbyhq.com/example/02234e0a-e1fc-4b23-b3e6-513200e4ff80/application"),("jobs.ashbyhq.com","example/02234e0a-e1fc-4b23-b3e6-513200e4ff80"))
        self.assertEqual(identity("https://example.wd3.myworkdayjobs.com/en-US/Careers/job/Singapore/AI-Engineer_JR123/apply"),("example.wd3.myworkdayjobs.com","jr123"))
        self.assertEqual(identity("https://sg.jobstreet.com/job/1234/apply"),("sg.jobstreet.com","1234"))
        self.assertIsNone(identity("https://job-boards.greenhouse.io/example"))
        self.assertIsNone(identity("https://job-boards.greenhouse.io.evil.example/example/jobs/1234"))
    def test_sharded_jd_and_research_assistant(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jd = root/"feed/ats/jd"
            jd.mkdir(parents=True)
            markets = root/"feed/ats/markets"
            markets.mkdir()
            url = self.url
            role = {"key":"backend", "market":"SG", "title":"Backend Engineer", "url":url}
            ra = {"key":"ra", "market":"SG", "title":"Research Assistant", "url":url.replace("1234","5678")}
            (markets/"SG.json").write_text(json.dumps({"jobs":[role,ra]}))
            (jd/"index.json").write_text(json.dumps({"parts":[{"path":"SG-000.json"}]}))
            (jd/"SG-000.json").write_text(json.dumps({"jobs":[dict(role,description_text="LLM, RAG and retrieval")]}))
            self.assertEqual({j["key"] for j in load_jobs(root)}, {"backend","ra"})

    def test_research_portal_source_is_integrated(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/"feed/sg-research"
            source.mkdir(parents=True)
            url = "https://careers.nus.edu.sg/job/Singapore-Research-Associate/123456/"
            role = {"title":"Research Associate","url":url,"requisition":"123",
                    "job_page_verified":True,"apply_control_seen":True,"technical_signals":["llm"]}
            (source/"current.json").write_text(json.dumps({"sources":[{"source":"NUS Research","jobs":[role]}]}))
            rows = load_jobs(root)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]["url"],url)
            self.assertEqual(rows[0]["market"],"SG")
            self.assertEqual(rows[0]["jd_evidence"],"listing_only")

    def test_my_source_and_budget(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root/"feed/market-api"
            src.mkdir(parents=True)
            url = "https://my.jobstreet.com/job/95373292"
            job = {"key":"my","market":"MY","title":"AI Engineer","url":url}
            (src/"MY.json").write_text(json.dumps({"jobs":[job]}))
            rows = load_jobs(root)
            self.assertEqual([j["key"] for j in rows], ["my"])
            self.assertEqual([j["key"] for j in select(rows,{},10)], ["my"])
            self.assertEqual(identity(url), ("my.jobstreet.com","95373292"))

    def test_fixed_term_research_is_not_dropped(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root/"feed/ats/markets"
            markets.mkdir(parents=True)
            ra = {"key":"ra","market":"SG","title":"Research Assistant (Fixed-term)",
                  "url":self.url,"employment_type":"fixed-term"}
            eng = dict(ra,key="engineer",title="AI Engineer (Fixed-term)",
                       url=self.url.replace("1234","5678"))
            intern = dict(ra,key="intern",title="Research Assistant Internship",
                          url=self.url.replace("1234","9999"))
            (markets/"SG.json").write_text(json.dumps({"jobs":[ra,eng,intern]}))
            self.assertEqual({j["key"] for j in load_jobs(root)}, {"ra"})

    def test_new_non_ats_roles_prioritize_before_old_checks(self):
        rows = [{"key":"old","market":"SG","title":"AI","url":self.url},
                {"key":"new","market":"SG","title":"AI","url":self.url}]
        chosen = select(rows,{"old":{"checked_at":"2026-11-24"}},1)
        self.assertEqual([x["key"] for x in chosen],["new"])

    def test_marketplace_budget_and_new_role_priority(self):
        direct = [{"key":str(i),"market":"SG","title":"AI","url":self.url} for i in range(100)]
        proxy = [{"key":"proxy"+str(i),"market":"SG","title":"AI","url":"https://sg.jobstreet.com/job/1234567"} for i in range(100)]
        picked = select(direct+proxy,{},20,{"99"})
        self.assertEqual(20,len(picked))
        self.assertEqual(3,sum(j["key"].startswith("proxy") for j in picked))
        self.assertIn("99",[j["key"] for j in picked])
        self.assertEqual(3,len(select(proxy,{},20)))

    def test_core_matches_mixed_chinese_english_titles(self):
        for title in ("Agent开发工程师", "LLM研发工程师", "RAG工程师", "智能体开发"):
            self.assertIsNotNone(CORE.search(title), title)
        for title in ("Management", "Reagent Specialist"):
            self.assertIsNone(CORE.search(title), title)

    def test_liepin_source_reuses_exact_url_and_marketplace_budget(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root/"feed/cn-native"
            src.mkdir(parents=True)
            url = "https://www.liepin.com/job/1982484575.shtml"
            role = {"sourceId":"82484575", "title":"AI Agent开发工程师",
                    "company":"Example", "location":"上海", "url":url}
            (src/"liepin-raw.json").write_text(json.dumps({"jobs":[
                role, dict(role, title="AI Agent 实习生", url=url.replace("4575","4576")),
                dict(role, url="https://www.liepin.com/career/1982484575"),
                dict(role, url=url+"?utm_source=test")]}))
            rows = load_jobs(root)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]["market"],"CN")
            self.assertEqual(rows[0]["url"],url)
            self.assertEqual(identity(url),("www.liepin.com","1982484575"))
            self.assertIn("www.liepin.com", MARKETPLACE_HOSTS)

    def test_native_source_keeps_exact_roles_and_verified_jd(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root/"feed/cn-native"
            src.mkdir(parents=True)
            url = "https://01ai.jobs.feishu.cn/index/position/7605812208450734374/detail"
            role = {"post_id":"7605812208450734374", "title":"AI算法工程师（智能体）",
                    "apply_url":url, "work_cities":"北京", "recruit_label":"全职"}
            intern = dict(role, post_id="7605812208450734375",
                          apply_url=url.replace("4374", "4375"), recruit_label="实习")
            mismatched = dict(role, post_id="7605812208450734376")
            group = {"company":"zerooneai", "positions":[role,intern,mismatched]}
            for name in ("agent","llm"):
                (src/f"jobpro-{name}.json").write_text(json.dumps({"results":[group]}))
            detail = {"company_key":"zerooneai", "job_id":role["post_id"], "title":role["title"],
                      "url":url, "full_jd_complete":True, "description_truncated":False,
                      "full_jd_text":"岗位职责：开发智能体。任职要求：Python。", "checked_at":"2026-11-24"}
            (src/"jobpro-jd.json").write_text(json.dumps({"jobs":[detail]}))
            rows = load_jobs(root)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]["market"],"CN")
            self.assertEqual(rows[0]["url"],url)
            self.assertEqual(rows[0]["jd_evidence"],"full_jd")
            self.assertEqual(rows[0]["recruit_label"],"全职")
            self.assertEqual(identity(url),("01ai.jobs.feishu.cn",role["post_id"]))

    def test_native_source_identity_rejects_generic_and_mismatched_routes(self):
        self.assertEqual(identity("https://join.qq.com/post_detail.html?postid=1282707395466077184"),
                         ("join.qq.com","1282707395466077184"))
        self.assertEqual(identity("https://jobs.bytedance.com/campus/position/7669725958044518661/detail"),
                         ("jobs.bytedance.com","7669725958044518661"))
        self.assertEqual(identity("https://campus-talent.alibaba.com/campus/position/199907640058"),
                         ("campus-talent.alibaba.com","199907640058"))
        self.assertIsNone(identity("https://join.qq.com/post_detail.html"))
        self.assertIsNone(identity("https://01ai.jobs.feishu.cn/index/position/123/detail"))
        self.assertIsNone(identity("https://evil.jobs.feishu.cn/index/position/7605812208450734374/detail"))

    def test_rotation(self):
        rows=[{"key":str(i),"market":"SG","title":"AI"} for i in range(5)]+[{"key":"cn","market":"CN","title":"AI"}]
        chosen=select(rows,{"0":{"checked_at":"2026-11-24"}},3)
        self.assertEqual(len(chosen),3)
        self.assertIn("cn",[x["key"] for x in chosen])
        self.assertNotIn("0",[x["key"] for x in chosen])


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_form_and_expired_fixture(self):
        from playwright.async_api import async_playwright
        url = "https://job-boards.greenhouse.io/example/jobs/1234"
        job = {"key":"fixture", "market":"SG","title":"AI Engineer","url":url}
        async with async_playwright() as p:
            kwargs = {"headless":True}
            if os.getenv("CHROMIUM_EXECUTABLE"):
                kwargs["executable_path"] = os.environ["CHROMIUM_EXECUTABLE"]
            browser = await p.chromium.launch(**kwargs)
            page = await browser.new_page()
            html = ["<h1>AI Engineer</h1><form><input name='first_name'><input type='email'><input type='file' name='resume'><button>Submit application</button></form>",
                    "<h1>AI Engineer</h1><form><input name='first_name'><input type='email'><button>Subscribe</button></form>",
                    "<h1>This job is no longer available</h1>"]
            async def mock(route):
                await route.fulfill(status=200, content_type="text/html", body=html[0])
            await page.route("**/*", mock)
            for expected in ("LIVE_FORM","JD_ONLY","CLOSED_EXPLICIT"):
                result, _ = await observe(page,job,identity(url),url)
                self.assertEqual(result["status"],expected)
                html.pop(0)
            await browser.close()

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,default=ROOT)
    parser.add_argument("--limit",type=int,default=100)
    parser.add_argument("--workers",type=int,default=10)
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        unittest.main(argv=[__file__])
    else:
        if args.limit<1 or not 1<=args.workers<=16:
            parser.error("positive limit, workers 1-16")
        asyncio.run(run(args.root,args.limit,args.workers))
