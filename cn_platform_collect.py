#!/usr/bin/env python3
"""Bounded, read-only native public job discovery. No login, CAPTCHA bypass or submission."""
import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlencode, urlparse

from application_probe import identity, CORE, HARD_TITLE, excluded_contract, BLOCKED, now

SOURCES = {
    "BOSS": ("zhipin.com", "https://www.zhipin.com/web/geek/job?", "page", {"query":"大模型","city":"101280600"}),
    "Nowcoder": ("nowcoder.com", "https://www.nowcoder.com/jobs?", "page", {"keyword":"大模型"}),
    "Zhaopin": ("zhaopin.com", "https://sou.zhaopin.com/?", "page", {"kw":"大模型"}),
    "51job": ("51job.com", "https://we.51job.com/pc/search?", "pageNum", {"keyword":"大模型"}),
}
CHALLENGE = re.compile(r"安全验证|请完成验证|访问受限|请求过于频繁|人机验证")

def source_host(url, domain):
    try:
        p = urlparse(url)
        return p.scheme=="https" and not p.username and not p.password and p.port in (None,443) and (p.hostname==domain or (p.hostname or "").endswith("."+domain))
    except ValueError:
        return False

def extract(links, domain):
    found = {}
    for link in links:
        url = str(link.get("url",""))
        title = " ".join(str(link.get("title","")).split())
        if not source_host(url,domain):
            continue
        ident = identity(url)
        if not ident or not (ident[0]==domain or ident[0].endswith("."+domain)):
            continue
        if not (5 <= len(title) <= 160 and CORE.search(title)) or HARD_TITLE.search(title) or excluded_contract(title):
            continue
        if re.search(r"产品经理|销售|运营|设计师|客户成功",title):
            continue
        canonical = urlparse(url)._replace(query="",fragment="").geturl()
        found[ident] = {"url":canonical,"title":title,"discovery_freshness":"OBSERVED_THIS_RUN"}
    return found

async def collect_source(browser, source, spec):
    domain, base, page_key, params = spec
    report = {"source":source,"query":params.get("query") or params.get("keyword") or params.get("kw"),"pages":[],"jobs":[]}
    context = await browser.new_context(accept_downloads=False)
    page = await context.new_page()
    async def guard(route):
        req = route.request
        if req.is_navigation_request() and req.frame==page.main_frame and not source_host(req.url,domain):
            await route.abort()
        else:
            await route.continue_()
    await page.route("**/*",guard)
    seen = {}
    try:
        for n in (1,2):
            url = base+urlencode(dict(params,**{page_key:n}))
            item = {"page":n,"url":url,"status":"UNKNOWN"}
            try:
                response = await page.goto(url,wait_until="domcontentloaded",timeout=12000)
                code = response.status if response else None
                item["http_status"] = code
                if code in (401,403,429) or not source_host(page.url,domain):
                    item["status"] = "BLOCKED_OR_REDIRECT"
                    report["pages"].append(item)
                    break
                if code is None or code >= 400:
                    item["status"] = "HTTP_ERROR"
                    report["pages"].append(item)
                    break
                try:
                    await page.locator("a[href*='job_detail/'], a[href*='/jobs/detail/'], a[href*='/jobdetail/'], a[href*='jobs.51job.com/']").first.wait_for(timeout=5000)
                except Exception:
                    pass
                body = (await page.locator("body").inner_text(timeout=3500))[:12000]
                if CHALLENGE.search(body[:3000]) or BLOCKED.search(body[:3000]):
                    item["status"] = "CHALLENGE"
                    report["pages"].append(item)
                    break
                links = await page.locator("a[href]").evaluate_all("""els => els.filter(e=>e.getClientRects().length).map(e=>({url:e.href,title:e.innerText.trim()}))""")
                rows = extract(links,domain)
                item["role_links"] = len(rows)
                item["new_links"] = len(rows.keys()-seen.keys())
                item["status"] = "ROLE_LINKS_ONLY" if rows else "NO_EXACT_ROLE_LINKS"
                seen.update(rows)
                report["pages"].append(item)
                if not rows or (n==2 and not item["new_links"]):
                    break
                await asyncio.sleep(1)
            except Exception as exc:
                item["status"] = "ERROR"
                item["error"] = type(exc).__name__
                report["pages"].append(item)
                break
    finally:
        await context.close()
    report["jobs"] = list(seen.values())
    report["unique_observed"] = len(seen)
    report["coverage"] = "BOUNDED_DISTINCT_ROLE_LINKS" if len(report["pages"])==2 and report["pages"][1].get("new_links",0)>0 else "NATIVE_COVERAGE_UNPROVEN"
    return report

async def main():
    from playwright.async_api import async_playwright
    out = Path("feed/cn-native/platform-public.json")
    prior = json.loads(out.read_text()) if out.exists() else {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            reports = await asyncio.gather(*(collect_source(browser,k,v) for k,v in SOURCES.items()))
        finally:
            await browser.close()
    previous = {r["source"]:r for r in prior.get("sources",[])}
    for report in reports:
        fresh = {identity(j["url"]):j for j in report["jobs"]}
        for old in previous.get(report["source"],{}).get("jobs",[]):
            if identity(old["url"]) not in fresh:
                fresh[identity(old["url"])] = dict(old,discovery_freshness="RETAINED_UNVERIFIED")
        report["jobs"] = list(fresh.values())
        print(json.dumps({k:v for k,v in report.items() if k!="jobs"},ensure_ascii=False))
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({"run_at":now(),"sources":reports,"note":"Public native source leads, not verified JD, application eligibility, or market coverage."},ensure_ascii=False,indent=2)+"\n")

if __name__=="__main__":
    asyncio.run(main())
