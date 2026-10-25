import unittest

import firehose_fetch as firehose
import freehire_fetch as worker


class PolicyRegressionTests(unittest.TestCase):
    def tearDown(self):
        if hasattr(worker, "MARKET_CATEGORY_SHARDS"):
            worker.MARKET_CATEGORY_SHARDS = {}
        worker.DEFAULT_CATEGORIES = (
            "backend",
            "fullstack",
            "data_engineering",
            "ml_ai",
            "ai_engineering",
            "solutions_engineering",
            "devops",
            "sre",
        )
        worker.BOOTSTRAP_EMIT_DAYS = 7

    def test_senior_title_is_flag_not_hard_drop(self):
        hard_drop, flags = worker.machine_flags(
            {"title": "Senior AI Engineer", "enrichment": {}}
        )

        self.assertFalse(hard_drop)
        self.assertIn("senior_title_hint", flags)
        self.assertNotIn("title_hard_drop", flags)

    def test_mature_titles_and_intern_remain_hard_drops(self):
        for title in (
            "Staff AI Engineer",
            "Principal Software Engineer",
            "Lead Backend Engineer",
            "Engineering Manager",
            "Software Engineer Intern",
        ):
            with self.subTest(title=title):
                hard_drop, flags = worker.machine_flags(
                    {"title": title, "enrichment": {}}
                )
                self.assertTrue(hard_drop)
                self.assertIn("title_hard_drop", flags)

    def test_firehose_configures_four_sg_engineering_shards(self):
        firehose.configure_worker()

        self.assertTrue(hasattr(worker, "MARKET_CATEGORY_SHARDS"))
        shards = worker.MARKET_CATEGORY_SHARDS["SG"]
        self.assertEqual(len(shards), 4)
        union = {category for shard in shards for category in shard}
        self.assertEqual(union, set(firehose.BROAD_CATEGORIES))
        self.assertNotIn("developer_relations", union)
        self.assertNotIn("technical_writing", union)

    def test_sg_sharded_fetch_unions_and_dedupes_results(self):
        worker.MARKET_CATEGORY_SHARDS = {
            "SG": (
                ("backend",),
                ("qa",),
            )
        }
        calls = []

        def fake_fetch(params):
            calls.append(dict(params))
            category = params["category"]
            if category == "backend":
                data = [
                    {"public_slug": "backend-only"},
                    {"public_slug": "shared"},
                ]
            elif category == "qa":
                data = [
                    {"public_slug": "shared"},
                    {"public_slug": "qa-only"},
                ]
            else:
                data = []
            return {
                "data": data,
                "meta": {"total": len(data), "limit": 2, "offset": 0},
            }

        jobs = worker.fetch_market(
            fake_fetch,
            country="SG",
            mode="full",
            max_rows=2,
            page_size=2,
        )

        self.assertEqual(
            [job["public_slug"] for job in jobs],
            ["backend-only", "shared", "qa-only"],
        )
        self.assertEqual([call["category"] for call in calls], ["backend", "qa"])


if __name__ == "__main__":
    unittest.main()
