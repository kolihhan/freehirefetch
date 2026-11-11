"""CN first-party job detail production contract (source-only, no applicant data)."""
import json
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import hydrate_cn_jobpro_jd as jd

TENCENT = {
    "post_id": "1282707398326592512",
    "title": "AI全栈工程师",
    "apply_url": "https://join.qq.com/post_detail.html?postid=1282707398326592512",
}
BYTE = {
    "post_id": "7668351902195009845",
    "title": "Agent后端开发工程师",
    "apply_url": "https://jobs.bytedance.com/campus/position/7668351902195009845/detail",
}


class JDProducerTests(unittest.TestCase):
    def test_exact_official_url_and_no_query_id_collapse(self):
        self.assertEqual(jd.official_url("tencent", TENCENT), TENCENT["apply_url"])
        self.assertEqual(jd.official_url("bytedance", BYTE), BYTE["apply_url"])
        self.assertIsNone(jd.official_url("tencent", {
            **TENCENT, "apply_url": "https://join.qq.com/post_detail.html?postid=1282707398326592513"}))
        self.assertIsNone(jd.official_url("tencent", {
            **TENCENT, "apply_url": "https://join.qq.com.evil.example/post_detail.html?postid=1282707398326592512"}))
        self.assertIsNone(jd.official_url("tencent", {
            **TENCENT, "apply_url": "https://join.qq.com/post_detail.html"}))
        self.assertIsNone(jd.official_url("bytedance", {
            **BYTE, "apply_url": "https://jobs.bytedance.com/campus/position/7668351902195009846/detail"}))

    def test_choose_genuine_distinct_employer_roles_not_just_20_per_company(self):
        doc = [{"company": "tencent", "positions": [TENCENT, TENCENT,
                {**TENCENT, "post_id": "1282707398326592513",
                 "apply_url": "https://join.qq.com/post_detail.html?postid=1282707398326592513"},
                {"post_id": "1282707398326592514", "title": "销售",
                 "apply_url": "https://join.qq.com/post_detail.html?postid=1282707398326592514"}]},
               {"company": "bytedance", "positions": [BYTE]}]
        selected = jd.choose_candidates([{"results": doc}], limit=4, per_company=2)
        self.assertEqual(len(selected), 3)
        self.assertEqual({x["company_key"] for x in selected}, {"bytedance", "tencent"})

    def test_prioritize_agent_backend_and_research_over_ai_operations(self):
        weak = {"post_id": "7683513087236688181", "title": "AI数据运营（视频通话）",
                "apply_url": "https://jobs.bytedance.com/campus/position/7683513087236688181/detail"}
        strong = {"post_id": "7628143430628919557",
                  "title": "面向大模型与AI Agent的AI云原生基础设施关键技术研究-SRE",
                  "apply_url": "https://jobs.bytedance.com/campus/position/7628143430628919557/detail"}
        agibot = {"post_id": "7657507612519483702", "title": "语音大模型后端工程师",
                  "apply_url": "https://agirobot.jobs.feishu.cn/socialrecruitment/position/7657507612519483702/detail"}
        rows = jd.choose_candidates([{"results": [
            {"company": "bytedance", "positions": [weak, strong]},
            {"company": "agibot", "positions": [agibot]},
        ]}], limit=2)
        self.assertEqual({x["post_id"] for x in rows},
                         {"7628143430628919557", "7657507612519483702"})
        self.assertEqual(rows[0]["title"], strong["title"])
        self.assertEqual(rows[1]["title"], agibot["title"])
        self.assertEqual(jd.official_url("agibot", agibot), agibot["apply_url"])

    def test_detail_accept_requires_matching_company_id_title_url_and_both_jd_sections(self):
        item = {"company_key": "tencent", **TENCENT, "url": TENCENT["apply_url"]}
        detail = {"ok": True, "post_id": TENCENT["post_id"], "title": TENCENT["title"],
                  "apply_url": TENCENT["apply_url"],
                  "description": "为研发团队开发高质量的 Agent / RAG 工具与工程平台。" * 10,
                  "requirements": "计算机相关本科以上学历，了解 Python 后端及大模型应用，具备协作能力。" * 10}
        row = jd.detail_evidence(item, detail, "2026-11-11T04:00:00Z")
        self.assertEqual(row["job_id"], TENCENT["post_id"])
        self.assertEqual(row["url"], TENCENT["apply_url"])
        self.assertTrue(row["full_jd_complete"])
        self.assertIn("Agent", row["description_text"])
        self.assertNotIn("applicant", row)
        self.assertIsNone(jd.detail_evidence(item, {**detail,"post_id":"1282707398326592513"},
                                              "2026-11-11T04:00:00Z"))
        self.assertIsNone(jd.detail_evidence(item, {**detail,"requirements":""},
                                              "2026-11-11T04:00:00Z"))
        self.assertIsNone(jd.detail_evidence(item, {**detail,"title":"Sales Director"},
                                              "2026-11-11T04:00:00Z"))

    def test_run_fail_closed_and_finite_failure_reports(self):
        data = [{"results": [{"company": "tencent", "positions": [TENCENT]}]}]
        def bad(*args, **kwargs):
            return {"ok": False, "message": "not reachable"}
        out = jd.hydrate(data, detail_fetch=bad, limit=3)
        self.assertEqual(out["jobs"], [])
        self.assertEqual(out["attempted"], 1)
        self.assertEqual(out["failed"], 1)
        self.assertEqual(out["source"], "jobpro-public-employer-detail")
        self.assertNotIn("candidate_profile", json.dumps(out))


if __name__ == "__main__":
    unittest.main()
