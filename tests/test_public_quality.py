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

    def test_unassigned_candidate_is_retained_with_market_facets_not_location(self):
        row = dict(market="UNVERIFIED", matched_markets=["SG", "CN", "MY"],
                   countries=["SG", "CN", "MY"], public_slug="shared-ai",
                   source_url="https://freehire.me/api/v1/go/shared-ai?src=web",
                   title="AI Engineer", company="Example", location="")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "feed/candidates.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"candidates": [], "unassigned_candidates": [row]}))
            rows, _, _, probes = collect(root)
            jobs, audit = build(rows, NOW, probes)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["observed_markets"], ["CN", "MY", "SG"])
        self.assertEqual(jobs[0]["location_markets"], [])
        self.assertEqual(jobs[0]["location_status"], "UNRESOLVED")
        self.assertEqual(audit["source_observations"]["freehire"], 1)

    def test_devglobal_source_visible_but_not_first_party_jd_or_live_apply(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "feed/devglobal"
            base.mkdir(parents=True)
            observed = "2026-11-27T20:00:00+00:00"
            item = dict(market="SG", source_id="180952401",
                        url="https://devglobaljobs.com/jobs/detail/180952401",
                        title="AI Agent Engineer", company="Example", location="Singapore")
            (base / "devglobal-sg-candidates.json").write_text(json.dumps(
                dict(market="SG", observed_at=observed, items=[item],
                     source_credit="Powered by Dev Global Jobs")))
            (base / "health.json").write_text(json.dumps(
                dict(SG=dict(coverage="PARTIAL_COVERAGE", pages=0, failed_pages=1,
                             observed_at="2026-11-28T00:00:00+00:00"))))
            rows, reads, health, probes = collect(root)
            jobs, audit = build(rows, NOW, probes)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(audit["source_observations"]["devglobal"], 1)
            self.assertEqual(jobs[0]["identity_quality"], "UNVERIFIED_URL")
            self.assertFalse(jobs[0]["fresh_full_jd"])
            self.assertEqual(jobs[0]["application_evidence"], [])
            obs = jobs[0]["observations"][0]
            self.assertEqual(obs["discovery_freshness"], "RETAINED_UNVERIFIED")
            self.assertEqual(obs["observed_at"], observed)
            self.assertEqual(obs["source_credit"], "Powered by Dev Global Jobs")
            self.assertEqual(health["devglobal"]["SG"]["pages"], 0)

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

    def test_cross_company_overlap_is_review_only_not_merge(self):
        body=" ".join("Develop anonymization pipeline component %d for rare identifiers and evaluate privacy leakage under adversarial conditions." % n for n in range(40))
        rows=[dict(source="official-ats",url="https://job-boards.greenhouse.io/"+owner+"/jobs/"+uid,
                   title=title,company=owner,location=location,market="SG",
                   _tag_text=text,_tag_grade="FIRST_PARTY_FULL")
              for owner,uid,title,location,text in (
                  ("agencyone","100","Research Engineer, Privacy","Singapore",body),
                  ("agencytwo","200","Research Engineer, Privacy (Singapore Time)","Singapore",body+" Other information"),
                  ("agencythree","300","Research Engineer, Privacy","Beijing",body),
                  ("agencyfour","400","Senior Research Engineer, Privacy","Singapore",body),
                  ("agencyfive","500","Research Engineer, Privacy","Singapore"," ".join("Manage tax compliance document %d and payroll accounts under different regulatory frameworks." % n for n in range(20))))]
        jobs,audit=build(rows,NOW)
        self.assertEqual(len(jobs),5)
        self.assertEqual(audit["possible_duplicate_pairs"],1)
        self.assertEqual(audit["possible_duplicate_roles"],2)
        self.assertEqual(audit["duplicate_observations"],0)
        by_company={j["company"]:j for j in jobs}
        self.assertEqual(by_company["agencyone"]["duplicate_review"][0]["other_id"],by_company["agencytwo"]["id"])
        self.assertEqual(by_company["agencytwo"]["duplicate_review"][0]["status"],"POSSIBLE_DUPLICATE_REVIEW")
        self.assertEqual(by_company["agencythree"]["duplicate_review"],[])
        self.assertEqual(by_company["agencyfour"]["duplicate_review"],[])
        self.assertEqual(by_company["agencyfive"]["duplicate_review"],[])

if __name__=="__main__":
    unittest.main()
