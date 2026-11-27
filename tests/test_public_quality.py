import unittest
from datetime import datetime, timezone
from public_quality import build, clean_text, collect
from tempfile import TemporaryDirectory
from pathlib import Path
import json

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
        self.assertEqual(clean_text("AI Engineer (R&D)"),"AI Engineer (R&D)")
        self.assertEqual(clean_text("大模型编排调度工程师（训练&推理方向）"),"大模型编排调度工程师（训练&推理方向）")

    def test_unknown_urls_preserved_without_unsafe_fuzzy_merge(self):
        rows=[dict(source="other",url="https://example.com/job?id="+i,title="Engineer",company="Example")
              for i in ("1","2")]
        jobs,_=build(rows,NOW)
        self.assertEqual(len(jobs),2)

    def test_route_evidence_is_exact_title_and_time_bound(self):
        url="https://jobs.ashbyhq.com/example/12345678-1234-1234-1234-123456789abc"
        row=dict(source="official-ats",url=url,title="AI Engineer",company="Example",market="SG")
        probes=[dict(url=url,title="AI Engineer",status="API_LISTED",checked_at=NOW.isoformat(),evidence_source="api"),
                dict(url=url,title="Other Engineer",status="LIVE_FORM",checked_at=NOW.isoformat(),evidence_source="browser")]
        jobs,audit=build([row],NOW,probes)
        self.assertEqual([p["status"] for p in jobs[0]["application_evidence"]],["API_LISTED"])
        self.assertEqual(audit["fresh_browser_evidence"],0)
        self.assertEqual(audit["fresh_api_evidence"],1)

    def test_source_health_and_missing_body_not_mistaken_for_fresh_jd(self):
        url="https://jobs.ashbyhq.com/example/12345678-1234-1234-1234-123456789abc"
        item=dict(key="example|ashby|123",url=url,title="AI Engineer",company="Example",evidence="full_jd")
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            def put(rel,obj):
                path=root/rel; path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps(obj))
            put("feed/ats/markets/SG.json",{"jobs":[item]})
            put("feed/ats/jd/index.json",{"jobs":[dict(item,part="SG-000.json",description_truncated=False,checked_at=NOW.isoformat())]})
            put("feed/ats/health.json",{"boards":{"ashby:example":{"status":"FAILED"}}})
            put("feed/cn-native/health.json",{"checked_at":NOW.isoformat(),"liepin":{"status":"PARTIAL_COVERAGE","jobs":0}})
            put("feed/cn-native/liepin-raw.json",{"generatedAt":"2026-11-27T00:00:00Z","jobs":[dict(url="https://www.liepin.com/job/12345678.shtml",title="Engineer",company="Example")]})
            rows,reads,health,probes=collect(root)
            jobs,audit=build(rows,NOW,probes)
            self.assertEqual(audit["fresh_full_jd"],0)
            self.assertEqual(health["ats"]["ashby:example"]["status"],"FAILED")
            self.assertEqual(next(x for x in rows if x["source"]=="liepin")["discovery_freshness"],"RETAINED_UNVERIFIED")
            self.assertEqual(reads["feed/ats/markets/SG.json"],"FILE_READ")

    def test_invalid_and_conflicting_records_are_diagnosable(self):
        rows=[dict(source="example",title="Engineer",url="not a url"),
              dict(source="example",title="Engineer",url="https://example.com/jobs")]
        jobs,audit=build(rows,NOW)
        self.assertEqual(audit["invalid_details"][0]["reason"],"INVALID_URL")
        self.assertEqual(jobs[0]["identity_quality"],"UNVERIFIED_URL")
        self.assertTrue(jobs[0]["content_fingerprint"])

    def test_jd_shard_relocation_does_not_change_content_fingerprint(self):
        row=dict(source="official-ats",title="AI Engineer",url="https://jobs.ashbyhq.com/example/12345678-1234-1234-1234-123456789abc",
                 company="Example",jd_kind="full_jd",jd_checked_at=NOW.isoformat(),
                 jd_ref={"path":"feed/ats/jd/SG-000.json","sha256":"same"})
        a,_=build([row],NOW)
        b,_=build([dict(row,jd_ref={"path":"feed/ats/jd/SG-001.json","sha256":"same"})],NOW)
        self.assertEqual(a[0]["content_fingerprint"],b[0]["content_fingerprint"])

    def test_published_api_evidence_is_parseable(self):
        path=Path(__file__).resolve().parents[1]/"feed/ats/api-liveness.json"
        if path.exists():
            self.assertIsInstance(json.loads(path.read_text())["jobs"],list)

if __name__=="__main__":
    unittest.main()
