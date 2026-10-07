from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "discord_pr_notification.py"
_SPEC = importlib.util.spec_from_file_location("discord_pr_notification", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
notification = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(notification)


class DiscordPrNotificationTests(unittest.TestCase):
    def test_merge_content_is_compact_and_disables_no_information(self) -> None:
        content = notification.build_merge_content(
            repository="sayosomi/voiceger-editor",
            number=215,
            title="Align CI merge gating",
            url="https://github.com/sayosomi/voiceger-editor/pull/216",
        )
        self.assertEqual(
            content,
            "✅ [sayosomi/voiceger-editor] PR #215 merged\n"
            "Align CI merge gating\n"
            "https://github.com/sayosomi/voiceger-editor/pull/216",
        )

    def test_ci_failure_prefers_failed_non_aggregate_job_and_step(self) -> None:
        jobs = [
            {
                "name": "CI",
                "conclusion": "failure",
                "steps": [{"name": "Check required CI results", "conclusion": "failure"}],
            },
            {
                "name": "Unit tests",
                "conclusion": "failure",
                "steps": [
                    {"name": "Set up Python", "conclusion": "success"},
                    {"name": "Run unit tests", "conclusion": "failure"},
                ],
            },
        ]
        job = notification.select_failed_job(jobs)
        step = notification.select_failed_step(job)
        self.assertEqual(job["name"], "Unit tests")
        self.assertEqual(step["name"], "Run unit tests")

        content = notification.build_ci_failure_content(
            repository="sayosomi/voiceger-editor",
            pr_number=216,
            title="CI lifecycle",
            run={
                "conclusion": "failure",
                "head_sha": "a" * 40,
                "run_attempt": 1,
                "html_url": "https://github.com/example/actions/runs/1",
            },
            job=job,
            step=step,
        )
        self.assertIn("CI failure — PR #216", content)
        self.assertIn("failed job: Unit tests", content)
        self.assertIn("failed step: Run unit tests", content)

    def test_cancelled_ci_is_actionable_failure(self) -> None:
        job = notification.select_failed_job(
            [{"name": "Windows Python 3.9 startup boundary", "conclusion": "cancelled"}]
        )
        self.assertIsNotNone(job)

    def test_out_of_date_content_identifies_both_refs(self) -> None:
        content = notification.build_out_of_date_content(
            repository="sayosomi/voiceger-editor",
            number=216,
            title="CI lifecycle",
            url="https://github.com/sayosomi/voiceger-editor/pull/216",
            main_sha="b" * 40,
            head_sha="a" * 40,
        )
        self.assertIn("out of date — latest main integration required", content)
        self.assertIn(f"main SHA: {'b' * 40}", content)
        self.assertIn(f"PR head SHA: {'a' * 40}", content)

    def test_eligible_pull_request_requires_open_non_draft_main_pr(self) -> None:
        base = {
            "state": "open",
            "draft": False,
            "number": 216,
            "base": {"ref": "main"},
            "head": {"sha": "a" * 40},
        }
        self.assertTrue(notification._eligible_pull_request(base))
        self.assertFalse(notification._eligible_pull_request({**base, "draft": True}))
        self.assertFalse(
            notification._eligible_pull_request({**base, "base": {"ref": "release"}})
        )

    def test_display_normalizes_control_whitespace_and_truncates(self) -> None:
        self.assertEqual(notification._display("a\n\tb", 10), "a b")
        self.assertEqual(notification._display("abcdef", 4), "abc…")


if __name__ == "__main__":
    unittest.main()
