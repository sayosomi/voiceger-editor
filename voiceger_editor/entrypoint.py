"""CLI entry point for the terminal interface."""

from __future__ import annotations

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
    preferred_notice_language,
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


def _load_curses():
    """Load the optional terminal backend at the point TUI startup begins."""

    import curses

    return curses


def _open_official_terms() -> bool:
    try:
        opened = webbrowser.open(OFFICIAL_TERMS_URL)
    except Exception as exc:
        opened = False
        reason = str(exc)
    else:
        reason = ""

    if opened:
        return True

    detail = f" ({reason})" if reason else ""
    print(
        "Could not open a browser. Open the official terms manually at "
        f"{OFFICIAL_TERMS_URL}{detail}",
        file=sys.stderr,
    )
    return False


def _run_terms_action(args) -> int | None:
    if args.accept_voiceger_terms:
        print(format_current_notice())
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
        return 0 if _open_official_terms() else 2

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

    language = preferred_notice_language()
    while True:
        print(format_current_notice(language))
        print()
        if language == "ja":
            print("[O] 公式利用規約を開く")
            print("[A] 同意して続ける")
            print("[E] English")
            print("[Q] 終了")
            prompt = "選択: "
            invalid_message = "O / A / E / Q のいずれかを入力してください。"
        else:
            print("[O] Open the official terms")
            print("[A] Accept and continue")
            print("[J] 日本語")
            print("[Q] Quit")
            prompt = "Choice: "
            invalid_message = "Enter O, A, J, or Q."

        try:
            answer = input(prompt).strip().lower()
        except (EOFError, OSError):
            return False

        if answer == "a":
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

        if answer == "o":
            _open_official_terms()
            continue

        if language == "ja" and answer == "e":
            language = "en"
            continue

        if language == "en" and answer == "j":
            language = "ja"
            continue

        if answer == "q":
            return False

        print(invalid_message, file=sys.stderr)


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

    # Load curses after preflight and setup so management actions and setup
    # failures do not require the optional terminal backend.
    try:
        curses = _load_curses()
    except ModuleNotFoundError as exc:
        if exc.name != "curses":
            raise
        print(
            "The terminal UI requires the TUI extra. Install it with: "
            "python -m pip install 'voiceger-editor[tui]'",
            file=sys.stderr,
        )
        return 2

    # Import curses before TuiApp because voiceger_editor.tui imports curses.
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
