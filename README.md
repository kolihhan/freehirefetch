# freehirefetch

Public-data firehose for broad SG/CN/MY tech-job discovery from FreeHire.

It deliberately contains **no personal job-search data**. It fetches FreeHire's public API, validates pagination/filter behavior, applies only conservative title-level hard drops, exact-deduplicates unchanged jobs, and publishes a bounded `NEW`/`CHANGED` event feed.

## Run

Use the firehose entrypoint for normal discovery:

```bash
python firehose_fetch.py --mode bootstrap
python firehose_fetch.py --mode delta
python firehose_fetch.py --mode full
```

`firehose_fetch.py` reuses the tested `freehire_fetch.py` worker while widening its search scope to broad early-career tech categories: generic software engineering, backend, frontend, fullstack, mobile, data engineering/science/analytics, ML/AI, QA, security, solutions engineering, developer relations, technical writing, DevOps, SRE, and network engineering.

- `bootstrap`: max-page SG + CN + MY scan; seeds fetched identities and emits initial `NEW` events for jobs FreeHire first saw within 30 days under the firehose scope.
- `delta`: hourly path using `open_within_days=2` overlap.
- `full`: max-page daily backstop/state refresh; newly discovered broad-scope jobs still use the 30-day initial-event window.

FreeHire's public search window is capped at 10,000 rows per market, 100 rows per request. The feed therefore prioritizes the newest matching jobs rather than claiming exhaustive historical coverage.

## Automation

GitHub Actions runs on the repository's public standard runner:

- hourly delta at minute `17`;
- daily full backstop at `18:43 UTC`;
- manual `workflow_dispatch` for bootstrap/delta/full probes.

The worker needs no API key or paid service. It commits only changed public state (`feed/`, `state/`, `health.json`).

## Public state

- `feed/events.jsonl`: 30-day rolling `NEW`/`CHANGED` event feed with monotonic `seq`.
- New events also retain sentence-level `visa_signal` (`positive`/`negative`/`ambiguous`/`none`) and `visa_evidence` extracted from FreeHire's public JD snippet; absence of a signal is not proof that the full employer JD says nothing about sponsorship.
- `state/seen.json`: exact machine-dedupe state, bounded by current/recent identities.
- `health.json`: latest successful run metadata including `first_seq` / `last_seq`.

FreeHire enrichment (seniority, experience, employer type, visa hints) is **not employer truth**. It can add flags, but only explicit title-level mismatches such as Senior/Staff/Lead/Manager/Intern are hard-dropped here. Private verification happens elsewhere.

## Test

```bash
python -m unittest discover -s tests -v
python -m py_compile freehire_fetch.py firehose_fetch.py
```

No paid API, browser automation, private cookies, or required secret.
