import unittest

import freehire_fetch as worker


class PolicyRegressionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
