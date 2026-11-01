"""Validate Slice 11a's isolated Android UI/UX launcher and Git safety."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_web_e2e_331 as launcher


class WebE2E331Tests(unittest.TestCase):
    def test_topic_branch_and_exact_remote_head_are_required(self):
        self.assertEqual(launcher.BRANCH, "sayosomi/issue-331-web-session-lifecycle")
        self.assertEqual(launcher.SCRATCH.name, "issue331-e2e")
        expected = "a" * 40
        calls = []

        def fake_git(*args):
            calls.append(args)
            if args == ("rev-parse", "--show-toplevel"):
                return str(launcher.REPOSITORY)
            if args == ("remote", "get-url", "origin"):
                return "https://github.com/sayosomi/voiceger-editor.git"
            if args == ("branch", "--show-current"):
                return launcher.BRANCH
            if args == ("status", "--porcelain"):
                return ""
            if args == ("fetch", "origin", "--prune"):
                return ""
            if args == ("rev-parse", "--verify", "refs/remotes/origin/" + launcher.BRANCH):
                return expected
            if args == ("rev-parse", "HEAD"):
                return expected
            self.fail("Unexpected git invocation " + str(args))

        with patch.object(launcher, "_git", side_effect=fake_git):
            self.assertEqual(launcher._verify_and_refresh(), expected)
        self.assertIn(("fetch", "origin", "--prune"), calls)
        self.assertFalse(any(call[0] in {"reset", "rebase", "switch", "merge"}
                             for call in calls))

    def test_disposable_scratch_is_isolated(self):
        with tempfile.TemporaryDirectory() as root:
            scratch = Path(root) / "scratch" / "issue331-e2e"
            unrelated = scratch.parent / "user-data"
            unrelated.mkdir(parents=True)
            (unrelated / "keep.txt").write_text("keep", encoding="utf-8")
            scratch.mkdir()
            (scratch / "stale.json").write_text("discard", encoding="utf-8")
            with patch.object(launcher, "SCRATCH", scratch):
                launcher._prepare_scratch()
            self.assertTrue((scratch / "output").is_dir())
            self.assertTrue((scratch / "home").is_dir())
            self.assertFalse((scratch / "stale.json").exists())
            self.assertEqual((unrelated / "keep.txt").read_text(encoding="utf-8"),
                             "keep")


if __name__ == "__main__":
    unittest.main()
