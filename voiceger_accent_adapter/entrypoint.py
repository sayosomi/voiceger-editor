"""CLI entry point for the terminal interface."""

from __future__ import annotations

import curses
import sys
from typing import Sequence
import webbrowser

from .settings import SettingsError, load_settings
from .takes import cleanup_stale_take_directories
from .terms_acceptance import (
    OFFICIAL_TERMS_URL,
    VoicegerTermsAcceptanceError,
    current_acceptance_status,
    format_acceptance_status,
    format_current_notice,
    record_explicit_acceptance,
    require_current_acceptance,
)
from .tui_cli import build_argument_parser, settings_for_invocation
from .voiceger_adapter import VoicegerAdapter
from .voiceger_environment import (
    VoicegerEnvironmentError,
    check_voiceger_environment,
    format_voiceger_environment_report,
)


def _run_terms_action(args) -> int | None:
    if args.accept_voiceger_terms:
        print(format_current_notice())
        print(f"Official terms: {OFFICIAL_TERMS_URL}")
        try:
            record_explicit_acceptance()
        except OSError as exc:
            print(f"Cannot save Voiceger terms acceptance: {exc}", file=sys.stderr)
            return 2
        print("Voiceger:Zundamon terms acceptance saved.")
        return 0

    if args.voiceger_terms_status:
        status = current_acceptance_status()
        print(format_acceptance_status(status))
        return 0 if status.accepted else 2

    if args.open_voiceger_terms:
        print(format_current_notice())
        print(f"Official terms: {OFFICIAL_TERMS_URL}")
        try:
            opened = webbrowser.open(OFFICIAL_TERMS_URL)
        except Exception as exc:
            opened = False
            reason = str(exc)
        else:
            reason = ""
        if not opened:
            detail = f" ({reason})" if reason else ""
            print(
                "Could not open a browser. Open the official terms manually at "
                f"{OFFICIAL_TERMS_URL}{detail}",
                file=sys.stderr,
            )
            return 2
        return 0

    return None


def _require_tui_terms_acceptance() -> bool:
    status = current_acceptance_status()
    if status.accepted:
        try:
            require_current_acceptance()
        except VoicegerTermsAcceptanceError as exc:
            print(str(exc), file=sys.stderr)
            return False
        return True

    if not sys.stdin.isatty():
        try:
            require_current_acceptance()
        except VoicegerTermsAcceptanceError as exc:
            print(str(exc), file=sys.stderr)
        return False

    print(format_current_notice())
    print(f"Official terms: {OFFICIAL_TERMS_URL}")
    print(f"Current acceptance status: {status.detail}")
    try:
        answer = input("Type ACCEPT after reading the official terms to continue: ")
    except (EOFError, OSError):
        answer = ""

    if answer != "ACCEPT":
        print(
            "Voiceger terms were not accepted; the TUI will not start.",
            file=sys.stderr,
        )
        return False

    try:
        record_explicit_acceptance()
        require_current_acceptance()
    except (OSError, VoicegerTermsAcceptanceError) as exc:
        print(
            "Cannot continue without current Voiceger terms acceptance: "
            f"{exc}",
            file=sys.stderr,
        )
        return False
    return True


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    if args.text is not None and (
        args.check
        or args.accept_voiceger_terms
        or args.voiceger_terms_status
        or args.open_voiceger_terms
    ):
        parser.error("a management action cannot be combined with synthesis text")

    terms_action_result = _run_terms_action(args)
    if terms_action_result is not None:
        return terms_action_result

    environment = check_voiceger_environment(args.voiceger_root)

    if args.check:
        print(format_voiceger_environment_report(environment))
        return 0 if environment.ready else 2

    if not environment.ready:
        print(str(VoicegerEnvironmentError(environment)), file=sys.stderr)
        return 2

    for warning in environment.warnings:
        print(f"Voiceger setup warning: {warning.message}", file=sys.stderr)

    if not _require_tui_terms_acceptance():
        return 2

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


if __name__ == "__main__":
    raise SystemExit(main())
