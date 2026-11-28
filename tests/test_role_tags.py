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

    def test_duties_not_qualification_or_employer_branding(self):
        text="Our company develops LLMs. Responsibilities: Build Android screens. Requirements: Familiarity with building RAG systems."
        tags=tag_role("Android Engineer - AI Finance Agent",text,"FIRST_PARTY_FULL")
        self.assertEqual(tags["ai_depth"],"AI_PRODUCT_CONTEXT_ONLY")
        tags=tag_role("Backend Software Engineer","Responsibilities: Develop LLM agents. Requirements: Python.","FIRST_PARTY_FULL")
        self.assertEqual(tags["role_family"],"AI_ENGINEERING")

    def test_unknown_title_with_explicit_duties(self):
        tags=tag_role("Algorithm Specialist","Responsibilities: Develop RAG systems.","FIRST_PARTY_FULL")
        self.assertEqual(tags["role_family"],"AI_ENGINEERING")

    def test_real_capco_range_and_local_work_restriction(self):
        tags=tag_role("AI Engineer - All Levels","Experience and Qualifications: 3–12 years of professional experience in AI/ML engineering. ELIGIBILITY TO WORK IN SG: Only Singapore Citizens and Singapore Permanent Residents (PRs) will be considered. Employment Pass sponsorship is not available.","FIRST_PARTY_FULL")
        self.assertEqual(tags["experience_min_mentions"],[3])
        self.assertTrue(tags["work_location_or_authorization_restriction"])

    def test_explicit_local_residence_and_doctoral_title(self):
        tags=tag_role("Applied AI Engineer","Applicants should already be based in Singapore.","FIRST_PARTY_FULL")
        self.assertTrue(tags["work_location_or_authorization_restriction"])
        self.assertEqual(tag_role("AI Engineer Graduate (PhD)")["degree"],"PHD_TITLE_SIGNAL")

    def test_community_operations_not_model_research(self):
        tags=tag_role("技术社区运营（大模型评测方向）",
            "岗位职责：负责评测社区开展相关社群活动，负责活跃社群用户增加社群的粘性，同时对大模型评测进行宣传。",
            "FIRST_PARTY_FULL")
        self.assertEqual(tags["role_family"],"NON_TECHNICAL")
        self.assertEqual(tags["ai_depth"],"NOT_CORE_AI")
        self.assertEqual(tag_role("Community Manager, AI Agents")["role_family"],"NON_TECHNICAL")
        self.assertEqual(tag_role("AI Platform Operations Engineer","Responsibilities: Develop RAG systems.")["ai_depth"],"AI_SYSTEM_DEVELOPMENT")

    def test_qualifications_without_responsibilities_do_not_establish_ai_duties(self):
        for heading in ("Requirements:", "What you'll bring:", "任职资格："):
            tags=tag_role("Backend Engineer", "Maintain backend APIs. "+heading+" Develop LLM agents.", "FIRST_PARTY_FULL")
            self.assertEqual(tags["role_family"],"SOFTWARE_ENGINEERING")
            self.assertNotEqual(tags["ai_depth"],"AI_SYSTEM_DEVELOPMENT")

    def test_bare_contract_metadata_is_not_permanent_or_unknown(self):
        for employment in ("Contract","FixedTerm","合同制"):
            self.assertEqual(tag_role("AI Engineer",metadata={"employment_type":employment})["employment"],"CONTRACT_SIGNAL")
        self.assertEqual(tag_role("Smart Contract Engineer",metadata={"employment_type":"Full-time"})["employment"],"FULL_TIME_UNSPECIFIED_TERM")

if __name__=="__main__": unittest.main()
