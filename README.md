# freehirefetch

Small public-data worker for FreeHire SG/CN job discovery.

It deliberately contains **no personal job-search data**. It fetches FreeHire's public API, validates pagination/filter behavior, applies only conservative title-level hard drops, exact-deduplicates unchanged jobs, and publishes a bounded `NEW`/`CHANGED` event feed.

## Run

```bash
python freehire_fetch.py --mode bootstrap
python freehire_fetch.py --mode delta
python freehire_fetch.py --mode full
```

- `bootstrap`: max-page SG + CN scan; seeds all fetched identities, but emits initial `NEW` events only for jobs FreeHire first saw within 7 days.
- `delta`: hourly path using `open_within_days=2` overlap.
- `full`: max-page daily backstop/state refresh.

FreeHire's public search window is capped at 10,000 rows per market, 100 rows per request.

## Public state

- `feed/events.jsonl`: 30-day rolling `NEW`/`CHANGED` event feed with monotonic `seq`.
- `state/seen.json`: exact machine-dedupe state, bounded by current/recent identities.
- `health.json`: latest successful run metadata including `first_seq` / `last_seq`.

FreeHire enrichment (seniority, experience, employer type, visa hints) is **not employer truth**. It can add flags, but only explicit title-level mismatches such as Senior/Staff/Lead/Manager/Intern are hard-dropped here. Private verification happens elsewhere.

## Test

```bash
python -m unittest discover -s tests -v
python -m py_compile freehire_fetch.py
```

No paid API, browser automation, private cookies, or required secret.
