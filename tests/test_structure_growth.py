"""AST-based regression guard for extreme local Python structure growth."""

import ast
import json
from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPOSITORY_ROOT / "voiceger_editor"
TEST_ROOT = REPOSITORY_ROOT / "tests"
EXCEPTION_REGISTRY = TEST_ROOT / "structure_growth_exceptions.json"

FUNCTION_REVIEW_THRESHOLD = 250
CLASS_METHOD_REVIEW_THRESHOLD = 50

METRIC_SPECS = {
    "function_lines": {
        "threshold": FUNCTION_REVIEW_THRESHOLD,
        "unit": "lines",
        "subject": "function/method",
    },
    "class_methods": {
        "threshold": CLASS_METHOD_REVIEW_THRESHOLD,
        "unit": "direct methods",
        "subject": "class",
    },
}

SCAN_ROOTS = (PACKAGE_ROOT, TEST_ROOT)
FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


class _StructureVisitor(ast.NodeVisitor):
    def __init__(self):
        self._parents = []
        self.measurements = []

    def _qualified_name(self, name):
        return ".".join((*self._parents, name))

    def visit_ClassDef(self, node):
        symbol = self._qualified_name(node.name)
        direct_methods = sum(
            isinstance(item, FUNCTION_NODES)
            for item in node.body
        )
        self.measurements.append(
            (symbol, "class_methods", direct_methods)
        )

        self._parents.append(node.name)
        self.generic_visit(node)
        self._parents.pop()

    def visit_FunctionDef(self, node):
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node):
        self._visit_function(node)

    def _visit_function(self, node):
        if node.end_lineno is None:
            raise AssertionError(
                f"{self._qualified_name(node.name)}: "
                "Python AST did not provide end_lineno"
            )

        symbol = self._qualified_name(node.name)
        line_count = node.end_lineno - node.lineno + 1
        self.measurements.append(
            (symbol, "function_lines", line_count)
        )

        self._parents.append(node.name)
        self.generic_visit(node)
        self._parents.pop()


def _measure_file(path):
    relative_path = path.relative_to(REPOSITORY_ROOT).as_posix()
    tree = ast.parse(
        path.read_text(encoding="utf-8"),
        filename=relative_path,
    )
    visitor = _StructureVisitor()
    visitor.visit(tree)
    return visitor.measurements


def _load_exception_registry():
    payload = json.loads(EXCEPTION_REGISTRY.read_text(encoding="utf-8"))
    exceptions = payload.get("exceptions")
    if not isinstance(exceptions, list):
        raise AssertionError(
            f"{EXCEPTION_REGISTRY.relative_to(REPOSITORY_ROOT)}: "
            "'exceptions' must be a list"
        )
    return exceptions


def _is_scanned_path(relative_path):
    if relative_path.suffix != ".py":
        return False
    return relative_path.parts[0] in {"voiceger_editor", "tests"}


class StructureGrowthTests(unittest.TestCase):
    def test_python_symbols_do_not_silently_outgrow_reviewed_limits(self):
        failures = []
        exception_by_key = {}

        for entry in _load_exception_registry():
            if not isinstance(entry, dict):
                failures.append(
                    "structure_growth_exceptions.json: every exception "
                    "must be an object"
                )
                continue

            relative_text = entry.get("path")
            symbol = entry.get("symbol")
            metric = entry.get("metric")
            reviewed_max = entry.get("reviewed_max")
            justification = entry.get("justification")
            follow_up_issue = entry.get("follow_up_issue")

            if not isinstance(relative_text, str) or not relative_text:
                failures.append(
                    "structure_growth_exceptions.json: every exception "
                    "needs a non-empty path"
                )
                continue

            relative_path = Path(relative_text)
            if not _is_scanned_path(relative_path):
                failures.append(
                    f"{relative_text}: structural exception path must be "
                    "a Python module under voiceger_editor/ or tests/"
                )
                continue

            if not isinstance(symbol, str) or not symbol.strip():
                failures.append(
                    f"{relative_text}: structural exception needs a "
                    "non-empty qualified symbol"
                )
                continue

            if metric not in METRIC_SPECS:
                failures.append(
                    f"{relative_text}::{symbol}: unsupported structural "
                    f"metric {metric!r}"
                )
                continue

            if (
                not isinstance(reviewed_max, int)
                or isinstance(reviewed_max, bool)
                or reviewed_max <= 0
            ):
                failures.append(
                    f"{relative_text}::{symbol}: reviewed_max must be "
                    "a positive integer"
                )
                continue

            if not isinstance(justification, str) or not justification.strip():
                failures.append(
                    f"{relative_text}::{symbol}: exception requires a "
                    "responsibility justification"
                )
                continue

            if follow_up_issue is not None and (
                not isinstance(follow_up_issue, str)
                or not follow_up_issue.strip()
            ):
                failures.append(
                    f"{relative_text}::{symbol}: follow_up_issue must be "
                    "a non-empty URL or null"
                )
                continue

            key = (relative_text, symbol, metric)
            if key in exception_by_key:
                failures.append(
                    f"{relative_text}::{symbol}: duplicate structural "
                    f"exception for {metric}"
                )
                continue

            exception_by_key[key] = entry

        scanned_keys = set()
        for root in SCAN_ROOTS:
            for path in sorted(root.rglob("*.py")):
                relative_text = path.relative_to(REPOSITORY_ROOT).as_posix()
                for symbol, metric, measured in _measure_file(path):
                    key = (relative_text, symbol, metric)
                    scanned_keys.add(key)
                    spec = METRIC_SPECS[metric]
                    threshold = spec["threshold"]
                    exception = exception_by_key.get(key)

                    if measured < threshold:
                        if exception is not None:
                            failures.append(
                                f"{relative_text}::{symbol}: {measured} "
                                f"{spec['unit']} is below the structural "
                                f"review threshold {threshold}; remove the "
                                "now-unneeded exception entry"
                            )
                        continue

                    if exception is None:
                        failures.append(
                            f"{relative_text}::{symbol}: {measured} "
                            f"{spec['unit']} reaches/exceeds the structural "
                            f"review threshold {threshold}; this is a new "
                            f"oversized {spec['subject']}. Review responsibility "
                            "ownership and split only at a coherent boundary, "
                            "or intentionally add a reviewed structural "
                            "exception baseline with justification. Do not use "
                            "code golf, formatting compression, or arbitrary "
                            "method fragmentation to satisfy the metric"
                        )
                        continue

                    reviewed_max = exception["reviewed_max"]
                    if measured > reviewed_max:
                        failures.append(
                            f"{relative_text}::{symbol}: {measured} "
                            f"{spec['unit']} exceeds its reviewed structural "
                            f"exception baseline {reviewed_max} "
                            f"(threshold {threshold}); review responsibility "
                            "ownership and split only at a coherent boundary, "
                            "or intentionally update the reviewed exception "
                            "baseline with justification"
                        )

        for relative_text, symbol, metric in sorted(
            set(exception_by_key) - scanned_keys
        ):
            failures.append(
                f"{relative_text}::{symbol}: registered structural "
                f"exception for {metric} does not exist; remove or correct "
                "the exception entry"
            )

        self.assertEqual([], failures, "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
