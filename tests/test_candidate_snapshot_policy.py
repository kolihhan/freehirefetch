import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).parents[1] / "firehose_fetch.py"
spec = importlib.util.spec_from_file_location("firehose_fetch", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class CandidateSnapshotPolicyTests(unittest.TestCase):
    def test_default_snapshot_is_not_capped_per_market(self):
        jobs = {
            "SG": [
                {
                    "public_slug": f"sg-{i}",
                    "title": "AI Engineer",
                    "company_name": f"SG{i}",
                    "description": "Build LLM agents, RAG retrieval and evaluation systems.",
                    "category": "ai_engineering",
                    "_event_kind": "NEW",
                    "_event_seq": i + 1,
                }
                for i in range(25)
            ],
            "CN": [],
            "MY": [],
        }

        snapshot = mod.build_candidate_snapshot(
            jobs,
            generated_at="2026-11-02T00:00:00Z",
            mode="delta",
        )

        self.assertEqual(snapshot["counts"]["SG"], 25)
        self.assertEqual(snapshot["count"], 25)

    def test_fixed_term_ai_research_role_survives(self):
        snapshot = mod.build_candidate_snapshot(
            {
                "SG": [{
                    "public_slug": "sg-research-fixed-term",
                    "title": "Research Assistant",
                    "company_name": "Example University",
                    "description": "Research LLM agents, retrieval and NLP evaluation.",
                    "category": "ml_ai",
                    "employment_type": "Fixed-term contract",
                    "_event_kind": "NEW",
                    "_event_seq": 1,
                }],
                "CN": [],
                "MY": [],
            },
            generated_at="2026-11-02T00:00:00Z",
            mode="delta",
        )

        self.assertEqual(snapshot["count"], 1)
        self.assertEqual(snapshot["candidates"][0]["title"], "Research Assistant")
        self.assertIn("title:research", snapshot["candidates"][0]["ai_signals"])


if __name__ == "__main__":
    unittest.main()
