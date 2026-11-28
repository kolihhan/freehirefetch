"""Regression tests for open-world ATS board discovery (no network)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import ats_discovery as ats


class BoardDiscoveryTests(unittest.TestCase):
    def test_exact_urls_only(self):
        uid = "a3d52889-1c3b-4913-86a9-37381ba464e7"
        self.assertEqual(ats.board_seed("https://job-boards.greenhouse.io/Acme/jobs/123"), ("greenhouse", "Acme"))
        self.assertEqual(ats.board_seed("https://jobs.ashbyhq.com/ACME/" + uid), ("ashby", "ACME"))
        self.assertEqual(ats.board_seed("https://jobs.lever.co/newco/" + uid + "/apply"), ("lever", "newco"))
        self.assertEqual(ats.board_seed("https://jobs.smartrecruiters.com/Acme/744000123456789-role"), ("smartrecruiters", "Acme"))
        for url in ("https://job-boards.greenhouse.io/acme", "https://evil.example/acme/jobs/123",
                    "https://user@jobs.ashbyhq.com/acme/" + uid,
                    "https://jobs.ashbyhq.com:444/acme/" + uid,
                    "http://jobs.ashbyhq.com/acme/" + uid,
                    "https://jobs.ashbyhq.com/acme/not-a-role",
                    "https://job-boards.greenhouse.io/../jobs/123"):
            self.assertIsNone(ats.board_seed(url), url)

    def test_aggregator_redirect_does_not_hide_exact_employer_route(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "feed/market-api/SG.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"jobs": [
                {"source_url": "https://freehire.me/jobs/example", "url": "https://job-boards.greenhouse.io/Alt/jobs/123",
                 "location": "Singapore"},
                {"url": "https://example.invalid/listing/456", "apply_url": "https://job-boards.greenhouse.io/Apply/jobs/456",
                 "location": "Singapore"},
                {"source_url": "https://example.invalid/redirect", "url": "https://evil.example/No/jobs/789",
                 "location": "Singapore"}
            ]}))
            _, state = ats.discover_boards(root, [], "2026-11-28T03:00:00+00:00")
            self.assertEqual(set(state["boards"]), {"greenhouse:alt", "greenhouse:apply"})
            self.assertEqual(state["boards"]["greenhouse:alt"]["seed_url"],
                             "https://job-boards.greenhouse.io/Alt/jobs/123")

    def test_rotation_and_known_owner_dedupe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "feed/market-api/SG.json"
            path.parent.mkdir(parents=True)
            def row(slug, location="Singapore"):
                return {"url": "https://job-boards.greenhouse.io/" + slug + "/jobs/123",
                        "location": location, "company": "Unverified company label"}
            path.write_text(json.dumps({"jobs": [row("Known"), row("Alpha"), row("alpha"),
                                                  row("Beta"), row("NY", "New York")]}))
            configured = [{"ats": "greenhouse", "slug": "known"}]
            clock = "2026-11-28T03:00:00+00:00"
            selected, state = ats.discover_boards(root, configured, clock, limit=1)
            self.assertEqual(len(state["boards"]), 2)
            self.assertEqual(state["selected"], ["greenhouse:alpha"])
            self.assertEqual(state["deferred"], ["greenhouse:beta"])
            self.assertEqual(selected[0]["company"], "Alpha")
            self.assertEqual(set(selected[0]["markets"]), set(ats.REGIONS))
            self.assertEqual(selected[0]["seed_source"], "feed/market-api/SG.json")
            raw = {"id": "123", "title": "AI Engineer", "location": "Singapore",
                   "url": "https://job-boards.greenhouse.io/Alpha/jobs/123",
                   "description": "Develop and evaluate LLM agents"}
            with patch.object(ats, "listing", return_value=[raw]):
                result = ats.run(root, selected, clock=clock, discovery=state)
            self.assertEqual(result["jobs"], 1)
            self.assertEqual(result["health"]["boards"]["greenhouse:beta"]["status"], "DEFERRED_ROTATION")
            self.assertTrue(result["health"]["complete"])  # attempted boards, not full registry
            later = "2026-11-28T07:00:00+00:00"
            selected, state = ats.discover_boards(root, configured, later, limit=1)
            self.assertEqual(state["selected"], ["greenhouse:beta"])
            with patch.object(ats, "listing", return_value=[]):
                result = ats.run(root, selected, clock=later, discovery=state)
            self.assertEqual(result["jobs"], 1)  # deferred Alpha cannot be falsely closed
            self.assertEqual(result["health"]["boards"]["greenhouse:alpha"]["status"], "DEFERRED_ROTATION")

    def test_checked_in_seed_inventory(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root / "ats_boards.json").read_text())["boards"]
        _, discovery = ats.discover_boards(root, config, "2026-11-28T03:00:00+00:00")
        print("REAL_SNAPSHOT_BOARD_DISCOVERY", json.dumps({
            "configured": len(config), "registered": len(discovery["boards"]),
            "selected": discovery["selected"], "deferred": len(discovery["deferred"]),
            "seed_reads": discovery["seed_reads"]}, sort_keys=True))
        self.assertLessEqual(len(discovery["selected"]), ats.DISCOVERED_BOARD_LIMIT)
        self.assertFalse(set(discovery["boards"]) & {b["ats"] + ":" + b["slug"].lower() for b in config})
