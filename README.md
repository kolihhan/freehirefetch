# freehirefetch

Public-data firehose for broad SG/CN/MY engineering-job discovery from FreeHire.

It deliberately contains **no personal job-search data**. It fetches FreeHire's public API, validates pagination/filter behavior, applies only conservative title-level hard drops, exact-deduplicates unchanged jobs, and publishes a bounded `NEW`/`CHANGED` event feed.

## Run

Use the firehose entrypoint for normal discovery:

```bash
python firehose_fetch.py --mode bootstrap
python firehose_fetch.py --mode delta
python firehose_fetch.py --mode full
```

`firehose_fetch.py` reuses the tested `freehire_fetch.py` worker while widening its search scope to broad early-career engineering categories: generic software engineering, backend, frontend, fullstack, mobile, data engineering/science/analytics, ML/AI, QA, security, solutions engineering, DevOps, SRE, and network engineering. Developer-relations and technical-writing categories are intentionally excluded so they do not consume engineering search capacity.

Singapore is split into four category windows so one 10,000-row API window cannot crowd out other engineering lanes:

1. SWE — software engineering / backend / frontend / fullstack / mobile;
2. AI + data — data engineering/science/analytics / ML / AI engineering;
3. QA — QA/test roles;
4. infra — security / solutions engineering / DevOps / SRE / network engineering.

Each SG shard may scan up to FreeHire's 10,000-row window. Results are unioned and exact-deduplicated by job identity before event classification. CN and MY continue to use one broad engineering window each.

- `bootstrap`: max-page SG + CN + MY scan; seeds fetched identities and emits initial `NEW` events for jobs FreeHire first saw within 30 days under the firehose scope.
- `delta`: hourly path using `open_within_days=2` overlap.
- `full`: max-page daily backstop/state refresh; newly discovered broad-scope jobs still use the 30-day initial-event window.

FreeHire's public search window is capped at 10,000 rows **per query window**, 100 rows per request. Sharding improves Singapore coverage but still does not imply exhaustive market coverage.

## AI candidate snapshot

Every firehose run also writes `feed/candidates.json`: a **derived machine triage artifact**, not a second human tracker.

It scores the jobs fetched in that run for material AI/ML/research relevance using title, FreeHire category and public JD text. Strong AI titles can pass directly; generic SWE/backend/full-stack titles only pass when the JD contains several concrete AI signals such as LLMs, agents, RAG, retrieval, model training or evaluation. A single casual AI mention is intentionally not enough.

The snapshot is bounded to at most **30 candidates per market** (90 total), contains compact AI-relevance signals plus a short JD excerpt, and excludes the worker's existing title hard-drops. Its purpose is to reduce downstream review from thousands of raw rows to tens of plausible AI candidates. It does **not** decide APPLY/CHECK/SKIP, does not perform Gmail/GitHub dedupe, and does not create Issues or submit applications.

## Automation

GitHub Actions runs on the repository's public standard runner:

- hourly delta at minute `17`;
- daily full backstop at `18:43 UTC`;
- manual `workflow_dispatch` for bootstrap/delta/full probes.

The worker needs no API key or paid service. It commits only changed public state (`feed/`, `state/`, `health.json`).

## Public state

- `feed/events.jsonl`: 30-day rolling `NEW`/`CHANGED` event feed with monotonic `seq`.
- `feed/candidates.json`: bounded current-run AI/ML/research candidate snapshot for fast downstream triage.
- New events also retain sentence-level `visa_signal` (`positive`/`negative`/`ambiguous`/`none`) and `visa_evidence` extracted from FreeHire's public JD snippet; absence of a signal is not proof that the full employer JD says nothing about sponsorship.
- `state/seen.json`: exact machine-dedupe state, bounded by current/recent identities.
- `health.json`: latest successful run metadata including `first_seq` / `last_seq`.

FreeHire enrichment (seniority, experience, employer type, visa hints) is **not employer truth**. It can add flags. Clear mature titles such as Staff/Principal/Lead/Manager/Director and internships remain title-level hard drops. A `Senior` title alone is now a `senior_title_hint`, not a source-level rejection, so downstream JD review can decide whether the actual experience/ownership requirements are viable.

## Test

```bash
python -m unittest discover -s tests -v
python -m py_compile freehire_fetch.py firehose_fetch.py candidate_snapshot.py
```

No paid API, browser automation, private cookies, or required secret.
