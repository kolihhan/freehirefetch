import unittest
from cn_platform_collect import extract, source_host, extract_51job_json, rotated_spec, retain_observations, SOURCES, QUERY_ROTATION

class CNPlatformTests(unittest.TestCase):
    def test_exact_native_links_only(self):
        good = "https://www.zhaopin.com/jobdetail/CC466267010J40873443311.htm"
        found = extract([
            {"url":good+"?tracking=abc","title":"大模型研发工程师"},
            {"url":good,"title":"大模型研发工程师"},
            {"url":"https://www.zhaopin.com.evil.example/jobdetail/CC466267010J40873443311.htm","title":"大模型研发工程师"},
            {"url":"https://www.zhaopin.com/jobdetail/CC466267010J40873443312.htm","title":"大模型产品经理"},
            {"url":"https://www.zhaopin.com/jobdetail/CC466267010J40873443313.htm","title":"大模型实习生"},
            {"url":"https://sou.zhaopin.com/?kw=大模型","title":"大模型工程师"},
        ],"zhaopin.com")
        self.assertEqual(len(found),1)
        self.assertEqual(next(iter(found.values()))["url"],good)

    def test_source_domain_boundary(self):
        self.assertTrue(source_host("https://sou.zhaopin.com/","zhaopin.com"))
        self.assertFalse(source_host("https://sou.zhaopin.com.evil.example/","zhaopin.com"))
        self.assertFalse(source_host("https://evil.example@zhaopin.com/","zhaopin.com"))

    def test_structured_51job_requires_same_role_identity(self):
        item = {"jobId":"12345678","jobName":"大模型研发工程师","jobHref":"https://jobs.51job.com/shenzhen/12345678.html?x=1","companyName":"Example","jobAreaString":"深圳","workYearString":"1年","provideSalaryString":"20-30k"}
        doc = {"resultbody":{"job":{"items":[item,dict(item,jobId="87654321"),dict(item,jobName="大模型实习生"),dict(item,jobHref="https://example.com/shenzhen/12345678.html")]}}}
        result = extract_51job_json(doc)
        self.assertEqual(len(result),1)
        row = next(iter(result.values()))
        self.assertEqual(row["company"],"Example")
        self.assertEqual(row["location"],"深圳")
        self.assertEqual(row["url"],"https://jobs.51job.com/shenzhen/12345678.html")

    def test_structured_51job_rejects_unrecognized_schema(self):
        self.assertEqual(extract_51job_json({"message":"access denied"}),{})

    def test_native_queries_rotate_without_mutating_source_config(self):
        for source, spec in SOURCES.items():
            queries = []
            for n in range(1, len(QUERY_ROTATION)+1):
                domain, base, page_key, params = rotated_spec(source, n)
                self.assertEqual((domain, base, page_key), spec[:3])
                key = next(k for k in ("query","keyword","kw") if k in params)
                queries.append(params[key])
            self.assertEqual(tuple(queries), QUERY_ROTATION)
            self.assertEqual(rotated_spec(source, 1), rotated_spec(source, len(QUERY_ROTATION)+1))

    def test_retained_observation_preserves_timestamp_and_expires(self):
        url = "https://jobs.51job.com/shenzhen/12345678.html"
        previous = {"jobs":[{"url":url,"title":"大模型研发工程师","discovery_freshness":"OBSERVED_THIS_RUN"}]}
        report = {"jobs":[]}
        retain_observations(report, previous, "2026-11-28T05:00:00+00:00","2026-11-27T05:00:00+00:00")
        self.assertEqual(report["jobs"][0]["observed_at"],"2026-11-27T05:00:00+00:00")
        self.assertEqual(report["retained_count"],1)
        later = {"jobs":[]}
        retain_observations(later,report,"2026-12-05T05:00:00+00:00","2026-11-28T05:00:00+00:00")
        self.assertEqual(later["jobs"],[])
        fresh = {"jobs":[{"url":url,"title":"大模型研发工程师"}]}
        retain_observations(fresh,report,"2026-11-28T06:00:00+00:00","2026-11-28T05:00:00+00:00")
        self.assertEqual(fresh["jobs"][0]["observed_at"],"2026-11-28T06:00:00+00:00")
        self.assertEqual(fresh["retained_count"],0)
