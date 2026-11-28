"""Test clean publication on local Git repositories; no network."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "publish_clean_feed.sh"


class CleanPublicationTests(unittest.TestCase):
    def git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, check=True,
                              capture_output=True, text=True).stdout.strip()

    def configure(self, repo):
        self.git(repo, "config", "user.name", "Test")
        self.git(repo, "config", "user.email", "test@example.invalid")

    def test_workflow_has_single_clean_writer(self):
        workflows = ROOT / ".github/workflows"
        producer = (workflows / "freehire.yml").read_text()
        self.assertNotIn("python public_quality.py", producer)
        self.assertNotIn("feed/clean", producer)
        workflow = (workflows / "clean-public-feed.yml").read_text()
        for name in ("FreeHire Ingestion", "FreeHire Cold Start",
                     "ATS Discovery and Application Evidence", "CN Native Public Discovery",
                     "Public ATS Playwright Liveness"):
            self.assertIn(name, workflow)
        self.assertIn("types: [completed]", workflow)
        self.assertIn("branches: [main]", workflow)
        self.assertIn("ref: main", workflow)
        self.assertIn("bash publish_clean_feed.sh", workflow)
        self.assertNotIn("download-artifact", workflow)

    @unittest.skipUnless(shutil.which("git") and shutil.which("bash"), "requires local Git and Bash")
    def test_concurrent_source_push_rebuilds_instead_of_rebasing_stale_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            remote, seed, runner, race = [base / x for x in ("remote", "seed", "runner", "race")]
            self.git(base, "init", "--bare", "--initial-branch=main", str(remote))
            self.git(base, "clone", str(remote), str(seed))
            self.configure(seed)
            (seed / "source.txt").write_text("first")
            (seed / "public_quality.py").write_text(
                "from pathlib import Path\n"
                "p=Path('feed/clean/projection.txt')\n"
                "p.parent.mkdir(parents=True, exist_ok=True)\n"
                "p.write_text(Path('source.txt').read_text())\n")
            self.git(seed, "add", ".")
            self.git(seed, "commit", "-m", "initial source")
            self.git(seed, "push", "origin", "main")
            for dest in (runner, race):
                self.git(base, "clone", str(remote), str(dest))
                self.configure(dest)
            hook = runner / ".git/hooks/pre-push"
            hook.write_text(
                "#!/bin/sh\nset -eu\n"
                "if [ ! -f .git/race-injected ]; then\n"
                "  touch .git/race-injected\n"
                f"  printf second > '{race}/source.txt'\n"
                f"  git -C '{race}' add source.txt\n"
                f"  git -C '{race}' commit -m 'concurrent raw source'\n"
                f"  git -C '{race}' push origin main\n"
                "fi\n")
            hook.chmod(0o755)
            proc = subprocess.run(["bash", str(SCRIPT)], cwd=runner, text=True,
                                  capture_output=True, timeout=45)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("Concurrent main update", proc.stdout)
            self.git(race, "fetch", "origin", "main")
            self.assertEqual(self.git(race, "show", "origin/main:source.txt"), "second")
            self.assertEqual(self.git(race, "show", "origin/main:feed/clean/projection.txt"), "second")


if __name__ == "__main__":
    unittest.main()
