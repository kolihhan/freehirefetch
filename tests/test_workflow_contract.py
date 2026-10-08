from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "freehire.yml"


class WorkflowContractTests(unittest.TestCase):
    def test_workflow_contract(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("cron: '17 * * * *'", text)
        self.assertIn("cron: '43 18 * * *'", text)
        self.assertIn('python freehire_fetch.py --mode "$MODE"', text)
        self.assertIn("permissions:\n  contents: write", text)
        self.assertIn("runs-on: ubuntu-latest", text)
        self.assertIn("uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", text)
        self.assertIn("uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97", text)
        self.assertNotIn("secrets.", text)
        self.assertNotIn("\n  push:", text)

    def test_scheduled_mode_mapping_is_explicit(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("github.event.schedule", text)
        self.assertIn("43 18 * * *", text)
        self.assertIn('MODE="full"', text)
        self.assertIn('MODE="delta"', text)


if __name__ == "__main__":
    unittest.main()
