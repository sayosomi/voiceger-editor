"""Regression checks for the TUI's module boundary and composition-root size."""

import ast
from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPOSITORY_ROOT / "voiceger_editor"
COMPOSITION_ROOT = PACKAGE_ROOT / "tui.py"
COMPOSITION_ROOT_LINE_CEILING = 900


def _imports_composition_root(node):
    if isinstance(node, ast.ImportFrom):
        if node.level and node.module == "tui":
            return True
        if node.module == "voiceger_editor.tui":
            return True
        if node.module == "voiceger_editor" and any(
            alias.name == "tui" for alias in node.names
        ):
            return True
        if node.module is None and node.level and any(
            alias.name == "tui" for alias in node.names
        ):
            return True
    elif isinstance(node, ast.Import):
        return any(
            alias.name == "voiceger_editor.tui"
            or alias.name.startswith("voiceger_editor.tui.")
            for alias in node.names
        )
    return False


def _imports_tui_app(node):
    if isinstance(node, ast.ImportFrom):
        return any(alias.name == "TuiApp" for alias in node.names)
    if isinstance(node, ast.Import):
        return any(
            alias.name.rsplit(".", 1)[-1] == "TuiApp"
            or alias.asname == "TuiApp"
            for alias in node.names
        )
    return False


class TuiArchitectureTests(unittest.TestCase):
    def test_composition_root_stays_within_physical_line_ceiling(self):
        actual_lines = len(COMPOSITION_ROOT.read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(
            actual_lines,
            COMPOSITION_ROOT_LINE_CEILING,
            f"voiceger_editor/tui.py has {actual_lines} physical lines; "
            f"the ceiling is {COMPOSITION_ROOT_LINE_CEILING}. Place new "
            "responsibility in the owning subsystem rather than expanding "
            "the composition root.",
        )

    def test_extracted_modules_do_not_import_the_composition_root_or_tui_app(self):
        violations = []
        for path in sorted(PACKAGE_ROOT.glob("tui_*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                relative_path = path.relative_to(REPOSITORY_ROOT)
                location = f"{relative_path}:{getattr(node, 'lineno', '?')}"
                if _imports_composition_root(node):
                    violations.append(
                        f"{location}: extracted module imports the TUI composition root"
                    )
                if _imports_tui_app(node):
                    violations.append(
                        f"{location}: extracted module imports the TuiApp symbol"
                    )

        self.assertEqual([], violations, "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
