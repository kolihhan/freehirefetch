import unittest
from cn_platform_collect import extract, source_host

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
