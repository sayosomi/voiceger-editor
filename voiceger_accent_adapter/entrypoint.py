"""CLI entry point for the terminal interface."""

from __future__ import annotations

import curses
import sys
from typing import Sequence

from .settings import SettingsError, load_settings
from .takes import cleanup_stale_take_directories
from .tui_cli import build_argument_parser, settings_for_invocation
from .voiceger_adapter import VoicegerAdapter
from .voiceger_environment import (
    VoicegerEnvironmentError,
    check_voiceger_environment,
    format_voiceger_environment_report,
)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    environment = check_voiceger_environment(args.voiceger_root)

    if args.check:
        print(format_voiceger_environment_report(environment))
        return 0 if environment.ready else 2

    if not environment.ready:
        print(str(VoicegerEnvironmentError(environment)), file=sys.stderr)
        return 2

    for warning in environment.warnings:
        print(f"Voiceger setup warning: {warning.message}", file=sys.stderr)

    cleanup_stale_take_directories()
    try:
        persisted_settings = load_settings(args.config)
        settings = settings_for_invocation(args, persisted_settings)
    except (SettingsError, ValueError) as exc:
        print(f"Cannot load settings: {exc}", file=sys.stderr)
        return 2

    adapter = VoicegerAdapter(
        voiceger_root=environment.voiceger_root,
        output_dir=settings.output_dir,
    )

    # Import after the environment preflight so --check and setup failures do not
    # require the full terminal composition root.
    from .tui import TuiApp

    app = TuiApp(
        adapter=adapter,
        settings=settings,
        persisted_settings=persisted_settings,
        config_path=args.config,
        source_text=args.text,
    )
    try:
        curses.wrapper(app.run)
    except curses.error as exc:
        print(
            f"The terminal UI could not start: {exc}. Run this command in a real terminal.",
            file=sys.stderr,
        )
        return 2
    return 0
