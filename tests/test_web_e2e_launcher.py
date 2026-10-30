"""The manual Web E2E runner must protect unrelated work and avoid pinned SHAs."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


RUNNER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_web_e2e.py"
SPEC = importlib.util.spec_from_file_location("voiceger_web_e2e_launcher", RUNNER_PATH)
assert SPEC and SPEC.loader
LAUNCHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAUNCHER)


class ManualWebE2ELauncherTests(unittest.TestCase):
    def test_unchanged_remote_does_not_merge_or_require_pinned_sha(self):
        current = "0123456789abcdef" * 2 + "01234567"
        calls = []
        answers = {
            ("rev-parse", "--show-toplevel"): str(LAUNCHER.REPOSITORY),
            ("remote", "get-url", "origin"):
                "https://github.com/sayosomi/voiceger-editor.git",
            ("branch", "--show-current"): LAUNCHER.BRANCH,
            ("status", "--porcelain"): "",
            ("fetch", "origin"): "",
            ("rev-parse", "--verify", "refs/remotes/origin/" + LAUNCHER.BRANCH): current,
            ("rev-parse", "--verify", "HEAD"): current,
        }

        def fake_git(*args):
            calls.append(args)
            return answers[args]

        with patch.object(LAUNCHER, "_git", side_effect=fake_git):
            self.assertEqual(LAUNCHER._verify_and_refresh(), current)
        self.assertIn(("fetch", "origin"), calls)
        self.assertFalse(any(c[0] == "merge" for c in calls))

    def test_dirty_checkout_does_not_fetch_or_switch(self):
        calls = []

        def fake_git(*args):
            calls.append(args)
            if args == ("rev-parse", "--show-toplevel"):
                return str(LAUNCHER.REPOSITORY)
            if args == ("remote", "get-url", "origin"):
                return "git@github.com:sayosomi/voiceger-editor.git"
            if args == ("branch", "--show-current"):
                return LAUNCHER.BRANCH
            if args == ("status", "--porcelain"):
                return " M user-file"
            self.fail("Unexpected git operation on dirty repository: " + str(args))

        with patch.object(LAUNCHER, "_git", side_effect=fake_git):
            with self.assertRaisesRegex(LAUNCHER.LaunchBlocked, "Uncommitted"):
                LAUNCHER._verify_and_refresh()
        self.assertNotIn(("fetch", "origin"), calls)

    def test_divergence_must_not_merge(self):
        local = "a" * 40
        remote = "b" * 40
        calls = []
        def fake_git(*args):
            calls.append(args)
            if args == ("rev-parse", "--show-toplevel"):
                return str(LAUNCHER.REPOSITORY)
            if args == ("remote", "get-url", "origin"):
                return "https://github.com/sayosomi/voiceger-editor"
            if args == ("branch", "--show-current"):
                return LAUNCHER.BRANCH
            if args == ("status", "--porcelain"):
                return ""
            if args == ("fetch", "origin"):
                return ""
            if args == ("rev-parse", "--verify", "refs/remotes/origin/" + LAUNCHER.BRANCH):
                return remote
            if args == ("rev-parse", "--verify", "HEAD"):
                return local
            self.fail("Unexpected git operation " + str(args))
        with patch.object(LAUNCHER, "_git", side_effect=fake_git):
            with patch.object(LAUNCHER.subprocess, "run",
                              return_value=subprocess.CompletedProcess([], 1)):
                with self.assertRaisesRegex(LAUNCHER.LaunchBlocked, "diverged"):
                    LAUNCHER._verify_and_refresh()
        self.assertFalse(any(c[0] == "merge" for c in calls))

    def test_clean_fast_forward_follows_current_remote_head(self):
        local = "a" * 40
        remote = "b" * 40
        calls = []
        values = iter((local, remote))
        def fake_git(*args):
            calls.append(args)
            if args == ("rev-parse", "--show-toplevel"):
                return str(LAUNCHER.REPOSITORY)
            if args == ("remote", "get-url", "origin"):
                return "https://github.com/sayosomi/voiceger-editor.git"
            if args == ("branch", "--show-current"):
                return LAUNCHER.BRANCH
            if args == ("status", "--porcelain"):
                return ""
            if args == ("fetch", "origin"):
                return ""
            if args == ("rev-parse", "--verify", "refs/remotes/origin/" + LAUNCHER.BRANCH):
                return remote
            if args == ("rev-parse", "--verify", "HEAD"):
                return next(values)
            if args == ("merge", "--ff-only", "refs/remotes/origin/" + LAUNCHER.BRANCH):
                return ""
            self.fail("Unexpected git operation " + str(args))
        with patch.object(LAUNCHER, "_git", side_effect=fake_git):
            with patch.object(LAUNCHER.subprocess, "run",
                              return_value=subprocess.CompletedProcess([], 0)):
                self.assertEqual(LAUNCHER._verify_and_refresh(), remote)
        self.assertIn(
            ("merge", "--ff-only", "refs/remotes/origin/" + LAUNCHER.BRANCH), calls)

    def test_scratch_cleanup_touches_only_canonical_issue_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp) / "scratch" / "issue314-e2e"
            unrelated = scratch.parent / "other-work"
            unrelated.mkdir(parents=True)
            (unrelated / "keep.txt").write_text("do not touch", encoding="utf-8")
            scratch.mkdir()
            (scratch / "old.wav").write_bytes(b"old")
            with patch.object(LAUNCHER, "SCRATCH", scratch):
                output = LAUNCHER._prepare_scratch()
            self.assertEqual(output, scratch / "output")
            self.assertTrue(output.is_dir())
            self.assertFalse((scratch / "old.wav").exists())
            self.assertEqual((unrelated / "keep.txt").read_text(encoding="utf-8"),
                             "do not touch")

    def test_symlink_scratch_refused_without_deleting_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "user-data"
            target.mkdir()
            (target / "keep.txt").write_text("safe", encoding="utf-8")
            symlink = root / "scratch" / "issue314-e2e"
            symlink.parent.mkdir()
            symlink.symlink_to(target, target_is_directory=True)
            with patch.object(LAUNCHER, "SCRATCH", symlink):
                with self.assertRaisesRegex(LAUNCHER.LaunchBlocked, "symbolic"):
                    LAUNCHER._prepare_scratch()
            self.assertEqual((target / "keep.txt").read_text(encoding="utf-8"), "safe")


if __name__ == "__main__":
    unittest.main()
