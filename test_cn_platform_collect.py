import unittest
from cn_platform_collect import extract, source_host, extract_51job_json

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
