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
    def test_lever_full_jd_includes_requirements_and_apply_url(self):
        board = {"ats": "lever", "slug": "sonarsource", "company": "Sonar",
                 "markets": ["SG"], "career_url": "https://jobs.lever.co/sonarsource"}
        raw = {"id": "role-1", "text": "Research Engineer",
               "categories": {"location": "Singapore", "commitment": "Full-time"},
               "descriptionPlain": "Build AI systems.",
               "lists": [{"text": "Requirements", "content": "<li>At least 2 years of experience as a Research Engineer.</li>"},
                         {"text": "Responsibilities", "content": "<li>Evaluate coding agents.</li>"}],
               "additionalPlain": "Work authorization information.",
               "hostedUrl": "https://jobs.lever.co/sonarsource/role-1",
               "applyUrl": "https://jobs.lever.co/sonarsource/role-1/apply"}
        with patch.object(ats, "request_json", return_value=[raw]):
            job = ats.listing(board)[0]
        normalized = ats.normalize(board, job, "2026-11-25T00:00:00Z")
        self.assertIn("At least 2 years of experience as a Research Engineer.", normalized["description_text"])
        self.assertIn("Evaluate coding agents.", normalized["description_text"])
        self.assertIn("Work authorization information.", normalized["description_text"])
        self.assertEqual(raw["applyUrl"], normalized["apply_url"])
        self.assertEqual("full_jd", normalized["evidence"])

    def test_new_official_sg_owner_ats_slugs_and_region_gate(self):
        # Slugs are anchored to exact employer-authored application URLs;
        # actual endpoint availability must be verified by the ATS producer.
        config=json.loads((Path(__file__).parent / "ats_boards.json").read_text())
        expected={
            ("greenhouse", "telnyx54"): ("Telnyx", "https://job-boards.greenhouse.io/telnyx54"),
            ("lever", "sonarsource"): ("Sonar", "https://jobs.lever.co/sonarsource"),
        }
        for item in config["boards"]:
            ident=(item["ats"],item["slug"])
            if ident not in expected:
                continue
            company,url=expected.pop(ident)
            self.assertEqual(item["company"],company)
            self.assertEqual(item["career_url"],url)
            self.assertEqual(item["markets"],["SG"])
            ats.validate(item)
            self.assertEqual("SG",ats.market_for("Singapore",item))
            self.assertIsNone(ats.market_for("Shenzhen, China",item))
        self.assertEqual(expected,{})

    def test_sg_frontier_retrieval_and_research_owner_boards(self):
        # First-party exact application routes; CI probes their live Ashby JSON.
        config=json.loads((Path(__file__).parent / "ats_boards.json").read_text())
        expected={
            "exa": ("Exa", "https://jobs.ashbyhq.com/exa"),
            "ami": ("AMI Labs", "https://jobs.ashbyhq.com/ami"),
        }
        for board in config["boards"]:
            if board["ats"] != "ashby" or board["slug"] not in expected:
                continue
            company, url=expected.pop(board["slug"])
            self.assertEqual(board["company"], company)
            self.assertEqual(board["career_url"], url)
            self.assertEqual(board["markets"], ["SG"])
            ats.validate(board)
            self.assertEqual(ats.market_for("Singapore", board), "SG")
            self.assertIsNone(ats.market_for("Paris", board))
            self.assertIsNone(ats.market_for("Austin, TX", board))
        self.assertEqual(expected, {})

    def test_abound_shenzhen_official_board_is_registered_cn_only(self):
        config=json.loads((Path(__file__).parent / "ats_boards.json").read_text())
        items=[b for b in config["boards"] if b["ats"]=="ashby" and
               b["slug"].lower()=="abound"]
        self.assertEqual(1,len(items))
        board=items[0]
        ats.validate(board)
        self.assertEqual(["CN"], board["markets"])
        # The public employer role is 1-3 YOE Shenzhen, NOT its separate
        # London graduate programme; geography must not leak across markets.
        shenzhen=row(title="AI Engineer", loc="Shenzhen", desc=
                     "Build AI agents and RAG evaluation pipelines")
        shenzhen["url"]="https://jobs.ashbyhq.com/abound/c952071d-2249-4137-b03e-e67a5b6353d6"
        self.assertEqual("CN",ats.normalize(board,shenzhen,"2026-11-09T13:00:00Z")["market"])
        london=row(title="Graduate AI Engineer", loc="London",
                   desc="Build LLM agents and evaluation pipelines")
        london["url"]="https://jobs.ashbyhq.com/abound/066b6933-ea2d-4a1a-a1a4-2a80d5d3a57f"
        self.assertIsNone(ats.normalize(board,london,"2026-11-09T13:00:00Z"))


    def test_ashby_without_id_and_direct_only_survives_into_public_feed(self):
        uuid = "52e1cc10-dfe0-4361-81c1-227f70f61e20"
        item = {
            "title": "LLM Agent Engineer", "location": "Singapore",
            "jobUrl": f"https://jobs.ashbyhq.com/bjakcareer/{uuid}",
            "applyUrl": f"https://jobs.ashbyhq.com/bjakcareer/{uuid}/application",
            "descriptionPlain": "Build retrieval, RAG and agent evaluation.",
            "employmentType": "FullTime", "isListed": False,
            "compensation": {
                "scrapeableCompensationSalarySummary": "SGD 72000 - 96000 per year",
                "summaryComponents": [
                    {"compensationType": "Salary", "currencyCode": "SGD",
                     "interval": "1 YEAR", "minValue": 72000, "maxValue": 96000},
                    {"compensationType": "Bonus", "currencyCode": "SGD", "minValue": 500}
                ]
            },
        }
        board = {**MY, "markets": ["SG"]}
        with patch.object(ats, "request_json", return_value={"jobs": [item]}):
            jobs = ats.listing(board)
        self.assertEqual(1, len(jobs))
        self.assertEqual(uuid, jobs[0]["id"])
        self.assertEqual("DIRECT_LINK_ONLY", jobs[0]["listing_visibility"])
        self.assertEqual(1, len(jobs[0]["salary_components"]))
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ats, "listing", return_value=jobs):
                result = ats.run(Path(tmp), [board])
            self.assertTrue(result["health"]["complete"])
            current = feed(Path(tmp), "current.json")["jobs"]
            self.assertEqual(1, len(current))
            self.assertEqual(uuid, current[0]["job_id"])
            self.assertEqual("DIRECT_LINK_ONLY", current[0]["listing_visibility"])
            self.assertEqual(72000, current[0]["salary_components"][0]["minValue"])
            self.assertIn("/application", current[0]["apply_url"])
            self.assertIn("SGD 72000", current[0]["salary_summary"])
            self.assertEqual("FullTime", current[0]["employment_type"])

    def test_ashby_url_must_match_official_board_and_uuid(self):
        good_uuid = "52e1cc10-dfe0-4361-81c1-227f70f61e20"
        for role_url in (
            "https://malicious.example/bjakcareer/" + good_uuid,
            "https://jobs.ashbyhq.com/otherboard/" + good_uuid,
            "https://jobs.ashbyhq.com/bjakcareer/not-a-uuid",
            "https://jobs.ashbyhq.com/bjakcareer/" + good_uuid + "/application",
            "",
        ):
            with self.subTest(role_url=role_url):
                with patch.object(ats, "request_json", return_value={"jobs": [
                    {"title": "LLM Engineer", "location": "Singapore", "jobUrl": role_url}
                ]}):
                    with self.assertRaises(ValueError):
                        ats.listing({**MY, "markets": ["SG"]})

    def test_ashby_existing_id_kept_for_stable_historical_keys(self):
        uuid = "52e1cc10-dfe0-4361-81c1-227f70f61e20"
        item = {"id": "existing-ats-id", "jobUrl": f"https://jobs.ashbyhq.com/bjakcareer/{uuid}",
                "title": "LLM Engineer", "location": "Singapore"}
        self.assertEqual("existing-ats-id", ats.ashby_job_identity(MY, item))

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



    def test_workday_partial_windows_keep_successful_rows(self):
        board = {"ats": "workday", "slug": "micron", "company": "Micron", "markets": ["SG"],
                 "career_url": "https://micron.wd1.myworkdayjobs.com/en-US/External",
                 "search_terms": ["AI", "machine learning", "LLM"]}
        first = {"title": "AI Engineer", "externalPath": "/job/Singapore/AI-Engineer_JR1", "locationsText": "Singapore"}
        second = {"title": "LLM Engineer", "externalPath": "/job/Singapore/LLM-Engineer_JR2", "locationsText": "Singapore"}
        with patch.object(ats, "request_json", side_effect=[{"jobPostings": [first], "total": 1},
                TimeoutError("blocked window"), {"jobPostings": [second], "total": 1}]):
            with self.assertRaises(ats.PartialListing) as result:
                ats.listing(board)
        self.assertEqual(2, len(result.exception.rows))
        self.assertIn("blocked window", str(result.exception))

    def test_workday_429_defers_remaining_windows_preserving_rows(self):
        board = {"ats": "workday", "slug": "micron", "company": "Micron", "markets": ["SG"],
                 "career_url": "https://micron.wd1.myworkdayjobs.com/en-US/External",
                 "search_terms": ["AI", "machine learning", "LLM"]}
        first = {"title": "AI Engineer", "externalPath": "/job/Singapore/AI-Engineer_JR1", "locationsText": "Singapore"}
        error = ats.HTTPError("https://micron.wd1.myworkdayjobs.com", 429, "Too Many Requests", {}, None)
        with patch.object(ats, "request_json", side_effect=[
            {"jobPostings": [first], "total": 1}, error]) as request:
            with self.assertRaises(ats.PartialListing) as caught:
                ats.listing(board)
        self.assertEqual(2, request.call_count)
        self.assertEqual(1, len(caught.exception.rows))
        self.assertIn("deferred", str(caught.exception))
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ats, "listing", side_effect=caught.exception), patch.object(ats, "enrich_listed_details") as enrich:
                result = ats.run(Path(tmp), [board])
            enrich.assert_not_called()
            self.assertEqual("PARTIAL", result["health"]["boards"]["workday:micron"]["status"])
            self.assertEqual(1, result["jobs"])

    def test_workday_http_429_not_retried(self):
        url = "https://micron.wd1.myworkdayjobs.com/wday/cxs/micron/External/jobs"
        error = ats.HTTPError(url, 429, "Too Many Requests", {}, None)
        with patch.object(ats, "urlopen", side_effect=error) as request, patch.object(ats.time, "sleep") as sleep:
            with self.assertRaises(ats.HTTPError):
                ats.request_json(url)
        self.assertEqual(1, request.call_count)
        sleep.assert_not_called()

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



    def test_small_candidate_index_and_sharded_jd_recovery_on_board_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            details = "Build RAG, agent evaluation, Python. " * 80
            with patch.object(ats, "listing", return_value=[row(desc=details)]):
                ats.run(root, [MY], clock="2026-11-09T00:00:00Z")
            current = feed(root, "current.json")
            self.assertEqual(1, len(current["jobs"]))
            self.assertNotIn("description_text", current["jobs"][0])
            index = json.loads((root / "feed/ats/jd/index.json").read_text())
            self.assertEqual(1, len(index["parts"]))
            self.assertEqual(2, index["version"])
            self.assertEqual(1, len(index["jobs"]))
            self.assertEqual(current["jobs"][0]["key"], index["jobs"][0]["key"])
            self.assertEqual("2026-11-09T00:00:00Z", index["jobs"][0]["checked_at"])
            part = index["parts"][0]["path"]
            self.assertEqual(part, index["jobs"][0]["part"])
            content = json.loads((root / "feed/ats/jd" / part).read_text())
            self.assertEqual(details.strip(), content["jobs"][0]["description_text"])
            with patch.object(ats, "listing", side_effect=RuntimeError("429")):
                failed = ats.run(root, [MY], clock="2026-11-09T01:00:00Z")
            self.assertEqual([], failed["events"])
            self.assertEqual("FAILED", failed["health"]["boards"]["ashby:bjakcareer"]["status"])
            fresh = json.loads((root / "feed/ats/jd" / part).read_text())
            self.assertEqual(details.strip(), fresh["jobs"][0]["description_text"])
            self.assertNotIn("description_text", feed(root, "current.json")["jobs"][0])
            recovered = json.loads((root / "feed/ats/jd/index.json").read_text())
            self.assertEqual("2026-11-09T00:00:00Z", recovered["jobs"][0]["checked_at"])



    def test_smartrecruiters_hydrates_first_party_jd_before_issue_review(self):
        role = {"id": "6000000001174513", "title": "Machine Learning Engineer",
                "location": "Singapore", "description": "",
                "url": "https://jobs.smartrecruiters.com/NCS3/6000000001174513"}
        api_payload = {"jobAd": {"sections": {
            "jobDescription": {"text": "<p>Build machine learning services.</p>"},
            "qualifications": {"text": "<p>Python, ML projects required; cloud is a plus.</p>"}
        }}}
        with patch.object(ats, "request_json", return_value=api_payload) as mocked:
            changed = ats.enrich_listed_details(SG, [role])
        self.assertEqual(1, changed)
        self.assertIn("machine learning", role["description"])
        self.assertIn("ML projects required", role["description"])
        self.assertTrue(mocked.call_args.args[0].endswith("/NCS3/postings/6000000001174513"))

    def test_workday_hydrates_jd_and_preserves_listing_when_api_fails(self):
        board = {"ats": "workday", "slug": "ntu", "company": "NTU",
                 "markets": ["SG"], "career_url": "https://ntu.wd3.myworkdayjobs.com/Careers"}
        url = "https://ntu.wd3.myworkdayjobs.com/wday/cxs/ntu/Careers/job/AI_Req123"
        good = {"id": "AI_Req123", "title": "AI Research Engineer", "location": "Singapore",
                "description": "", "url": "https://ntu.wd3.myworkdayjobs.com/Careers/job/AI_Req123",
                "detail_url": url}
        with patch.object(ats, "request_json", return_value={
            "jobPostingInfo": {"jobDescription": "<p>Research NLP agents and evaluate tools.</p>",
                               "timeType": "Full time"}
        }):
            count = ats.enrich_listed_details(board, [good])
        self.assertEqual(1, count)
        self.assertIn("NLP agents", good["description"])
        self.assertEqual("Full time", good["employment"])
        failed = dict(good, description="")
        with patch.object(ats, "request_json", side_effect=RuntimeError("429")):
            self.assertEqual(0, ats.enrich_listed_details(board, [failed]))
        self.assertEqual("", failed["description"])

    def test_detail_hydration_prioritizes_early_career_ai(self):
        roles = [
            {"id": "senior", "title": "Senior AI Engineer", "location": "Singapore", "description": ""},
            {"id": "junior", "title": "AI Engineer", "location": "Singapore", "description": ""}
        ]
        with patch.object(ats, "request_json", return_value={
            "jobAd": {"sections": {"jobDescription": {"text": "Build RAG and agent models"}}}
        }) as req:
            self.assertEqual(1, ats.enrich_listed_details(SG, roles, limit=1))
        self.assertTrue(req.call_args.args[0].endswith("/junior"))
        self.assertEqual("", roles[0]["description"])
        self.assertIn("RAG", roles[1]["description"])



    def test_compact_market_index_matches_global_public_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(ats, "listing", return_value=[
                row("id-1", desc="Build RAG and agent evaluations " * 150),
                row("id-2", title="Backend Software Engineer", desc="Develop AI retrieval evaluation services")
            ]):
                ats.run(root, [MY])
            global_rows = feed(root, "current.json")["jobs"]
            my_rows = json.loads((root / "feed/ats/markets/MY.json").read_text())["jobs"]
            sg_rows = json.loads((root / "feed/ats/markets/SG.json").read_text())["jobs"]
            self.assertEqual(global_rows, my_rows)
            self.assertEqual([], sg_rows)
            self.assertTrue(all(len(r["description_excerpt"]) <= 240 for r in my_rows))
            self.assertTrue(all("description_text" not in r for r in my_rows))
            part = json.loads((root / "feed/ats/jd/MY-000.json").read_text())["jobs"]
            self.assertEqual({r["key"] for r in my_rows}, {r["key"] for r in part})



if __name__ == "__main__":
    unittest.main()
