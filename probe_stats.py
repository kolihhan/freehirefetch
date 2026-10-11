import re
import freehire_fetch as f

BROAD = re.compile(
    r"visa|sponsor|work authorization|work permit|employment pass|s\s*pass|签证|工作许可|工作许可证",
    re.IGNORECASE,
)

for market in ("SG", "CN"):
    jobs = f.fetch_market(f.http_fetch, market, "delta")
    with_description = [j for j in jobs if str(j.get("description") or "").strip()]
    broad = [j for j in jobs if BROAD.search(str(j.get("description") or ""))]
    with_visa_enrichment = [
        j for j in jobs
        if isinstance(j.get("enrichment"), dict)
        and any(k in j["enrichment"] for k in ("visa_sponsorship", "work_authorization", "sponsorship"))
    ]
    print(
        f"PROBE {market}: total={len(jobs)} "
        f"description_nonempty={len(with_description)} "
        f"broad_visa_terms={len(broad)} "
        f"visa_enrichment={len(with_visa_enrichment)}"
    )
    if with_description:
        lengths = [len(str(j.get("description") or "")) for j in with_description]
        print(f"PROBE {market}: description_len_min={min(lengths)} max={max(lengths)}")
    for job in broad:
        signal, evidence = f.visa_evidence(job.get("description"))
        print(
            "PROBE BROAD:",
            market,
            repr(job.get("company")),
            repr(job.get("title")),
            f"signal={signal}",
            f"evidence={evidence}",
        )
    for job in with_visa_enrichment:
        enrichment = job["enrichment"]
        values = {k: enrichment.get(k) for k in ("visa_sponsorship", "work_authorization", "sponsorship") if k in enrichment}
        print(
            "PROBE ENRICHMENT:",
            market,
            repr(job.get("company")),
            repr(job.get("title")),
            repr(values),
        )
