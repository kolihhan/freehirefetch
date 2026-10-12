import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / "freehire_fetch.py"
spec = importlib.util.spec_from_file_location("freehire_fetch", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class MarketCoverageTests(unittest.TestCase):
    def test_malaysia_params_use_country_filter(self):
        params = mod.build_params("MY", "delta", 0)
        self.assertEqual(params["countries"], "MY")
        self.assertEqual(params["open_within_days"], 2)

    def test_run_fetches_malaysia_alongside_sg_and_cn(self):
        calls = []
        jobs = {
            "SG": [{"public_slug": "sg1", "title": "AI Engineer", "created_at": "2026-10-12T00:00:00Z"}],
            "CN": [{"public_slug": "cn1", "title": "Backend Engineer", "created_at": "2026-10-12T00:00:00Z"}],
            "MY": [{"public_slug": "my1", "title": "Applied AI Engineer", "created_at": "2026-10-12T00:00:00Z"}],
        }

        def fake_fetch(params):
            country = params["countries"]
            calls.append(country)
            data = jobs[country]
            return {"data": data, "meta": {"total": len(data), "limit": 100, "offset": 0}}

        with tempfile.TemporaryDirectory() as td:
            health = mod.run(
                "bootstrap",
                Path(td),
                fake_fetch,
                now=datetime(2026, 10, 12, tzinfo=timezone.utc),
            )

        self.assertEqual(calls, ["SG", "CN", "MY"])
        self.assertEqual(health["markets"]["MY"]["fetched"], 1)
        self.assertEqual(health["new"], 3)


if __name__ == "__main__":
    unittest.main()
