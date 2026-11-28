"""CN first-party job detail production contract (source-only, no applicant data)."""
import json
import unittest
from tempfile import TemporaryDirectory
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
    def test_new_social_employer_routes_exact_and_canonical(self):
        for company, url, uid in (
            ("baichuan", "https://cq6qe6bvfr6.jobs.feishu.cn/baichuanzhaopin/position/7654879972347152650/detail", "7654879972347152650"),
            ("minimax", "https://vrfi1sk8a0.jobs.feishu.cn/379481/position/7681599148466571566/detail", "7681599148466571566"),
            ("meituan", "https://zhaopin.meituan.com/web/position/detail?jobUnionId=4933015251", "4933015251"),
        ):
            self.assertEqual(jd.official_url(company, {"post_id":uid, "apply_url":url}), url)
            self.assertIsNone(jd.official_url(company, {"post_id":uid[:-1]+"9", "apply_url":url}))
        self.assertEqual(jd.official_url("meituan", {
            "post_id":"4933015251", "apply_url":"https://zhaopin.meituan.com/web/position/detail?jobUnionId=4933015251&highlightType=social"}),
            "https://zhaopin.meituan.com/web/position/detail?jobUnionId=4933015251")
        self.assertIsNone(jd.official_url("meituan", {"post_id":"4933015251",
            "apply_url":"https://zhaopin.meituan.com.evil.example/web/position/detail?jobUnionId=4933015251"}))

    def test_exact_xiaohongshu_and_ant_routes(self):
        for company, uid, url in (
            ("xiaohongshu","22903","https://job.xiaohongshu.com/campus/position/22903"),
            ("antgroup","260908011960948","https://talent.antgroup.com/off-campus-position?positionId=260908011960948"),
        ):
            self.assertEqual(jd.official_url(company,{"post_id":uid,"apply_url":url}),url)
            self.assertIsNone(jd.official_url(company,{"post_id":"999999999999","apply_url":url}))
        self.assertIsNone(jd.official_url("antgroup",{"post_id":"260908011960948","apply_url":"https://talent.antgroup.com/off-campus-position"}))

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

    def test_generic_embedded_roles_do_not_consume_agent_jd_budget(self):
        generic = {
            "post_id": "7611757252383197491",
            "title": "嵌入式软件工程师",
            "apply_url": "https://agirobot.jobs.feishu.cn/socialrecruitment/position/7611757252383197491/detail",
        }
        agent = {
            "post_id": "7612980262242584886",
            "title": "Agent算法工程师",
            "apply_url": "https://agirobot.jobs.feishu.cn/socialrecruitment/position/7612980262242584886/detail",
        }
        selected = jd.choose_candidates(
            [{"results": [{"company": "agibot", "positions": [generic, agent]}]}],
            limit=10,
        )
        self.assertEqual([x["post_id"] for x in selected], [agent["post_id"]])

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

    def test_main_includes_agent_and_llm_source_batches(self):
        with TemporaryDirectory() as tmp:
            source_dir = Path(tmp)
            for keyword in ("ai", "backend", "swe", "agent", "llm"):
                (source_dir / f"jobpro-{keyword}.json").write_text(
                    json.dumps({"ok": True, "results": [
                        {"company": keyword, "positions": []}]}), encoding="utf-8")
            result = {"attempted": 0, "failed": 0, "checked_at": "test", "jobs": [],
                      "state": {"records": {}}, "newly_verified": 0, "cached_verified": 0,
                      "observed_distinct": 0, "coverage": "OBSERVED_BATCH_VERIFIED"}
            with patch.object(sys, "argv", ["hydrate_cn_jobpro_jd.py",
                                           "--source-dir", str(source_dir),
                                           "--output", str(source_dir / "out.json")]):
                with patch.object(jd, "hydrate", return_value=result) as mocked:
                    jd.main()
            inputs = mocked.call_args.args[0]
            self.assertEqual(len(inputs), 5)
            self.assertEqual({doc["results"][0]["company"] for doc in inputs},
                             {"ai", "backend", "swe", "agent", "llm"})

    def test_rotation_visits_unread_roles_then_retries_after_cooldown(self):
        positions = [{**TENCENT, "post_id": str(1282707398326592512 + i),
                      "apply_url": "https://join.qq.com/post_detail.html?postid=" + str(1282707398326592512 + i)}
                     for i in range(9)]
        data = [{"results": [{"company": "tencent", "positions": positions}]}]
        bad = lambda *args: {"ok": False}
        a = jd.hydrate(data, detail_fetch=bad, limit=6, now="2026-11-25T00:00:00Z")
        b = jd.hydrate(data, detail_fetch=bad, limit=6, history=a["state"]["records"], now="2026-11-25T03:00:00Z")
        self.assertEqual((a["attempted"], b["attempted"]), (6, 3))
        self.assertFalse({r["job_id"] for r in a["failures"]} & {r["job_id"] for r in b["failures"]})
        c = jd.hydrate(data, detail_fetch=bad, limit=6, history=b["state"]["records"], now="2026-11-25T12:00:00Z")
        self.assertEqual(c["attempted"], 6)

    def test_cache_preserves_original_timestamp_and_failed_refresh_is_not_live(self):
        data = [{"results": [{"company": "tencent", "positions": [TENCENT]}]}]
        detail = {"ok": True, **TENCENT, "description": "Agent RAG engineering. " * 12,
                  "requirements": "Python and LLM engineering. " * 12}
        a = jd.hydrate(data, detail_fetch=lambda *args: detail, now="2026-11-25T00:00:00Z")
        b = jd.hydrate(data, detail_fetch=lambda *args: self.fail("fresh cache refetched"),
                       history=a["state"]["records"], now="2026-11-25T03:00:00Z")
        self.assertEqual((b["attempted"], b["cached_verified"]), (0, 1))
        self.assertEqual(b["jobs"][0]["checked_at"], a["jobs"][0]["checked_at"])
        c = jd.hydrate(data, detail_fetch=lambda *args: {"ok": False},
                       history=b["state"]["records"], now="2026-11-26T01:00:00Z")
        self.assertEqual(c["jobs"], [])
        self.assertEqual(c["state"]["records"][jd.identity({"company_key": "tencent", **TENCENT})]["evidence"], a["jobs"][0])
        self.assertEqual(c["coverage"], "PARTIAL")

    def test_changed_identity_does_not_reuse_previous_evidence(self):
        data = [{"results": [{"company": "tencent", "positions": [TENCENT]}]}]
        detail = {"ok": True, **TENCENT, "description": "Agent RAG engineering. " * 12,
                  "requirements": "Python and LLM engineering. " * 12}
        a = jd.hydrate(data, detail_fetch=lambda *args: detail, now="2026-11-25T00:00:00Z")
        changed = {**TENCENT, "title": "LLM研究工程师"}
        b = jd.hydrate([{"results": [{"company": "tencent", "positions": [changed]}]}],
                       detail_fetch=lambda *args: detail, history=a["state"]["records"],
                       now="2026-11-25T03:00:00Z")
        self.assertEqual((b["attempted"], b["failed"], b["jobs"]), (1, 1, []))

    def test_detail_budget_excludes_explicit_sales_and_internships_without_dropping_listings(self):
        sales={**TENCENT,"post_id":"1282707398326592513","title":"大模型行业销售","apply_url":"https://join.qq.com/post_detail.html?postid=1282707398326592513"}
        intern={**TENCENT,"post_id":"1282707398326592514","title":"Agent开发实习生","apply_url":"https://join.qq.com/post_detail.html?postid=1282707398326592514"}
        data=[{"results":[{"company":"tencent","positions":[sales,intern,TENCENT]}]}]
        report=jd.hydrate(data,detail_fetch=lambda *args:{"ok":False},limit=10)
        self.assertEqual(report["observed_distinct"],3)
        self.assertEqual(report["technical_observed_distinct"],1)
        self.assertEqual(report["attempted"],1)
        self.assertEqual(report["failures"][0]["job_id"],TENCENT["post_id"])

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
