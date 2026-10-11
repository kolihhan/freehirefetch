import freehire_fetch as f

for market in ("SG", "CN"):
    jobs = f.fetch_market(f.http_fetch, market, "delta")
    with_description = [j for j in jobs if str(j.get("description") or "").strip()]
    with_visa_enrichment = [
        j for j in jobs
        if isinstance(j.get("enrichment"), dict)
        and any(k in j["enrichment"] for k in ("visa_sponsorship", "work_authorization", "sponsorship"))
    ]
    print(
        f"PROBE {market}: total={len(jobs)} "
        f"description_nonempty={len(with_description)} "
        f"visa_enrichment={len(with_visa_enrichment)}"
    )
    if jobs:
        print(f"PROBE {market}: sample_keys={sorted(jobs[0].keys())}")
    if with_description:
        lengths = [len(str(j.get("description") or "")) for j in with_description]
        print(f"PROBE {market}: description_len_min={min(lengths)} max={max(lengths)}")
