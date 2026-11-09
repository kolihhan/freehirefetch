"""Offline regression tests for the public browserless ATS feed."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ats_discovery as ats


MY = {"ats": "ashby", "slug": "bjakcareer", "company": "BJAK", "markets": ["MY"], "my_swe": True}
SG = {"ats": "smartrecruiters", "slug": "NCS3", "company": "NCS", "markets": ["SG"]}


def row(id="id-1", title="Junior AI Engineer", loc="Kuala Lumpur, Malaysia", desc="Build RAG and LLM evaluation pipelines"):
    return {"id": id, "title": title, "location": loc, "description": desc,
            "url": "https://jobs.ashbyhq.com/bjakcareer/" + id, "employment": "Full time", "posted_at": "2026-11-08"}


def feed(root, file):
    return json.loads((root / "feed" / "ats" / file).read_text())


class ATSFeedTests(unittest.TestCase):
    def test_baseline_then_new_and_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(ats, "listing", return_value=[row()]):
                first = ats.run(root, [MY], clock="2026-11-09T00:00:00Z")
            self.assertEqual(["BASELINE"], [e["kind"] for e in first["events"]])
            with patch.object(ats, "listing", return_value=[row(), row("id-2")]):
                second = ats.run(root, [MY], clock="2026-11-09T01:00:00Z")
            self.assertEqual(["NEW"], [e["kind"] for e in second["events"]])
            jobs = feed(root, "current.json")["jobs"]
            self.assertEqual(2, len(jobs))
            self.assertEqual("2026-11-09T00:00:00Z", jobs[0]["first_seen_at"])
            with patch.object(ats, "listing", return_value=[row(desc="Build advanced RAG and agent reliability"), row("id-2")]):
                changed = ats.run(root, [MY], clock="2026-11-09T02:00:00Z")
            self.assertEqual(["CHANGED"], [e["kind"] for e in changed["events"]])

    def test_failure_preserves_old_board_without_fake_closure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(ats, "listing", return_value=[row()]):
                ats.run(root, [MY])
            with patch.object(ats, "listing", side_effect=RuntimeError("429 on page two")):
                result = ats.run(root, [MY])
            self.assertFalse(result["health"]["complete"])
            self.assertEqual(1, len(feed(root, "current.json")["jobs"]))
            self.assertEqual([], result["events"])
            self.assertEqual("FAILED", feed(root, "health.json")["boards"]["ashby:bjakcareer"]["status"])

    def test_closed_only_on_complete_successful_enumeration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(ats, "listing", return_value=[row()]):
                ats.run(root, [MY])
            with patch.object(ats, "listing", return_value=[]):
                result = ats.run(root, [MY])
            self.assertEqual(["REMOVED_FROM_FEED"], [e["kind"] for e in result["events"]])
            self.assertEqual([], feed(root, "current.json")["jobs"])

    def test_title_and_market_gate_avoid_generic_sg(self):
        item = row(title="Backend Software Engineer", loc="Singapore", desc="Build standard payment REST APIs")
        self.assertIsNone(ats.normalize(SG, item, "now"))
        item["location"] = "Petaling Jaya, Malaysia"
        self.assertEqual("MY_SWE_SECONDARY", ats.normalize(MY, item, "now")["lane"])
        item["location"] = "New York"
        self.assertIsNone(ats.normalize(MY, item, "now"))

    def test_paginated_smartrecruiters_reads_next_page(self):
        postings = [{"id": "first", "name": "AI Engineer", "location": {"city": "Singapore"}},
                    {"id": "second", "name": "LLM Engineer", "location": {"city": "Singapore"}}]
        with patch.object(ats, "request_json", side_effect=[
            {"content": postings[:1], "totalFound": 2},
            {"content": postings[1:], "totalFound": 2},
        ]) as mocked:
            result = ats.listing(SG)
        self.assertEqual(2, len(result))
        self.assertEqual(2, mocked.call_count)

    def test_workday_page_one_not_silent_end(self):
        board = {"ats": "workday", "slug": "ntu", "company": "NTU", "markets": ["SG"],
                 "career_url": "https://ntu.wd3.myworkdayjobs.com/en-US/Careers"}
        with patch.object(ats, "request_json", side_effect=[
            {"jobPostings": [{"title": "AI Research Engineer", "externalPath": "/job/Research_Req1",
                              "locationsText": "Singapore"}], "total": 2},
            {"jobPostings": [{"title": "AI Engineer", "externalPath": "/job/Engineer_Req2",
                              "locationsText": "Singapore"}], "total": 2},
        ]) as req:
            result = ats.listing(board)
        self.assertEqual(2, len(result))
        self.assertEqual(2, req.call_count)
        self.assertIn("/Careers/job/Engineer", result[1]["url"])


    def test_keyword_workday_windows_dedupe_same_id(self):
        board = {"ats": "workday", "slug": "micron", "company": "Micron", "markets": ["SG"],
                 "career_url": "https://micron.wd1.myworkdayjobs.com/en-US/External",
                 "search_terms": ["AI", "machine learning"]}
        same = {"title": "AI Engineer", "externalPath": "/job/Singapore/AI-Engineer_JR1",
                "locationsText": "Singapore"}
        with patch.object(ats, "request_json", side_effect=[
            {"jobPostings": [same], "total": 1},
            {"jobPostings": [same], "total": 1}
        ]) as req:
            rows = ats.listing(board)
        self.assertEqual(1, len(rows))
        self.assertEqual(["AI", "machine learning"],
                         [call.kwargs["payload"]["searchText"] for call in req.call_args_list])



    def test_ai_branded_non_engineering_titles_do_not_flood_feed(self):
        for title in ("CEO, AI Finance", "Technical Product Manager - AI Investing",
                      "Product Owner - AI Agent", "Head of Machine Learning",
                      "AI Sales Engineer", "Research Engineer Internship"):
            with self.subTest(title=title):
                self.assertIsNone(ats.normalize(MY, row(title=title), "2026-11-09T00:00:00Z"))

    def test_real_ai_role_and_genuine_backend_still_survive(self):
        for title in ("AI Agent Engineer", "LLM Application Engineer",
                      "Research Engineer, Benchmarks", "Applied Machine Learning Engineer"):
            with self.subTest(title=title):
                record = ats.normalize(MY, row(title=title), "2026-11-09T00:00:00Z")
                self.assertIsNotNone(record)
                self.assertEqual("HIGH", record["triage_priority"])
        record = ats.normalize(MY, row(title="Backend Software Engineer",
            desc="Build a production RAG evaluation pipeline and retrieval APIs"), "now")
        self.assertIsNotNone(record)
        self.assertEqual("MEDIUM", record["triage_priority"])



    def test_applied_scientists_must_reach_review_queue(self):
        for title in ("Pioneer Talent Program - Applied Data Scientist",
                      "Applied Scientist, Agent Evaluation",
                      "Research Scientist, LLM Systems", "Algorithm Engineer - NLP"):
            with self.subTest(title=title):
                role = ats.normalize(MY, row(title=title), "2026-11-09T00:00:00Z")
                self.assertIsNotNone(role)
                self.assertEqual("AI", role["lane"])
        self.assertIsNone(ats.normalize(MY, row(title="Director, Applied Scientist"), "now"))



    def test_public_jd_preserves_decisive_requirements_beyond_excerpt(self):
        description = "Design RAG systems. " * 50 + "Hard requirement: AWS production deployment experience."
        actual = ats.normalize(MY, row(desc=description), "now")
        self.assertIsNotNone(actual)
        self.assertTrue(len(actual["description_text"]) > 550)
        self.assertIn("Hard requirement: AWS", actual["description_text"])
        self.assertNotIn("Hard requirement: AWS", actual["description_excerpt"])
        self.assertFalse(actual["description_truncated"])
        self.assertEqual("full_jd", actual["evidence"])
        very_long = ats.normalize(MY, row(desc="Build RAG. " * 2000), "now")
        self.assertTrue(very_long["description_truncated"])
        self.assertEqual(12000, len(very_long["description_text"]))
        self.assertEqual("partial_jd", very_long["evidence"])



if __name__ == "__main__":
    unittest.main()
