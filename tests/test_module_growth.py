"""Repository-wide regression guard for silent Python module growth."""

import json
from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPOSITORY_ROOT / "voiceger_editor"
TEST_ROOT = REPOSITORY_ROOT / "tests"
EXCEPTION_REGISTRY = TEST_ROOT / "module_growth_exceptions.json"

PRODUCTION_REVIEW_THRESHOLD = 1500
TEST_REVIEW_THRESHOLD = 3500

ROOT_SPECS = (
    ("production", PACKAGE_ROOT, PRODUCTION_REVIEW_THRESHOLD),
    ("test", TEST_ROOT, TEST_REVIEW_THRESHOLD),
)


def _line_count(path):
    return len(path.read_text(encoding="utf-8").splitlines())


def _load_exception_registry():
    payload = json.loads(EXCEPTION_REGISTRY.read_text(encoding="utf-8"))
    exceptions = payload.get("exceptions")
    if not isinstance(exceptions, list):
        raise AssertionError(
            f"{EXCEPTION_REGISTRY.relative_to(REPOSITORY_ROOT)}: "
            "'exceptions' must be a list"
        )
    return exceptions


def _scope_for_path(relative_path):
    if relative_path.parts[0] == "voiceger_editor":
        return "production", PRODUCTION_REVIEW_THRESHOLD
    if relative_path.parts[0] == "tests":
        return "test", TEST_REVIEW_THRESHOLD
    raise AssertionError(f"unsupported exception path: {relative_path}")


class ModuleGrowthTests(unittest.TestCase):
    def test_python_modules_do_not_silently_outgrow_reviewed_limits(self):
        failures = []
        exception_by_path = {}

        for entry in _load_exception_registry():
            if not isinstance(entry, dict):
                failures.append(
                    "module_growth_exceptions.json: every exception must be an object"
                )
                continue

            relative_path = entry.get("path")
            reviewed_max_lines = entry.get("reviewed_max_lines")
            justification = entry.get("justification")
            follow_up_issue = entry.get("follow_up_issue")

            if not isinstance(relative_path, str) or not relative_path:
                failures.append(
                    "module_growth_exceptions.json: every exception needs a non-empty path"
                )
                continue

            path = Path(relative_path)
            try:
                _scope_for_path(path)
            except AssertionError as exc:
                failures.append(str(exc))
                continue

            if relative_path in exception_by_path:
                failures.append(
                    f"{relative_path}: duplicate module-growth exception entry"
                )
                continue

            if (
                not isinstance(reviewed_max_lines, int)
                or isinstance(reviewed_max_lines, bool)
                or reviewed_max_lines <= 0
            ):
                failures.append(
                    f"{relative_path}: reviewed_max_lines must be a positive integer"
                )
                continue

            if not isinstance(justification, str) or not justification.strip():
                failures.append(
                    f"{relative_path}: exception requires a responsibility justification"
                )
                continue

            if follow_up_issue is not None and (
                not isinstance(follow_up_issue, str) or not follow_up_issue.strip()
            ):
                failures.append(
                    f"{relative_path}: follow_up_issue must be a non-empty URL or null"
                )
                continue

            exception_by_path[relative_path] = entry

        scanned_paths = set()
        for scope, root, threshold in ROOT_SPECS:
            for path in sorted(root.rglob("*.py")):
                relative_path = path.relative_to(REPOSITORY_ROOT)
                relative_text = relative_path.as_posix()
                scanned_paths.add(relative_text)
                current_lines = _line_count(path)
                exception = exception_by_path.get(relative_text)

                if current_lines < threshold:
                    if exception is not None:
                        failures.append(
                            f"{relative_text}: {current_lines} lines is below the "
                            f"{scope} review threshold {threshold}; remove the "
                            "now-unneeded exception entry"
                        )
                    continue

                if exception is None:
                    failures.append(
                        f"{relative_text}: {current_lines} lines reaches/exceeds the "
                        f"{scope} review threshold {threshold}; this is a new oversized "
                        "module. Split responsibility into a focused owner, or "
                        "intentionally add a reviewed exception with a baseline and "
                        "responsibility justification"
                    )
                    continue

                reviewed_max_lines = exception["reviewed_max_lines"]
                if current_lines > reviewed_max_lines:
                    failures.append(
                        f"{relative_text}: {current_lines} lines exceeds its reviewed "
                        f"exception baseline {reviewed_max_lines} (the {scope} review "
                        f"threshold is {threshold}); split responsibility into a focused "
                        "owner, or intentionally update the reviewed exception baseline "
                        "with justification"
                    )

        for relative_text in sorted(set(exception_by_path) - scanned_paths):
            failures.append(
                f"{relative_text}: registered exception path does not exist; "
                "remove or correct the exception entry"
            )

        self.assertEqual([], failures, "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
