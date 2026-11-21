"""One-off public JobSpy SG/MY source probe; never modifies the existing feeds."""
from __future__ import annotations

import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from jobspy import scrape_jobs

SEARCHES = (
    ("SG", "Singapore", "Singapore", "LLM Engineer"),
    ("SG", "Singapore", "Singapore", "AI Engineer"),
    ("SG", "Singapore", "Singapore", "Research Engineer"),
    ("MY", "Malaysia", "Kuala Lumpur", "LLM Engineer"),
    ("MY", "Malaysia", "Kuala Lumpur", "AI Engineer"),
    ("MY", "Malaysia", "Kuala Lumpur", "Machine Learning Engineer"),
)
SITES = ("linkedin", "seek")  # SEEK uses SG/MY JobStreet via country_indeed.
FIELDS = ("market", "source", "job_id", "company", "title", "location", "job_url", "date_posted")
OUT = Path("jobspy-probe-output")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    rows = {}
    trials = []
    for index, (market, country, location, query) in enumerate(SEARCHES):
        if index:
            time.sleep(4)
        item = {"market": market, "country": country, "query": query, "location": location,
                "counts": {site: 0 for site in SITES}, "errors": {}, "warnings": {}}
        try:
            result = scrape_jobs(
                site_name=list(SITES),
                search_term=query,
                location=location,
                country_indeed=country,
                results_wanted=15,
                hours_old=168,
                fetch_description=False,
                verbose=1,
            )
            item["errors"] = {str(k): str(v) for k, v in result.attrs.get("errors", {}).items()}
            item["warnings"] = {str(k): str(v) for k, v in result.attrs.get("warnings", {}).items()}
            for job in result.to_dict("records"):
                site = str(job.get("site") or "")
                item["counts"][site] = item["counts"].get(site, 0) + 1
                job_id = str(job.get("id") or "").strip()
                url = str(job.get("job_url") or "").strip()
                if not job_id or not url:
                    continue
                key = (market, site, job_id)
                rows.setdefault(key, {
                    "market": market, "source": site, "job_id": job_id,
                    "company": str(job.get("company") or ""),
                    "title": str(job.get("title") or ""),
                    "location": str(job.get("location") or ""),
                    "job_url": url, "date_posted": str(job.get("date_posted") or ""),
                })
        except Exception as exc:
            item["errors"]["execution"] = f"{type(exc).__name__}: {exc}"
        trials.append(item)
        print(f'{market} {query}: {item["counts"]}, errors={item["errors"]}', flush=True)

    with (OUT / "jobs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows.values())

    blocked = sum(bool(x["errors"]) for x in trials)
    state = "HAS_ROWS" if rows else ("BLOCKED" if blocked else "EMPTY_UNVERIFIED")
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": state,
        "market_source_job_ids": len(rows),
        "sample_public_roles": list(rows.values())[:15],
        "queries": trials,
        "scope": "bounded LinkedIn + JobStreet JobSpy probe, NOT complete native-platform coverage",
        "limitations": "No employer-JD/liveness/eligibility/application-history verification; no candidate data",
    }
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"RESULT: {state}, unique market-source-job IDs={len(rows)}", flush=True)


if __name__ == "__main__":
    main()
