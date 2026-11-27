import unittest
from datetime import datetime, timezone
from public_quality import build, clean_text

NOW = datetime(2026,11,28,tzinfo=timezone.utc)

class QualityTests(unittest.TestCase):
    def test_duplicate_market_query_not_location_proof(self):
        rows=[dict(source="freehire", market=m, public_slug="job-123",
                   source_url="https://freehire.me/api/v1/go/job-123?src=web",
                   title="AI Engineer", company="Example", location="", event_seq=5)
              for m in ("SG","CN","MY")]
        jobs, audit=build(rows,NOW)
        self.assertEqual(len(jobs),1)
        self.assertEqual(jobs[0]["observed_markets"],["CN","MY","SG"])
        self.assertEqual(jobs[0]["location_markets"],[])
        self.assertEqual(audit["duplicate_observations"],2)

    def test_exact_query_identity_and_aliases(self):
        base="https://zhaopin.meituan.com/web/position/detail?jobUnionId="
        rows=[dict(source="ats",market="CN",url=base+i,title="AI Engineer",company="Meituan")
              for i in ("4933015251","4933015252")]
        rows.append(dict(rows[0],source="proxy",url=rows[0]["url"]+"&tracking=1"))
        jobs,audit=build(rows,NOW)
        self.assertEqual(len(jobs),2)
        self.assertEqual(audit["duplicate_observations"],1)

    def test_conflicting_title_does_not_transfer_jd(self):
        url="https://jobs.ashbyhq.com/example/12345678-1234-1234-1234-123456789abc"
        rows=[dict(source="ats",url=url,title="AI Engineer",company="Example",market="SG"),
              dict(source="proxy",url=url,title="Data Scientist",company="Example",market="SG",
                   jd_kind="full_jd",jd_checked_at=NOW.isoformat(),jd_ref="example")]
        jobs,audit=build(rows,NOW)
        self.assertEqual(len(jobs),1)
        self.assertTrue(jobs[0]["identity_conflict"])
        self.assertFalse(jobs[0]["fresh_full_jd"])

    def test_stale_jd_and_html(self):
        row=dict(source="ats",market="SG",url="https://jobs.ashbyhq.com/example/12345678-1234-1234-1234-123456789abc",
                 title="AI Engineer",company="Example",location="Singapore",
                 jd_kind="full_jd",jd_checked_at="2026-11-20T00:00:00Z",jd_ref="example",
                 excerpt="<p>Build &amp; test</p><script>bad</script>")
        jobs,_=build([row],NOW)
        self.assertFalse(jobs[0]["fresh_full_jd"])
        self.assertEqual(jobs[0]["excerpt"],"Build & test")
        self.assertEqual(jobs[0]["location_markets"],["SG"])
        self.assertEqual(clean_text("<b>one</b><p>two</p>"),"one two")

    def test_unknown_urls_preserved_without_unsafe_fuzzy_merge(self):
        rows=[dict(source="other",url="https://example.com/job?id="+i,title="Engineer",company="Example")
              for i in ("1","2")]
        jobs,_=build(rows,NOW)
        self.assertEqual(len(jobs),2)

if __name__=="__main__":
    unittest.main()
