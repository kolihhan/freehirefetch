import importlib.util
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "freehire_fetch.py"
spec = importlib.util.spec_from_file_location("freehire_fetch_cursor_health", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class CursorHealthTests(unittest.TestCase):
    def test_empty_retained_feed_after_history_points_to_next_sequence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "state").mkdir()
            (root / "feed").mkdir()
            (root / "state" / "seen.json").write_text("{}\n")
            (root / "feed" / "events.jsonl").write_text("")
            (root / "health.json").write_text('{"first_seq":877,"last_seq":877}\n')

            def fake_fetch(params):
                return {"data": [], "meta": {"total": 0, "limit": 100, "offset": 0}}

            health = mod.run("delta", root, fake_fetch, now=datetime(2026, 10, 9, tzinfo=timezone.utc))
            self.assertEqual(health["first_seq"], 878)
            self.assertEqual(health["last_seq"], 877)

    def test_health_contains_duration_seconds(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            def fake_fetch(params):
                return {"data": [], "meta": {"total": 0, "limit": 100, "offset": 0}}

            health = mod.run("delta", root, fake_fetch, now=datetime(2026, 10, 9, tzinfo=timezone.utc))
            self.assertIn("duration_seconds", health)
            self.assertGreaterEqual(health["duration_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
