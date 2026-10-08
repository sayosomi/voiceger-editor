"""Help-screen document construction."""

from __future__ import annotations

from ._version import __version__
from .project_info import DOCUMENTATION_URL
from .tui_display import _display_width, _wrap_text
from .tui_shortcuts import main_shortcut

_HELP_ITEMS = (
    ("Up/Down", ": move one selectable item"),
    (
        "Left/Right",
        ": Batch List Takes; Batch Item generation count or pronunciation controls",
    ),
    (
        "Enter",
        ": open a Batch List Caption or activate the focused Batch Item row",
    ),
    ("Space", ": toggle Batch List inclusion or replay a focused Take"),
    (
        main_shortcut("delete_caption").shortcut.upper(),
        ": delete current Batch Item Caption through confirmation",
    ),
    ("Esc", ": one level back"),
    ("Ctrl+C", ": cancel active Take generation; otherwise quit"),
    ("Tab / Shift+Tab", ": next / previous major Batch Item section"),
    (
        " / ".join(
            main_shortcut(name).shortcut.upper()
            for name in ("caption", "build_pronunciation", "add_section", "generate")
        ),
        ": Caption / Build pronunciation / Add section / Generate or regenerate all",
    ),
    ("1-9", ": focus and play an available Take"),
    ("[ / ]", ": previous / next Batch Item Caption or Dictionary word"),
    (main_shortcut("clear_candidates").shortcut.upper(), ": clear candidates through confirmation"),
    ("R", ": regenerate the focused Take"),
    (main_shortcut("settings").shortcut.upper(), ": open Settings"),
    (main_shortcut("dictionary").shortcut.upper(), ": open Dictionary"),
    ("A / G", ": Batch List Add captions / Generate selected"),
    (None, "Menu mode: editor/modal action letters are active."),
    (None, "Editing: Enter finishes; printable shortcut letters insert text."),
    (None, "Add captions: Ctrl+N inserts a new line; Enter finishes editing."),
    (main_shortcut("help").shortcut, ": open or close Help"),
    (main_shortcut("quit").shortcut.upper(), ": Quit"),
)


def help_document(width: int) -> list[tuple[tuple[int, str, bool], ...]]:
    """Build all physical Help rows before viewport clipping."""

    column = 1
    available = max(1, width - column - 1)
    rows: list[tuple[tuple[int, str, bool], ...]] = []

    def append_plain(value: str) -> None:
        for piece in _wrap_text(value, available) or [""]:
            rows.append(((column, piece, False),))

    append_plain(f"Voiceger Editor {__version__}")
    append_plain(f"Docs: {DOCUMENTATION_URL}")
    rows.append(())

    for shortcut, suffix in _HELP_ITEMS:
        if shortcut is None:
            append_plain(suffix)
            continue

        key_width = _display_width(shortcut)
        if key_width >= available:
            for piece in _wrap_text(shortcut, available) or [""]:
                rows.append(((column, piece, True),))
            for piece in _wrap_text(suffix, available) or [""]:
                rows.append(((column, piece, False),))
            continue

        explanation_pieces = _wrap_text(
            suffix, max(1, available - key_width)
        ) or [""]
        rows.append(
            (
                (column, shortcut, True),
                (column + key_width, explanation_pieces[0], False),
            )
        )
        for piece in explanation_pieces[1:]:
            rows.append(((column + key_width, piece, False),))

    return rows
