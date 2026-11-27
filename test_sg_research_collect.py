import unittest
import sg_research_collect as s

SUTD = "https://careers.sutd.edu.sg/go/Researchers-Jobs/653644/"
JOB = "https://careers.sutd.edu.sg/job/Singapore-Research-Associate-138682/46469144/"
LIST = ("""<html><h1>Researchers Jobs</h1><p>Results 1 – 1 of 1 Page 1 of 1</p>"""
        """<a href="/job/Singapore-Research-Associate-138682/46469144/">Research Associate</a>"""
        """<a href="https://example.com/job/Fake/1234/">Research Engineer</a>"""
        """<a href="/job/Singapore-Admin/1234/">Admin Assistant</a></html>""")
DETAIL = ("""<html><a>Apply now »</a><h1>Research Associate</h1>"""
          """<p>Job Req ID: 2210</p><div>LLM Agents and RAG retrieval evaluation.</div></html>""")


class ResearchPortalProbeTests(unittest.TestCase):
    def test_only_same_employer_exact_job_urls_are_accepted(self):
        rows = s.candidates(LIST, SUTD)
        self.assertEqual(rows, [{"url": JOB, "title": "Research Associate"}])

    def test_full_detail_must_have_employer_req_and_apply_control(self):
        result = s.probe(("SUTD", SUTD), fetch=lambda url: LIST if url == SUTD else DETAIL)
        self.assertEqual(result["status"], "VERIFIED_BOUNDED_SOURCE_END")
        self.assertEqual(result["listing_identified"], 1)
        self.assertEqual(result["detail_verified"], 1)
        self.assertEqual(result["jobs"][0]["requisition"], "2210")
        self.assertIn("rag", result["jobs"][0]["technical_signals"])

    def test_false_success_shell_never_claimed_to_be_job_coverage(self):
        result = s.probe(("NUS", "https://careers.nus.edu.sg/NUS/go/test"),
                         fetch=lambda url: "<html><h1>Research Jobs</h1><p>Loading...</p></html>")
        self.assertEqual(result["status"], "UNDERCOVERED")
        self.assertEqual(result["listing_identified"], 0)

    def test_no_apply_control_preserves_detail_debt(self):
        result = s.probe(("SUTD", SUTD), fetch=lambda url:
                         LIST if url == SUTD else "<p>Job Req ID: 2210</p>")
        self.assertEqual(result["status"], "PARTIAL_COVERAGE")
        self.assertEqual(result["detail_verified"], 0)
        self.assertEqual(len(result["errors"]), 1)

    def test_missing_explicit_exhaustion_does_not_claim_full_coverage(self):
        result = s.probe(("SUTD", SUTD), fetch=lambda url:
                         LIST.replace("Page 1 of 1", "Page 1 of 9") if url == SUTD else DETAIL)
        self.assertEqual(result["status"], "PARTIAL_COVERAGE")
        self.assertEqual(result["detail_verified"], 1)

    def test_hidden_script_text_cannot_fake_apply_control(self):
        detail = "<script>Apply now and Job Req ID: 2210</script><p>Research Associate</p>"
        r = s.probe(("SUTD", SUTD), fetch=lambda url: LIST if url == SUTD else detail)
        self.assertEqual(r["detail_verified"], 0)
        self.assertEqual(r["status"], "PARTIAL_COVERAGE")

    def test_non_official_host_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-official portal host"):
            s.fetch_html("https://thirdparty.example.com/search/")


if __name__ == "__main__":
    unittest.main()
