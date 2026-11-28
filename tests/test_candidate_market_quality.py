import unittest

from candidate_snapshot import build_candidate_snapshot


class CandidateMarketQualityTests(unittest.TestCase):
    def test_same_unlocated_identity_across_markets_is_one_unresolved_candidate(self):
        row = {"public_slug": "shared-ai", "title": "AI Engineer",
               "company": "Example", "location": "", "countries": ["SG", "CN", "MY"]}
        local = {"public_slug": "local-ai", "title": "AI Engineer",
                 "company": "Example", "location": "Singapore", "countries": ["SG"]}
        snapshot = build_candidate_snapshot(
            {"SG": [row, local], "CN": [row], "MY": [row]},
            "2026-11-28T00:00:00Z", "delta",
        )
        self.assertEqual(snapshot["counts"], {"SG": 1, "CN": 0, "MY": 0})
        self.assertEqual(snapshot["count"], 1)
        self.assertEqual([j["identity"] for j in snapshot["candidates"]], ["local-ai"])
        unresolved = snapshot["unassigned_candidates"]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["identity"], "shared-ai")
        self.assertEqual(unresolved[0]["matched_markets"], ["SG", "CN", "MY"])
        self.assertEqual(unresolved[0]["market"], "UNVERIFIED")
        self.assertEqual(unresolved[0]["countries"], ["SG", "CN", "MY"])

    def test_distinct_requisitions_and_single_market_unknown_are_preserved(self):
        row = {"title": "AI Engineer", "company": "Example", "location": ""}
        snapshot = build_candidate_snapshot(
            {"SG": [dict(row, public_slug="sg-role")],
             "CN": [dict(row, public_slug="cn-role")]},
            "2026-11-28T00:00:00Z", "coldstart",
        )
        self.assertEqual(snapshot["count"], 2)
        self.assertEqual(snapshot["unassigned_candidates"], [])

    def test_explicit_location_is_not_discarded(self):
        row = {"public_slug": "shared-ai", "title": "AI Engineer",
               "company": "Example", "location": "Singapore and Beijing"}
        snapshot = build_candidate_snapshot(
            {"SG": [row], "CN": [row]}, "2026-11-28T00:00:00Z", "delta",
        )
        self.assertEqual(snapshot["count"], 2)
        self.assertEqual(snapshot["unassigned_candidates"], [])
