import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / "firehose_fetch.py"
spec = importlib.util.spec_from_file_location("firehose_fetch_coldstart", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ColdStartSnapshotTests(unittest.TestCase):
    def test_full_run_writes_all_current_plausible_jobs_even_when_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "state").mkdir(parents=True)
            (root / "feed").mkdir(parents=True)

            ai_job = {
                "public_slug": "sg-existing-ai",
                "title": "Software Engineer",
                "company_name": "Acme AI",
                "location": "Singapore",
                "description": "Build LLM agents, RAG retrieval, vector search and evaluation pipelines.",
                "category": "software_engineering",
                "created_at": "2026-10-25T00:00:00Z",
            }
            generic_job = {
                "public_slug": "sg-generic",
                "title": "Backend Engineer",
                "company_name": "GenericCo",
                "location": "Singapore",
                "description": "Build REST APIs and databases.",
                "category": "backend",
                "created_at": "2026-10-25T00:00:00Z",
            }
            seen = {
                "sg-existing-ai": {
                    "fingerprint": mod.worker.content_fingerprint(ai_job),
                    "last_seen": "2026-10-24T00:00:00Z",
                }
            }
            (root / "state" / "seen.json").write_text(json.dumps(seen) + "\n", encoding="utf-8")
            (root / "feed" / "events.jsonl").write_text("", encoding="utf-8")
            (root / "health.json").write_text('{"last_seq":40}\n', encoding="utf-8")

            jobs = {"SG": [ai_job, generic_job], "CN": [], "MY": []}

            def fake_fetch(params):
                data = jobs[params["countries"]]
                return {"data": data, "meta": {"total": len(data), "limit": 100, "offset": 0}}

            mod.configure_worker()
            mod.worker.run("full", root, fake_fetch, now=datetime(2026, 11, 3, tzinfo=timezone.utc))

            coldstart_path = root / "feed" / "coldstart.json"
            self.assertTrue(coldstart_path.exists())
            coldstart = json.loads(coldstart_path.read_text(encoding="utf-8"))
            self.assertEqual(coldstart["mode"], "coldstart")
            self.assertEqual(coldstart["raw_counts"]["SG"], 2)
            self.assertEqual(coldstart["counts"]["SG"], 1)
            self.assertEqual(coldstart["count"], 1)
            self.assertEqual(coldstart["candidates"][0]["public_slug"], "sg-existing-ai")


if __name__ == "__main__":
    unittest.main()
