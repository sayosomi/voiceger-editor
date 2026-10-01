"""Shared Voiceger environment detection and first-run diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Optional

from ._version import __version__
from .compatibility import SUPPORTED_VOICEGER_REVISION
from .styles import available_styles


VOICEGER_REPOSITORY_URL = "https://github.com/zunzun999/voiceger_v2"


class CheckStatus(str, Enum):
    OK = "OK"
    WARN = "WARN"
    ERROR = "ERROR"


@dataclass(frozen=True)
class EnvironmentCheck:
    key: str
    status: CheckStatus
    message: str


@dataclass(frozen=True)
class VoicegerEnvironmentReport:
    adapter_version: str
    python_version: str
    voiceger_root: Path
    root_source: str
    voiceger_revision: Optional[str]
    checks: tuple[EnvironmentCheck, ...]

    @property
    def ready(self) -> bool:
        return not any(check.status is CheckStatus.ERROR for check in self.checks)

    @property
    def errors(self) -> tuple[EnvironmentCheck, ...]:
        return tuple(
            check for check in self.checks if check.status is CheckStatus.ERROR
        )

    @property
    def warnings(self) -> tuple[EnvironmentCheck, ...]:
        return tuple(
            check for check in self.checks if check.status is CheckStatus.WARN
        )


class VoicegerEnvironmentError(RuntimeError):
    """Raised when shared Voiceger setup checks find a fatal problem."""

    def __init__(self, report: VoicegerEnvironmentReport) -> None:
        self.report = report
        lines = ["Voiceger setup is not ready."]
        lines.extend(f"- {check.message}" for check in report.errors)
        lines.extend(
            (
                f"Voiceger: {VOICEGER_REPOSITORY_URL}",
                'Set VOICEGER_ROOT, for example: export VOICEGER_ROOT="/path/to/voiceger_v2"',
                f"Tested Voiceger revision: {SUPPORTED_VOICEGER_REVISION}",
                "Run voiceger-editor --check for the full report.",
            )
        )
        super().__init__("\n".join(lines))


def resolve_voiceger_root(
    voiceger_root: Optional[str | os.PathLike[str]] = None,
) -> tuple[Path, str]:
    """Resolve Voiceger root and report which configuration source was used."""

    if voiceger_root is not None:
        return Path(voiceger_root).expanduser().resolve(), "explicit"

    configured = os.environ.get("VOICEGER_ROOT")
    if configured:
        return Path(configured).expanduser().resolve(), "environment"

    return (Path.home() / "voiceger_v2").expanduser().resolve(), "default"


def _voiceger_python(root: Path) -> Optional[Path]:
    candidates = (
        root / ".venv" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",
    )
    return next((path for path in candidates if path.is_file()), None)


def _read_voiceger_revision(root: Path) -> Optional[str]:
    if not (root / ".git").exists():
        return None

    git = shutil.which("git")
    if git is None:
        return None

    try:
        result = subprocess.run(
            [git, "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    revision = result.stdout.strip()
    return revision or None


def check_voiceger_environment(
    voiceger_root: Optional[str | os.PathLike[str]] = None,
) -> VoicegerEnvironmentReport:
    """Inspect the local Voiceger runtime without importing or modifying it."""

    root, root_source = resolve_voiceger_root(voiceger_root)
    checks: list[EnvironmentCheck] = []

    if root_source == "default":
        checks.append(
            EnvironmentCheck(
                "voiceger-root-config",
                CheckStatus.WARN,
                f"VOICEGER_ROOT is not set; using the default path {root}.",
            )
        )
    else:
        checks.append(
            EnvironmentCheck(
                "voiceger-root-config",
                CheckStatus.OK,
                f"VOICEGER_ROOT resolved from {root_source} configuration.",
            )
        )

    if root.is_dir():
        checks.append(
            EnvironmentCheck(
                "voiceger-root",
                CheckStatus.OK,
                f"Voiceger root exists: {root}",
            )
        )
    else:
        checks.append(
            EnvironmentCheck(
                "voiceger-root",
                CheckStatus.ERROR,
                f"Voiceger root does not exist: {root}",
            )
        )

    layout_paths = (
        root / "voiceger.py",
        root / "GPT-SoVITS" / "GPT_SoVITS" / "inference_webui.py",
    )
    missing_layout = tuple(path for path in layout_paths if not path.is_file())
    if missing_layout:
        checks.append(
            EnvironmentCheck(
                "voiceger-layout",
                CheckStatus.ERROR,
                "The configured path does not look like a Voiceger installation; "
                "missing " + ", ".join(str(path) for path in missing_layout) + ".",
            )
        )
    else:
        checks.append(
            EnvironmentCheck(
                "voiceger-layout",
                CheckStatus.OK,
                "Voiceger installation layout was detected.",
            )
        )

    voiceger_python = _voiceger_python(root)
    if voiceger_python is None:
        checks.append(
            EnvironmentCheck(
                "voiceger-python",
                CheckStatus.ERROR,
                f"Voiceger Python environment is missing under {root / '.venv'}.",
            )
        )
    else:
        checks.append(
            EnvironmentCheck(
                "voiceger-python",
                CheckStatus.OK,
                f"Voiceger Python environment detected: {voiceger_python}",
            )
        )

    if sys.version_info[:2] == (3, 9):
        checks.append(
            EnvironmentCheck(
                "python-version",
                CheckStatus.OK,
                f"Python {sys.version.split()[0]} matches the v1 supported runtime.",
            )
        )
    else:
        checks.append(
            EnvironmentCheck(
                "python-version",
                CheckStatus.ERROR,
                f"Python {sys.version.split()[0]} is not supported by v1; use Python 3.9.",
            )
        )

    expected_prefix = root / ".venv"
    try:
        active_prefix = Path(sys.prefix).expanduser().resolve()
        expected_prefix = expected_prefix.expanduser().resolve()
    except (OSError, RuntimeError):
        active_prefix = Path(sys.prefix)

    if voiceger_python is not None and active_prefix == expected_prefix:
        checks.append(
            EnvironmentCheck(
                "active-python-environment",
                CheckStatus.OK,
                "The adapter is running inside the Voiceger Python environment.",
            )
        )
    elif voiceger_python is not None:
        checks.append(
            EnvironmentCheck(
                "active-python-environment",
                CheckStatus.WARN,
                "The adapter is not running inside Voiceger\'s .venv; "
                "Voiceger imports may be unavailable.",
            )
        )

    model_paths = (
        root / "GPT_weights_v2" / "zudamon_style_1-e15.ckpt",
        root / "SoVITS_weights_v2" / "zudamon_style_1_e8_s96.pth",
    )
    missing_models = tuple(path for path in model_paths if not path.is_file())
    if missing_models:
        checks.append(
            EnvironmentCheck(
                "voiceger-models",
                CheckStatus.ERROR,
                "Required Voiceger model files are missing: "
                + ", ".join(str(path) for path in missing_models)
                + ".",
            )
        )
    else:
        checks.append(
            EnvironmentCheck(
                "voiceger-models",
                CheckStatus.OK,
                "Required Voiceger model files are available.",
            )
        )

    required_reference_paths = (
        root / "reference" / "reference.wav",
        root / "reference" / "ref_text.txt",
    )
    missing_references = tuple(
        path for path in required_reference_paths if not path.is_file()
    )
    styles = available_styles(root)
    if missing_references or not styles:
        missing_parts = [str(path) for path in missing_references]
        if not styles:
            missing_parts.append("all known reference style WAV files")
        checks.append(
            EnvironmentCheck(
                "voiceger-reference-assets",
                CheckStatus.ERROR,
                "Required Voiceger reference assets are unavailable: "
                + ", ".join(missing_parts)
                + ".",
            )
        )
    else:
        checks.append(
            EnvironmentCheck(
                "voiceger-reference-assets",
                CheckStatus.OK,
                f"Voiceger reference assets are available ({len(styles)} style(s) detected).",
            )
        )

    revision = _read_voiceger_revision(root)
    if revision == SUPPORTED_VOICEGER_REVISION:
        checks.append(
            EnvironmentCheck(
                "voiceger-revision",
                CheckStatus.OK,
                f"Voiceger revision matches the tested revision {revision}.",
            )
        )
    elif revision is None:
        checks.append(
            EnvironmentCheck(
                "voiceger-revision",
                CheckStatus.WARN,
                "Voiceger revision could not be determined; compatibility is unverified.",
            )
        )
    else:
        checks.append(
            EnvironmentCheck(
                "voiceger-revision",
                CheckStatus.WARN,
                f"Voiceger revision {revision} differs from the tested revision "
                f"{SUPPORTED_VOICEGER_REVISION}; compatibility is unverified.",
            )
        )

    return VoicegerEnvironmentReport(
        adapter_version=__version__,
        python_version=sys.version.split()[0],
        voiceger_root=root,
        root_source=root_source,
        voiceger_revision=revision,
        checks=tuple(checks),
    )


def require_voiceger_environment(
    voiceger_root: Optional[str | os.PathLike[str]] = None,
) -> VoicegerEnvironmentReport:
    """Return the shared environment report or raise an actionable setup error."""

    report = check_voiceger_environment(voiceger_root)
    if not report.ready:
        raise VoicegerEnvironmentError(report)
    return report


def format_voiceger_environment_report(report: VoicegerEnvironmentReport) -> str:
    """Render stable user-facing diagnostics for the CLI."""

    revision = report.voiceger_revision or "unavailable"
    lines = [
        f"voiceger-editor {report.adapter_version}",
        f"Python: {report.python_version}",
        f"VOICEGER_ROOT: {report.voiceger_root} ({report.root_source})",
        f"Voiceger revision: {revision}",
        "",
    ]
    lines.extend(
        f"[{check.status.value}] {check.message}" for check in report.checks
    )
    lines.extend(
        (
            "",
            f"READY: {'YES' if report.ready else 'NO'}",
            f"Voiceger: {VOICEGER_REPOSITORY_URL}",
            'Set VOICEGER_ROOT: export VOICEGER_ROOT="/path/to/voiceger_v2"',
            f"Tested Voiceger revision: {SUPPORTED_VOICEGER_REVISION}",
        )
    )
    return "\n".join(lines)
