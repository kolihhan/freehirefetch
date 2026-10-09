import importlib.util
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone

SCRIPT = Path(__file__).parents[1] / "freehire_fetch.py"
spec = importlib.util.spec_from_file_location("freehire_fetch", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class FullBackstopRegressionTests(unittest.TestCase):
    def test_full_scan_seeds_stale_unseen_job_without_emitting_new_event(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            jobs = {
                "SG": [
                    {
                        "public_slug": "stale-role",
                        "title": "Backend Engineer",
                        "company_name": "OldCo",
                        "created_at": "2026-07-01T00:00:00Z",
                        "posted_at": "2026-09-01T00:00:00Z",
                    }
                ],
                "CN": [],
            }

            def fake_fetch(params):
                data = jobs[params["countries"]]
                return {
                    "data": data,
                    "meta": {
                        "total": len(data),
                        "limit": 100,
                        "offset": 0,
                    },
                }

            health = mod.run(
                "full",
                root,
                fake_fetch,
                now=datetime(2026, 10, 9, tzinfo=timezone.utc),
            )

            events_path = root / "feed" / "events.jsonl"
            emitted = events_path.read_text(encoding="utf-8") if events_path.exists() else ""
            self.assertEqual(emitted, "")
            self.assertEqual(health["new"], 0)
            self.assertIn("stale-role", mod.load_public_state(root)[0])


if __name__ == "__main__":
    unittest.main()
