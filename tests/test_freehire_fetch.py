import importlib.util
from pathlib import Path
import unittest
import json
import tempfile
from datetime import datetime, timezone

SCRIPT = Path(__file__).parents[1] / "freehire_fetch.py"
spec = importlib.util.spec_from_file_location("freehire_fetch", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class FreeHireWorkerTests(unittest.TestCase):
    def test_page_offsets_cover_10000_rows_exactly(self):
        offsets = mod.page_offsets()
        self.assertEqual(len(offsets), 100)
        self.assertEqual(offsets[0], 0)
        self.assertEqual(offsets[-1], 9900)

    def test_fetch_stops_when_reported_total_is_exhausted(self):
        calls = []
        def fake_fetch(params):
            calls.append(dict(params))
            if params["offset"] == 0:
                return {"data": [{"public_slug": "a"}, {"public_slug": "b"}], "meta": {"total": 3, "limit": 2, "offset": 0}}
            return {"data": [{"public_slug": "c"}], "meta": {"total": 3, "limit": 2, "offset": 2}}
        jobs = mod.fetch_market(fake_fetch, country="SG", mode="full", page_size=2)
        self.assertEqual([j["public_slug"] for j in jobs], ["a", "b", "c"])
        self.assertEqual([c["offset"] for c in calls], [0, 2])

    def test_fetch_fails_when_requested_filter_is_ignored(self):
        def fake_fetch(params):
            return {"data": [], "meta": {"total": 0, "limit": 100, "offset": 0, "ignored_params": ["countries"]}}
        with self.assertRaisesRegex(RuntimeError, "ignored"):
            mod.fetch_market(fake_fetch, country="CN", mode="delta")

    def test_delta_params_use_open_within_days_2(self):
        params = mod.build_params("CN", "delta", 0)
        self.assertEqual(params["limit"], 100)
        self.assertEqual(params["offset"], 0)
        self.assertEqual(params["open_within_days"], 2)
        self.assertEqual(params["countries"], "CN")

    def test_title_hard_drop_rejects_explicit_senior_and_intern(self):
        senior_drop, senior_flags = mod.machine_flags({"title": "Senior AI Engineer", "enrichment": {}})
        intern_drop, intern_flags = mod.machine_flags({"title": "Software Engineer Intern", "enrichment": {}})
        self.assertTrue(senior_drop)
        self.assertTrue(intern_drop)
        self.assertIn("title_hard_drop", senior_flags)
        self.assertIn("title_hard_drop", intern_flags)

    def test_enrichment_5_years_becomes_flag_not_reject(self):
        hard_drop, flags = mod.machine_flags({"title": "AI Engineer", "enrichment": {"experience_years_min": 5, "seniority": "senior", "company_type": "outstaff"}})
        self.assertFalse(hard_drop)
        self.assertIn("experience_5_plus_hint", flags)
        self.assertIn("seniority_hint", flags)
        self.assertIn("agency_or_outstaff_hint", flags)

    def test_same_identity_same_fingerprint_emits_nothing(self):
        job = {"public_slug": "abc", "title": "AI Engineer", "company_name": "Acme", "location": "Singapore"}
        seen = {"abc": {"fingerprint": mod.content_fingerprint(job), "last_seen": "2026-10-08T00:00:00Z"}}
        events, next_seen = mod.classify_events([job], seen, "2026-10-09T00:00:00Z", bootstrap=False)
        self.assertEqual(events, [])
        self.assertEqual(next_seen["abc"]["fingerprint"], seen["abc"]["fingerprint"])

    def test_same_identity_changed_fingerprint_emits_changed(self):
        old = {"public_slug": "abc", "title": "AI Engineer", "company_name": "Acme", "location": "Singapore"}
        changed = dict(old, title="AI Application Engineer")
        seen = {"abc": {"fingerprint": mod.content_fingerprint(old), "last_seen": "2026-10-08T00:00:00Z"}}
        events, next_seen = mod.classify_events([changed], seen, "2026-10-09T00:00:00Z", bootstrap=False)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "CHANGED")
        self.assertEqual(events[0]["identity"], "abc")
        self.assertEqual(next_seen["abc"]["fingerprint"], mod.content_fingerprint(changed))

    def test_unseen_identity_emits_new(self):
        job = {"public_slug": "abc", "title": "AI Engineer", "company_name": "Acme", "location": "Singapore"}
        events, next_seen = mod.classify_events([job], {}, "2026-10-09T00:00:00Z", bootstrap=False)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "NEW")
        self.assertEqual(events[0]["identity"], "abc")
        self.assertIn("abc", next_seen)

    def test_bootstrap_old_rows_seed_seen_without_emitting_event(self):
        old = {"public_slug": "old", "title": "AI Engineer", "company_name": "OldCo", "created_at": "2026-09-01T00:00:00Z"}
        recent = {"public_slug": "recent", "title": "Backend Engineer", "company_name": "NewCo", "created_at": "2026-10-08T00:00:00Z"}
        events, seen = mod.classify_events([old, recent], {}, "2026-10-09T00:00:00Z", bootstrap=True)
        self.assertEqual([e["identity"] for e in events], ["recent"])
        self.assertIn("old", seen)
        self.assertIn("recent", seen)

    def test_events_retention_is_30_days_without_renumbering(self):
        events = [{"seq": 4, "detected_at": "2026-08-01T00:00:00Z"}, {"seq": 9, "detected_at": "2026-09-20T00:00:00Z"}, {"seq": 15, "detected_at": "2026-10-08T00:00:00Z"}]
        seen, kept = mod.apply_retention({}, events, datetime(2026, 10, 9, tzinfo=timezone.utc), current_identities=set())
        self.assertEqual([e["seq"] for e in kept], [9, 15])

    def test_seen_retention_keeps_current_or_recent_only(self):
        seen = {"current-old": {"last_seen": "2026-08-01T00:00:00Z"}, "recent": {"last_seen": "2026-10-01T00:00:00Z"}, "stale": {"last_seen": "2026-08-01T00:00:00Z"}}
        kept_seen, _ = mod.apply_retention(seen, [], datetime(2026, 10, 9, tzinfo=timezone.utc), current_identities={"current-old"})
        self.assertEqual(set(kept_seen), {"current-old", "recent"})

    def test_failed_market_fetch_does_not_replace_state_or_feed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "state").mkdir(); (root / "feed").mkdir()
            (root / "state" / "seen.json").write_text('{"keep":{"fingerprint":"x"}}\n')
            (root / "feed" / "events.jsonl").write_text('{"seq":7,"kind":"NEW"}\n')
            (root / "health.json").write_text('{"last_seq":7}\n')
            def fake_fetch(params):
                if params["countries"] == "CN": raise RuntimeError("CN failed")
                return {"data": [], "meta": {"total": 0, "limit": 100, "offset": 0}}
            with self.assertRaisesRegex(RuntimeError, "CN failed"):
                mod.run("delta", root, fake_fetch, now=datetime(2026, 10, 9, tzinfo=timezone.utc))
            self.assertEqual(json.loads((root / "state" / "seen.json").read_text()), {"keep": {"fingerprint": "x"}})
            self.assertEqual((root / "feed" / "events.jsonl").read_text(), '{"seq":7,"kind":"NEW"}\n')
            self.assertEqual(json.loads((root / "health.json").read_text()), {"last_seq": 7})

    def test_health_exposes_first_seq_last_seq_and_counts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            jobs = {"SG": [{"public_slug": "sg1", "title": "AI Engineer", "company_name": "A", "created_at": "2026-10-09T00:00:00Z"}], "CN": [{"public_slug": "cn1", "title": "Backend Engineer", "company_name": "B", "created_at": "2026-10-09T00:00:00Z"}]}
            def fake_fetch(params):
                country = params["countries"]; return {"data": jobs[country], "meta": {"total": 1, "limit": 100, "offset": 0}}
            health = mod.run("bootstrap", root, fake_fetch, now=datetime(2026, 10, 9, tzinfo=timezone.utc))
            self.assertEqual(health["first_seq"], 1); self.assertEqual(health["last_seq"], 2)
            self.assertEqual(health["markets"]["SG"]["fetched"], 1); self.assertEqual(health["markets"]["CN"]["fetched"], 1)
            self.assertEqual(health["new"], 2)

    def test_http_fetch_retries_twice_then_succeeds(self):
        attempts = {"count": 0}; original_urlopen = mod.urlopen; original_sleep = mod.time.sleep
        class FakeResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"data":[],"meta":{}}'
        def flaky_urlopen(request, timeout=30):
            attempts["count"] += 1
            if attempts["count"] < 3: raise OSError("temporary")
            return FakeResponse()
        try:
            mod.urlopen = flaky_urlopen; mod.time.sleep = lambda _: None
            payload = mod.http_fetch({"countries": "SG"}, retries=2)
        finally:
            mod.urlopen = original_urlopen; mod.time.sleep = original_sleep
        self.assertEqual(attempts["count"], 3); self.assertEqual(payload, {"data": [], "meta": {}})

    def test_new_sequence_continues_after_retained_gap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "state").mkdir(); (root / "feed").mkdir()
            (root / "state" / "seen.json").write_text('{}\n')
            (root / "feed" / "events.jsonl").write_text('{"seq":50,"kind":"NEW","detected_at":"2026-10-08T00:00:00Z"}\n')
            (root / "health.json").write_text('{"last_seq":50}\n')
            def fake_fetch(params):
                data = [{"public_slug": "sg-new", "title": "AI Engineer", "created_at": "2026-10-09T00:00:00Z"}] if params["countries"] == "SG" else []
                return {"data": data, "meta": {"total": len(data), "limit": 100, "offset": 0}}
            health = mod.run("delta", root, fake_fetch, now=datetime(2026, 10, 9, tzinfo=timezone.utc))
            lines = [json.loads(line) for line in (root / "feed" / "events.jsonl").read_text().splitlines()]
            self.assertEqual(lines[-1]["seq"], 51); self.assertEqual(health["last_seq"], 51)

    def test_empty_feed_health_does_not_report_false_cursor_gap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            def fake_fetch(params): return {"data": [], "meta": {"total": 0, "limit": 100, "offset": 0}}
            health = mod.run("delta", root, fake_fetch, now=datetime(2026, 10, 9, tzinfo=timezone.utc))
            self.assertEqual(health["first_seq"], 0); self.assertEqual(health["last_seq"], 0)


if __name__ == "__main__":
    unittest.main()
