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
        self.assertIn("uses: actions/checkout@v7", text)
        self.assertIn("uses: actions/setup-python@v7", text)
        self.assertNotIn("secrets.", text)

    def test_scheduled_mode_mapping_is_explicit(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("github.event.schedule", text)
        self.assertIn("43 18 * * *", text)
        self.assertIn('MODE="full"', text)
        self.assertIn('MODE="delta"', text)


if __name__ == "__main__":
    unittest.main()
