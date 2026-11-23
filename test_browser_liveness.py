"""No-browser, no-network regression tests for public Playwright liveness gate."""
import unittest

from browser_liveness import assess_page, safe_public_role, select_targets

SG = ("https://ntu.wd3.myworkdayjobs.com/en-US/Careers/job/"
      "NTU-Main-Campus-Singapore/Research-Associate--Computer-Science---"
      "Cyber-Security---Artificial-Intelligence-_R00024958")
CN = "https://dptechnology.jobs.feishu.cn/index/position/7584808203012213033/detail"
ASHBY = "https://jobs.ashbyhq.com/endex/5c6b360f-94ea-404e-8929-def23aaa0a9a"


class PublicLivenessTests(unittest.TestCase):
    def test_allow_official_exact_urls_and_deny_fake_or_bad_links(self):
        for url in (SG, CN, ASHBY):
            self.assertTrue(safe_public_role(url), url)
        for url in (
            "http://jobs.ashbyhq.com/endex/5c6b360f-94ea-404e-8929-def23aaa0a9a",
            "https://jobs.ashbyhq.com.evil.org/endex/5c6b360f-94ea-404e-8929-def23aaa0a9a",
            "https://jobs.ashbyhq.com:444/endex/5c6b360f-94ea-404e-8929-def23aaa0a9a",
            "https://jobs.ashbyhq.com/",
            "https://username:secret@jobs.ashbyhq.com/endex/5c6b360f-94ea-404e-8929-def23aaa0a9a",
            "https://example.com/my/job",
        ):
            self.assertFalse(safe_public_role(url), url)

    def test_apply_is_signal_not_verified_form(self):
        status, reason = assess_page(requested_url=SG, final_url=SG,
                                     http_status=200, heading="Research Associate, Trustworthy LLM",
                                     body="Research Associate. Applications accepted.", apply_controls=1)
        self.assertEqual(status, "OPEN_SIGNAL_FORM_UNTESTED")
        self.assertIn("not submitted", reason)

    def test_explicit_closed(self):
        status, _ = assess_page(requested_url=CN, final_url=CN, http_status=200,
                                heading="LLM Algorithm Engineer",
                                body="This position is no longer accepting applications.",
                                apply_controls=1)
        self.assertEqual(status, "CLOSED_EXPLICIT")

    def test_403_404_and_lost_exact_id_never_claim_closed(self):
        for code in (403, 404):
            status, _ = assess_page(requested_url=SG, final_url=SG,
                                    http_status=code, heading="", body="", apply_controls=0)
            self.assertTrue(status.startswith("UNKNOWN_"))
        status, _ = assess_page(
            requested_url=CN,
            final_url="https://dptechnology.jobs.feishu.cn/index/position/7000000000000000000/detail",
            http_status=200, heading="Algorithm Engineer", body="Apply Now",
            apply_controls=1,
        )
        self.assertEqual(status, "UNKNOWN_REDIRECT")

    def test_200_generic_career_page_not_live(self):
        status, _ = assess_page(requested_url=SG, final_url=SG, http_status=200,
                                heading="Careers", body="Join us. Apply Now", apply_controls=1)
        self.assertEqual(status, "UNKNOWN_NO_ROLE_HEADING")

    def test_service_unavailable_and_form_absence(self):
        status, _ = assess_page(requested_url=ASHBY, final_url=ASHBY, http_status=200,
                                heading="Agent Engineer", body="Service Unavailable",
                                apply_controls=1)
        self.assertEqual(status, "UNKNOWN_BLOCKED")
        status, _ = assess_page(requested_url=ASHBY, final_url=ASHBY, http_status=200,
                                heading="Agent Engineer", body="Work on agents",
                                apply_controls=0)
        self.assertEqual(status, "UNKNOWN_NO_APPLY")

    def test_unsupported_browser_shell_is_not_an_open_job(self):
        status, _ = assess_page(
            requested_url=ASHBY, final_url=ASHBY, http_status=200,
            heading="Sorry, Internet Explorer 11 is no longer supported by SmartRecruiters",
            body="Sorry, Internet Explorer 11 is no longer supported by SmartRecruiters",
            apply_controls=0)
        self.assertEqual(status, "UNKNOWN_BLOCKED")

    def test_curated_plus_rotating_generic_feed_distinct_employers(self):
        config = {"version": 1, "targets": [{"market": "SG", "url": SG}]}
        feed = {"jobs": [
            {"url": ASHBY, "market": "SG", "title": "Agent Engineer", "company": "Endex"},
            {"url": "https://jobs.ashbyhq.com/endex/66666666-aaaa-bbbb-cccc-111111111111",
             "market": "SG", "title": "AI Engineer", "company": "Endex"},
            {"url": CN, "market": "CN", "title": "LLM Algorithm Engineer", "company": "DP Tech"},
            {"url": "https://jobs.ashbyhq.com/senior/77777777-aaaa-bbbb-cccc-111111111111",
             "market": "SG", "title": "Staff AI Engineer", "company": "Senior"},
        ]}
        targets = select_targets(config, feed, rotation=1, max_feed=2)
        self.assertEqual(len(targets), 3)
        self.assertEqual([x["market"] for x in targets], ["SG", "SG", "CN"])
        self.assertEqual(len({x["url"] for x in targets}), 3)

    def test_bad_config_rejected(self):
        with self.assertRaises(ValueError):
            select_targets({"version": 2, "targets": []}, {"jobs": []})


if __name__ == "__main__":
    unittest.main()
