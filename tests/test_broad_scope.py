import unittest

import firehose_fetch as firehose
import freehire_fetch as worker


class BroadScopeTests(unittest.TestCase):
    def tearDown(self):
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
        worker.MARKET_CATEGORY_SHARDS = {}
        worker.BOOTSTRAP_EMIT_DAYS = 7

    def test_firehose_enables_broad_early_career_engineering_categories(self):
        firehose.configure_worker()
        required = {
            "software_engineering",
            "backend",
            "frontend",
            "fullstack",
            "mobile",
            "data_engineering",
            "data_science",
            "data_analytics",
            "ml_ai",
            "ai_engineering",
            "qa",
            "security",
            "solutions_engineering",
            "devops",
            "sre",
            "network_engineering",
        }
        self.assertEqual(set(worker.DEFAULT_CATEGORIES), required)
        self.assertEqual(len(worker.MARKET_CATEGORY_SHARDS["SG"]), 4)
        shard_union = {
            category
            for shard in worker.MARKET_CATEGORY_SHARDS["SG"]
            for category in shard
        }
        self.assertEqual(shard_union, required)
        params = worker.build_params("SG", "delta", 0)
        self.assertEqual(set(params["category"].split(",")), required)
        self.assertNotIn("developer_relations", required)
        self.assertNotIn("technical_writing", required)

    def test_firehose_bootstrap_surfaces_30_days_of_new_scope(self):
        firehose.configure_worker()
        self.assertEqual(worker.BOOTSTRAP_EMIT_DAYS, 30)


if __name__ == "__main__":
    unittest.main()
