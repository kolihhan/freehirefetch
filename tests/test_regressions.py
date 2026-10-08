import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "freehire_fetch.py"
spec = importlib.util.spec_from_file_location("freehire_fetch_regression", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class FreeHireRegressionTests(unittest.TestCase):
    def test_synthetic_market_does_not_change_content_fingerprint(self):
        sg = {"public_slug": "multi", "title": "AI Engineer", "company": "Acme", "location": "", "countries": ["SG", "CN"], "market": "SG"}
        cn = dict(sg, market="CN")
        self.assertEqual(mod.content_fingerprint(sg), mod.content_fingerprint(cn))

    def test_unchanged_job_does_not_refresh_seen_timestamp(self):
        job = {"public_slug": "abc", "title": "AI Engineer", "company": "Acme"}
        seen = {"abc": {"fingerprint": mod.content_fingerprint(job), "last_seen": "2026-09-01T00:00:00Z"}}
        events, next_seen = mod.classify_events([job], seen, "2026-10-09T00:00:00Z", bootstrap=False)
        self.assertEqual(events, [])
        self.assertEqual(next_seen["abc"]["last_seen"], "2026-09-01T00:00:00Z")

    def test_event_does_not_embed_full_raw_job(self):
        job = {"public_slug": "abc", "title": "AI Engineer", "company": "Acme", "description": "x" * 10000, "url": "https://jobs.example/abc"}
        events, _ = mod.classify_events([job], {}, "2026-10-09T00:00:00Z", bootstrap=False)
        self.assertEqual(len(events), 1)
        self.assertNotIn("job", events[0])

    def test_source_and_freehire_urls_are_distinct(self):
        job = {"public_slug": "abc", "title": "AI Engineer", "company": "Acme", "url": "https://jobs.example/abc"}
        events, _ = mod.classify_events([job], {}, "2026-10-09T00:00:00Z", bootstrap=False)
        self.assertEqual(events[0]["source_url"], "https://jobs.example/abc")
        self.assertEqual(events[0]["freehire_url"], "https://freehire.me/jobs/abc")

    def test_delta_does_not_prune_old_unseen_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "state").mkdir()
            (root / "feed").mkdir()
            old_job = {"public_slug": "old-live", "title": "Backend Engineer", "company": "Acme"}
            old_fp = mod.content_fingerprint(old_job)
            (root / "state" / "seen.json").write_text(json.dumps({"old-live": {"fingerprint": old_fp, "last_seen": "2026-08-01T00:00:00Z"}}) + "\n")
            (root / "feed" / "events.jsonl").write_text("")
            (root / "health.json").write_text('{"first_seq":0,"last_seq":0}\n')
            def fake_fetch(params):
                return {"data": [], "meta": {"total": 0, "limit": 100, "offset": 0}}
            mod.run("delta", root, fake_fetch, now=datetime(2026, 10, 9, tzinfo=timezone.utc))
            kept = json.loads((root / "state" / "seen.json").read_text())
            self.assertIn("old-live", kept)

    def test_existing_event_is_compacted_on_next_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "state").mkdir()
            (root / "feed").mkdir()
            (root / "state" / "seen.json").write_text('{}\n')
            legacy = {"seq": 7, "kind": "NEW", "detected_at": "2026-10-08T00:00:00Z", "identity": "abc", "job": {"description": "x" * 10000}}
            (root / "feed" / "events.jsonl").write_text(json.dumps(legacy) + "\n")
            (root / "health.json").write_text('{"first_seq":7,"last_seq":7}\n')
            def fake_fetch(params):
                return {"data": [], "meta": {"total": 0, "limit": 100, "offset": 0}}
            mod.run("delta", root, fake_fetch, now=datetime(2026, 10, 9, tzinfo=timezone.utc))
            event = json.loads((root / "feed" / "events.jsonl").read_text().strip())
            self.assertNotIn("job", event)

    def test_seen_json_is_compact_machine_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            def fake_fetch(params):
                data = [{"public_slug": "a", "title": "AI Engineer", "company": "Acme", "created_at": "2026-10-09T00:00:00Z"}] if params["countries"] == "SG" else []
                return {"data": data, "meta": {"total": len(data), "limit": 100, "offset": 0}}
            mod.run("bootstrap", root, fake_fetch, now=datetime(2026, 10, 9, tzinfo=timezone.utc))
            text = (root / "state" / "seen.json").read_text()
            self.assertEqual(text.count("\n"), 1)


if __name__ == "__main__":
    unittest.main()
