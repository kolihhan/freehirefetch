import unittest
from datetime import datetime, timezone
from public_quality import build
from role_tags import tag_role

class RoleTagTests(unittest.TestCase):
    def test_sales_is_not_ai_research(self):
        tags=tag_role("大模型与智能体行业销售","要求8年以上销售经验","FIRST_PARTY_FULL")
        self.assertEqual(tags["role_family"],"NON_TECHNICAL")
        self.assertEqual(tags["ai_depth"],"NOT_CORE_AI")

    def test_product_context_does_not_prove_ai_development(self):
        tags=tag_role("Mobile Engineer - AI Finance Agent","Build iOS interfaces and maintain mobile apps","FIRST_PARTY_FULL")
        self.assertEqual(tags["role_family"],"SOFTWARE_ENGINEERING")
        self.assertEqual(tags["ai_depth"],"AI_PRODUCT_CONTEXT_ONLY")

    def test_actual_ai_system_work(self):
        tags=tag_role("Backend Software Engineer","Develop LLM agents and implement RAG systems.","FIRST_PARTY_FULL")
        self.assertEqual(tags["ai_depth"],"AI_SYSTEM_DEVELOPMENT")
        self.assertEqual(tags["text_evidence_grade"],"FIRST_PARTY_FULL")

    def test_degree_preference_and_requirement_are_not_same(self):
        tags=tag_role("大模型算法研究员","硕士及以上学历，博士优先。","FIRST_PARTY_FULL")
        self.assertEqual(tags["degree"],"MASTER_MIN_SIGNAL")
        self.assertTrue(tags["phd_preferred_signal"])
        tags=tag_role("AI Engineer","我们正在寻找优秀的博士毕业生加入团队。","THIRD_PARTY_TEXT")
        self.assertEqual(tags["degree"],"PHD_REQUIRED_SIGNAL")
        self.assertEqual(tags["text_evidence_grade"],"THIRD_PARTY_TEXT")

    def test_hidden_internship_and_explicit_experience(self):
        tags=tag_role("大模型算法工程师","实习时长：每周 ≥ 4 天，稳定 6 个月以上。","FIRST_PARTY_FULL")
        self.assertEqual(tags["employment"],"INTERNSHIP")
        tags=tag_role("AI Engineer","具备 3 年及以上软件研发经验。","FIRST_PARTY_FULL")
        self.assertEqual(tags["experience_min_mentions"],[3])
        self.assertEqual(tag_role("AI Engineer","Our company has 20 years of history.")["experience_min_mentions"],[])
        self.assertEqual(tag_role("AI Engineer","3+ years experience preferred.")["experience_min_mentions"],[])

    def test_non_ai_research_and_unknown_not_rejected(self):
        tags=tag_role("Research Assistant","Conduct textile fabrication and materials characterization.","FIRST_PARTY_PARTIAL")
        self.assertEqual(tags["role_family"],"OTHER_RESEARCH")
        self.assertEqual(tag_role("Research Assistant")["degree"],"UNKNOWN")
        self.assertEqual(tag_role("Research Assistant")["role_family"],"RESEARCH_UNSPECIFIED")

    def test_cohort_and_full_time_not_permanent(self):
        tags=tag_role("大模型算法工程师-2027届校招",metadata={"employment_type":"FullTime"})
        self.assertEqual(tags["graduation_cohorts"],["2027"])
        self.assertEqual(tags["employment"],"FULL_TIME_UNSPECIFIED_TERM")

    def test_projection_does_not_drop_or_transfer_conflicting_text(self):
        url="https://jobs.ashbyhq.com/example/12345678-1234-1234-1234-123456789abc"
        rows=[dict(source="official-ats",title="Software Engineer",url=url,company="Example"),
              dict(source="market-api",title="AI Engineer",url=url,company="Example",
                   _tag_text="博士毕业生加入团队",_tag_grade="THIRD_PARTY_TEXT")]
        jobs,audit=build(rows,datetime(2026,11,28,tzinfo=timezone.utc))
        self.assertEqual(len(jobs),1)
        self.assertTrue(jobs[0]["role_tags"]["identity_conflict"])
        self.assertEqual(jobs[0]["role_tags"]["degree"],"UNKNOWN")
        self.assertEqual(audit["valid_observations"],2)

if __name__=="__main__": unittest.main()
