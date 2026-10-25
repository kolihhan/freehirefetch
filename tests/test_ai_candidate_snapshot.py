import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone

SCRIPT = Path(__file__).parents[1] / "firehose_fetch.py"
spec = importlib.util.spec_from_file_location("firehose_fetch", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class AICandidateSnapshotTests(unittest.TestCase):
    def test_ai_title_is_high_relevance(self):
        score, signals = mod.ai_relevance({
            "title": "LLM Evaluation Engineer",
            "description": "Build evaluation pipelines for agents and RAG systems.",
            "category": "ai_engineering",
        })
        self.assertGreaterEqual(score, mod.AI_CANDIDATE_MIN_SCORE)
        self.assertIn("title:llm", signals)

    def test_generic_backend_with_one_ai_mention_is_not_candidate(self):
        score, _ = mod.ai_relevance({
            "title": "Backend Engineer",
            "description": "Build APIs and distributed systems. Some teams experiment with an AI assistant.",
            "category": "backend",
        })
        self.assertLess(score, mod.AI_CANDIDATE_MIN_SCORE)

    def test_generic_software_role_with_material_ai_jd_survives(self):
        score, signals = mod.ai_relevance({
            "title": "Software Engineer",
            "description": "Build LLM agents, RAG retrieval, vector search, tool calling and evaluation pipelines in Python.",
            "category": "software_engineering",
        })
        self.assertGreaterEqual(score, mod.AI_CANDIDATE_MIN_SCORE)
        self.assertIn("jd:llm", signals)
        self.assertIn("jd:agent", signals)

    def test_research_engineer_with_ai_description_survives(self):
        score, signals = mod.ai_relevance({
            "title": "Research Engineer",
            "description": "Research and implement machine learning models, deep learning and model evaluation.",
            "category": "ml_ai",
        })
        self.assertGreaterEqual(score, mod.AI_CANDIDATE_MIN_SCORE)
        self.assertIn("title:research", signals)

    def test_explicit_non_permanent_job_is_not_candidate(self):
        snapshot = mod.build_candidate_snapshot(
            {
                "SG": [{
                    "public_slug": "sg-contract-ai",
                    "title": "AI Engineer",
                    "company_name": "ContractCo",
                    "description": "Build LLM agents and RAG systems.",
                    "category": "ai_engineering",
                    "employment_type": "Contract",
                }],
                "CN": [],
                "MY": [],
            },
            generated_at="2026-10-25T00:00:00Z",
            mode="delta",
        )
        self.assertEqual(snapshot["count"], 0)

    def test_snapshot_is_bounded_per_market_and_contains_short_excerpt(self):
        jobs = {
            "SG": [
                {
                    "public_slug": f"sg-{i}",
                    "title": "AI Engineer",
                    "company_name": f"SG{i}",
                    "description": "Build LLM agents, RAG and evaluation systems. " + ("x" * 900),
                    "category": "ai_engineering",
                    "created_at": f"2026-10-{25 - i:02d}T00:00:00Z",
                    "_event_kind": "NEW",
                    "_event_seq": 100 + i,
                }
                for i in range(4)
            ],
            "CN": [],
            "MY": [],
        }
        snapshot = mod.build_candidate_snapshot(
            jobs,
            generated_at="2026-10-25T00:00:00Z",
            mode="delta",
            limit_per_market=2,
        )
        self.assertEqual(snapshot["counts"]["SG"], 2)
        self.assertEqual(snapshot["count"], 2)
        self.assertEqual(len(snapshot["candidates"]), 2)
        self.assertLessEqual(len(snapshot["candidates"][0]["description_excerpt"]), mod.AI_CANDIDATE_EXCERPT_CHARS)
        self.assertGreaterEqual(snapshot["candidates"][0]["ai_score"], mod.AI_CANDIDATE_MIN_SCORE)
        self.assertIn(snapshot["candidates"][0]["event_kind"], {"NEW", "CHANGED"})
        self.assertIsInstance(snapshot["candidates"][0]["event_seq"], int)

    def test_run_snapshot_contains_only_new_or_changed_ai_jobs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "state").mkdir(parents=True)
            (root / "feed").mkdir(parents=True)

            unchanged = {
                "public_slug": "sg-unchanged",
                "title": "AI Engineer",
                "company_name": "SameCo",
                "description": "Build LLM agents and RAG systems.",
                "category": "ai_engineering",
                "created_at": "2026-10-25T00:00:00Z",
            }
            old_changed = {
                "public_slug": "sg-changed",
                "title": "AI Engineer",
                "company_name": "ChangedCo",
                "description": "Build machine learning models.",
                "category": "ai_engineering",
                "created_at": "2026-10-25T00:00:00Z",
            }
            changed = dict(old_changed, description="Build LLM agents, RAG retrieval and evaluation pipelines.")
            new = {
                "public_slug": "sg-new",
                "title": "Research Engineer",
                "company_name": "NewCo",
                "description": "Research machine learning and deep learning model evaluation.",
                "category": "ml_ai",
                "created_at": "2026-10-25T00:00:00Z",
            }
            seen = {
                "sg-unchanged": {
                    "fingerprint": mod.worker.content_fingerprint(unchanged),
                    "last_seen": "2026-10-24T00:00:00Z",
                },
                "sg-changed": {
                    "fingerprint": mod.worker.content_fingerprint(old_changed),
                    "last_seen": "2026-10-24T00:00:00Z",
                },
            }
            (root / "state" / "seen.json").write_text(json.dumps(seen) + "\n", encoding="utf-8")
            (root / "feed" / "events.jsonl").write_text("", encoding="utf-8")
            (root / "health.json").write_text('{"last_seq":40}\n', encoding="utf-8")

            jobs = {"SG": [unchanged, changed, new], "CN": [], "MY": []}

            def fake_fetch(params):
                data = jobs[params["countries"]]
                return {"data": data, "meta": {"total": len(data), "limit": 100, "offset": 0}}

            mod.configure_worker()
            mod.worker.run("delta", root, fake_fetch, now=datetime(2026, 10, 25, tzinfo=timezone.utc))
            snapshot = json.loads((root / "feed" / "candidates.json").read_text(encoding="utf-8"))
            by_slug = {candidate["public_slug"]: candidate for candidate in snapshot["candidates"]}

            self.assertEqual(set(by_slug), {"sg-changed", "sg-new"})
            self.assertEqual(by_slug["sg-changed"]["event_kind"], "CHANGED")
            self.assertEqual(by_slug["sg-new"]["event_kind"], "NEW")
            self.assertEqual({by_slug["sg-changed"]["event_seq"], by_slug["sg-new"]["event_seq"]}, {41, 42})

    def test_run_writes_candidate_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            jobs = {
                "SG": [{
                    "public_slug": "sg-ai",
                    "title": "Software Engineer",
                    "company_name": "Acme AI",
                    "description": "Build LLM agents, RAG retrieval, tool calling and evaluation pipelines.",
                    "category": "software_engineering",
                    "created_at": "2026-10-25T00:00:00Z",
                }],
                "CN": [{
                    "public_slug": "cn-generic",
                    "title": "Backend Engineer",
                    "company_name": "GenericCo",
                    "description": "Build APIs and databases.",
                    "category": "backend",
                    "created_at": "2026-10-25T00:00:00Z",
                }],
                "MY": [],
            }

            def fake_fetch(params):
                data = jobs[params["countries"]]
                return {"data": data, "meta": {"total": len(data), "limit": 100, "offset": 0}}

            mod.configure_worker()
            mod.worker.run("delta", root, fake_fetch, now=datetime(2026, 10, 25, tzinfo=timezone.utc))
            snapshot = json.loads((root / "feed" / "candidates.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot["count"], 1)
            self.assertEqual(snapshot["candidates"][0]["public_slug"], "sg-ai")
            self.assertEqual(snapshot["candidates"][0]["event_kind"], "NEW")
            self.assertEqual(snapshot["candidates"][0]["event_seq"], 1)


if __name__ == "__main__":
    unittest.main()
