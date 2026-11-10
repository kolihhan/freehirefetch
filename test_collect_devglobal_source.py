import importlib.util
from pathlib import Path
import unittest

P=Path(__file__).parent/"collect_devglobal_source.py"
spec=importlib.util.spec_from_file_location("devglobal_collector",P)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class DevGlobalTests(unittest.TestCase):
    def test_organization_field_maps_company_name(self):
        rows=m.parse_roles({"jobs":[{"id":174081606,"title":"Applied AI Engineer, Codex","organization":"OpenAI","location":"Singapore"}]},"SG")
        self.assertEqual(rows[0]["company"],"OpenAI")

    def test_realistic_sg_titles_are_screened_without_marking_eligibility(self):
        raw={"jobs":[
            {"id":174081606,"title":"Applied AI Engineer, Codex","company":"OpenAI","location":"Singapore"},
            {"id":2,"title":"AI Deployment Manager - Builder","company":"A","location":"Singapore"},
            {"id":3,"title":"Senior AI Engineer","company":"A","location":"Singapore"},
            {"id":4,"title":"AI Engineer","company":"A","location":"United States"},
            {"id":5,"title":"LLM Research Engineer","company":"A","location":"Singapore"},
            {"id":6,"title":"Business Operations Lead","company":"OpenAI","location":"Singapore"},
        ]}
        rows=m.parse_roles(raw,"SG")
        self.assertEqual({r["source_id"] for r in rows},{"174081606","5"})
        self.assertTrue(all(r["exact_jd_unverified"] for r in rows))
        self.assertEqual(rows[0]["url"],"https://devglobaljobs.com/jobs/detail/174081606")
    def test_truncated_second_page_not_reported_exhausted(self):
        rows=[{"id":i+100000,"title":"AI Engineer","company":"A","location":"Singapore"} for i in range(50)]
        def fetch(url):
            return {"jobs":rows}
        r=m.scan("SG",fetch)
        self.assertEqual(r["coverage"],"PARTIAL_COVERAGE")
        self.assertEqual(len(r["pages"]),2)
        self.assertEqual(len(r["items"]),50)
    def test_empty_source_is_not_invented(self):
        r=m.scan("MY",lambda u:{"jobs":[]})
        self.assertEqual(r["items"],[])
        self.assertEqual(r["coverage"],"BOUNDED_SOURCE_END")
    def test_failed_second_page_preserves_page_one(self):
        def fetch(url):
            if "offset=50" in url:raise ConnectionError("source timeout")
            return {"jobs":[{"id":i+100000,"title":"AI Engineer","location":"Singapore","company":"A"} for i in range(50)]}
        r=m.scan("SG",fetch)
        self.assertEqual(len(r["pages"]),1)
        self.assertEqual(len(r["items"]),50)
        self.assertEqual(r["failed_pages"][0]["offset"],50)
        self.assertEqual(r["coverage"],"PARTIAL_COVERAGE")
if __name__=="__main__":unittest.main()
