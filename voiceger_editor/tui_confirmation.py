"""Reusable mechanics for narrow two-choice TUI confirmation screens."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .tui_display import _display_width
from .tui_selection import move_clamped_selection
from .tui_shortcuts import menu_items, resolve_shortcut


_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}
_ESCAPE = "\x1b"


@dataclass(frozen=True)
class ConfirmationInteraction:
    """Result of interpreting one key within a confirmation screen."""

    selection: str
    activation: str | None = None
    handled: bool = False
    changed: bool = False


@dataclass(frozen=True)
class ConfirmationDetail:
    """One read-only label/value pair shown above a confirmation warning."""

    label: str
    value: str


ConfirmationLine = tuple[str, str | None]
WrapText = Callable[[str, int], Sequence[str]]


def handle_confirmation_key(
    screen_kind: str,
    selection: str,
    key: Any,
    payload: Mapping[str, Any] | None = None,
) -> ConfirmationInteraction:
    """Interpret shared confirmation navigation without executing feature actions."""

    items = menu_items(screen_kind, payload)
    keys = tuple(item.key for item in items)
    if not keys:
        return ConfirmationInteraction(selection)

    if key == _ESCAPE and "cancel" in keys:
        return ConfirmationInteraction(
            "cancel",
            activation="cancel",
            handled=True,
            changed=selection != "cancel",
        )

    if key in (curses.KEY_UP, curses.KEY_DOWN):
        result = move_clamped_selection(
            selection,
            keys,
            delta=-1 if key == curses.KEY_UP else 1,
        )
        assert result is not None
        return ConfirmationInteraction(
            result.selection,
            handled=True,
            changed=result.changed,
        )

    shortcut = resolve_shortcut(screen_kind, key, payload)
    if shortcut is not None:
        return ConfirmationInteraction(
            shortcut.key,
            activation=(
                shortcut.key if shortcut.shortcut_mode == "activate" else None
            ),
            handled=True,
            changed=selection != shortcut.key,
        )

    if key in _ENTER_KEYS:
        return ConfirmationInteraction(
            selection,
            activation=selection if selection in keys else None,
            handled=True,
        )

    return ConfirmationInteraction(selection)


def confirmation_lines(
    screen_kind: str,
    selection: str,
    *,
    warning: str,
    details: Sequence[ConfirmationDetail] = (),
    payload: Mapping[str, Any] | None = None,
    width: int,
    wrap_text: WrapText,
) -> tuple[ConfirmationLine, ...]:
    """Build the shared detail/warning/action-row confirmation document body."""

    lines: list[ConfirmationLine] = [("", None)]

    def wrapped(prefix: str, value: str) -> None:
        available = max(1, width - 1 - _display_width(prefix))
        pieces = tuple(wrap_text(value, available)) or ("",)
        lines.append((prefix + pieces[0], None))
        continuation = " " * _display_width(prefix)
        lines.extend((continuation + piece, None) for piece in pieces[1:])

    for detail in details:
        lines.append((detail.label, None))
        wrapped("  ", detail.value)
        lines.append(("", None))

    if warning:
        wrapped("", warning)
        lines.append(("", None))

    for item in menu_items(screen_kind, payload):
        marker = "▶ " if selection == item.key else "  "
        lines.append((marker + item.display_label, item.key))

    return tuple(lines)
