"""Issue #322 manual Android E2E launcher safety contract."""

from pathlib import Path
import unittest


class Issue322LauncherTests(unittest.TestCase):
    def test_uses_target_branch_and_isolated_disposable_state(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "scripts" / "run_web_e2e_322.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'BRANCH = "sayosomi/issue-322-ja-arpabet-runtime-probe"', script
        )
        self.assertIn(
            'SCRATCH = REPOSITORY / "scratch" / "issue322-e2e"', script
        )
        self.assertIn('os.environ["HOME"] = str(SCRATCH / "home")', script)
        self.assertIn("shutil.copyfile(source, destination)", script)
        self.assertIn('dictionary_core=adapter.user_dictionary', script)
        self.assertIn('uvicorn.run(create_web_app(service=service)', script)


if __name__ == "__main__":
    unittest.main()
