import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "feed_pages.py"


class FeedPagesTests(unittest.TestCase):
    def test_writes_small_seq_addressable_pages_and_index(self):
        self.assertTrue(SCRIPT.exists(), "feed_pages.py must exist")
        spec = importlib.util.spec_from_file_location("feed_pages", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "feed").mkdir()
            events = [
                {"seq": seq, "kind": "NEW", "company": f"C{seq}", "title": "Engineer"}
                for seq in range(87, 92)
            ]
            (root / "feed" / "events.jsonl").write_text(
                "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8"
            )
            (root / "health.json").write_text(
                json.dumps({"first_seq": 87, "last_seq": 91}), encoding="utf-8"
            )

            index = mod.build_pages(root, page_size=2)

            self.assertEqual(index["first_seq"], 87)
            self.assertEqual(index["last_seq"], 91)
            self.assertEqual(
                [(p["first_seq"], p["last_seq"], p["count"]) for p in index["pages"]],
                [(87, 88, 2), (89, 90, 2), (91, 91, 1)],
            )
            for page in index["pages"]:
                path = root / page["path"]
                self.assertTrue(path.exists())
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
                self.assertEqual(rows[0]["seq"], page["first_seq"])
                self.assertEqual(rows[-1]["seq"], page["last_seq"])
            persisted = json.loads((root / "feed" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted, index)

    def test_workflow_builds_and_publishes_pages(self):
        workflow = (ROOT / ".github" / "workflows" / "freehire.yml").read_text(encoding="utf-8")
        self.assertIn("python feed_pages.py", workflow)
        self.assertIn("feed/index.json", workflow)
        self.assertIn("feed/pages", workflow)


if __name__ == "__main__":
    unittest.main()
