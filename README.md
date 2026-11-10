# freehirefetch

Public-data firehose for broad SG/CN/MY engineering-job discovery from FreeHire.

It deliberately contains **no personal job-search data**. It fetches FreeHire's public API, validates pagination/filter behavior, applies only conservative title-level hard drops, exact-deduplicates unchanged jobs, and publishes machine-readable discovery feeds.

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
- `full`: max-page daily backstop/state refresh; newly discovered broad-scope jobs still use the 30-day initial-event window. A full run also refreshes `feed/coldstart.json` from the complete jobs/JD text seen in that scan.

FreeHire's public search window is capped at 10,000 rows **per query window**, 100 rows per request. Sharding improves Singapore coverage but still does not imply exhaustive market coverage.

## Public ATS discovery (browserless)

Separate from FreeHire, `ats_discovery.py` scans a **configured set of first-party employer ATS boards**, using public HTTP JSON endpoints only: **Ashby, Greenhouse, Lever, SmartRecruiters, and Workday CXS**. No Playwright, browser cookies, login, API key or candidate data.

- Config: `ats_boards.json` (SG/MY/CN official career-board owners).
- GitHub Actions: `.github/workflows/ats-discovery.yml` (every four hours and on relevant code/config pushes).
- Live public machine artifacts: `feed/ats/current.json` (snapshot), `feed/ats/changes.json` (ephemeral latest-run delta), `feed/ats/health.json` (per-board complete/error status).
- **Always consume `current.json` for review recovery.** `changes.json` is overwritten and is not a lossless downstream event journal.
- Workday boards with a global vacancy count over the public search-window cap can use **explicit keyword windows**. Their `scope: targeted_keywords` status is not a claim of full company coverage. A failed board preserves its previous candidates rather than declaring them closed.
- Public candidate count is not eligibility. An ATS listing still requires the **full exact JD, liveness, hard qualifications, open/closed GitHub Issue history, Gmail application dedupe, and true apply route** before promotion into the private `kolihhan/job-resources` APPLY/CHECK queue.
- The private queue and applications remain entirely in `kolihhan/job-resources`; this public repo never stores user data, applicant outcomes, or submitted application state.

Offline tests: `python -m unittest -v test_ats_discovery`. New boards should use verified official board URLs and have their source/geography and paging checked. In particular, a board with many irrelevant AI-branded but generic roles is *not* high eligible-role yield.

## Public batch ownership (2026-11-10)

All **public, profile-agnostic source batches** run here, not in `job-resources`.

- `ats_discovery.py` pulls employer-controlled ATS boards and publishes `feed/ats/markets/{SG,MY,CN}.json` for exact IDs. Full employer-published JDs stay in `feed/ats/jd/{market}-{shard}.json`; `feed/ats/jd/index.json` **v2** maps exact canonical job URL and title to its shard and last successful source check time.
- `market_api_collect.py` uses the public FreeHire/AI Dev Jobs APIs to produce `feed/market-api/{SG,MY,CN}.json`, `health.json` and `platform-coverage.md`. API aliases are not native-board scans. When an entire market's API sources fail, keep the last usable public snapshot and report the outage explicitly.
- The scheduled `.github/workflows/ats-discovery.yml` owns both public collection paths. Source identity, JD text, freshness, provider failures and generic technical title signals are public **evidence**, never applicant fit, eligibility, Gmail dedupe, APPLY/CHECK or permission to contact an employer.
- `kolihhan/job-resources` consumes these **already-published** artifacts. It does not repeat ATS/API batch collection; the user's private matching rules, lifecycle, evidence decisions, application and all outbound communication belong exclusively there. A full JD here is never proof an application is already submitted.

## Candidate feeds

### Incremental feed

Every firehose run writes `feed/candidates.json`: a **derived machine triage artifact**, not a second human tracker.

The snapshot contains only AI/ML/research jobs that emitted a `NEW` or `CHANGED` event in that exact ingestion run. Unchanged jobs are not repeated on every hourly scan. Each candidate carries its event `kind` and monotonic `seq`, so downstream review can process only fresh work.

### Cold-start feed

Every `full` scan also writes `feed/coldstart.json`. Unlike the incremental feed, it is built from **all current jobs captured by the full API scan**, including unchanged jobs. It exists so downstream private consumers can perform a one-time/history-aware cold start without asking an LLM to replay the compact event log one sequence at a time.

The cold-start feed deliberately does **not** contain personal application history and does not decide whether a candidate has already been reviewed. That private dedupe belongs downstream. `feed/events.jsonl` remains the audit/recovery event log; it is not the preferred normal review queue.

Material AI relevance in both candidate feeds is scored from title, FreeHire category and public JD text. Strong AI titles can pass directly; generic SWE/backend/full-stack titles only pass when the JD contains several concrete AI signals such as LLMs, agents, RAG, retrieval, model training or evaluation. A single casual AI mention is intentionally not enough.

The candidate feeds are **not capped per market**. Explicit non-permanent ordinary engineering roles are still removed, but Research Assistant / Research Associate / Research Officer / Research Engineer / Research Scientist-style roles are preserved for downstream research-exception review instead of being machine-dropped. The feeds contain compact AI-relevance signals plus a short JD excerpt and exclude the worker's existing title hard-drops. They do **not** decide APPLY/CHECK/SKIP, do not perform Gmail/GitHub dedupe, and do not create Issues or submit applications.

## Automation

GitHub Actions runs on the repository's public standard runner:

- hourly delta at minute `17`;
- daily full backstop at `18:43 UTC`;
- manual `workflow_dispatch` for bootstrap/delta/full probes;
- a separate `FreeHire Cold Start` workflow can run an explicit full-scan refresh without changing the trigger contract of the normal ingestion workflow.

The worker needs no API key or paid service. It commits only changed public state (`feed/`, `state/`, `health.json`).

## Public state

- `feed/events.jsonl`: 30-day rolling `NEW`/`CHANGED` event feed with monotonic `seq`.
- `feed/candidates.json`: latest-run incremental AI/ML/research review candidates only.
- `feed/coldstart.json`: latest full-scan set of current plausible AI/ML/research candidates for downstream cold-start dedupe/review.
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
