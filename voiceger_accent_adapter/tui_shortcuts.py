"""Declarative shortcut metadata for Main actions and editor/modal items."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping


MenuItemKind = Literal["editable", "adjustable", "action"]
ShortcutMode = Literal["activate", "focus"]


@dataclass(frozen=True)
class MenuItem:
    """One selectable editor/modal row and its local shortcut policy."""

    key: str
    label: str
    shortcut: str | None
    kind: MenuItemKind
    shortcut_mode: ShortcutMode | None = None
    condition_key: str | None = None
    no_shortcut_reason: str | None = None

    @property
    def display_label(self) -> str:
        if self.shortcut is None:
            return self.label
        return f"[{self.shortcut.upper()}] {self.label}"


@dataclass(frozen=True)
class MainShortcut:
    """One visible primary Main-screen action shortcut."""

    navigation_key: str
    label: str
    shortcut: str

    @property
    def display_label(self) -> str:
        return f"[{self.shortcut.upper()}] {self.label}"

    def display_with_label(self, label: str) -> str:
        return f"[{self.shortcut.upper()}] {label}"


_MAIN_SHORTCUTS: tuple[MainShortcut, ...] = (
    MainShortcut("build_pronunciation", "Build pronunciation", "b"),
    MainShortcut("add_section", "Add section", "a"),
    MainShortcut("generate", "Generate", "g"),
    MainShortcut("clear_candidates", "Clear candidates", "c"),
    MainShortcut("settings", "Settings", "s"),
    MainShortcut("dictionary", "Dictionary", "d"),
    MainShortcut("help", "Help", "?"),
    MainShortcut("quit", "Quit", "q"),
)


_MENU_DEFINITIONS: dict[str, tuple[MenuItem, ...]] = {
    "caption": (
        MenuItem(
            "draft",
            "Caption",
            None,
            "editable",
            no_shortcut_reason="Enter edits the Caption field.",
        ),
        MenuItem("apply", "Apply", "a", "action", "activate"),
        MenuItem("clear", "Clear", "c", "action", "activate"),
        MenuItem("reset", "Reset", "r", "action", "activate"),
        MenuItem("back", "Back", "b", "action", "activate"),
    ),
    "build_confirmation": (
        MenuItem("rebuild", "Rebuild", "r", "action", "activate"),
        MenuItem("cancel", "Cancel", "b", "action", "activate"),
    ),
    "japanese": (
        MenuItem(
            "pronunciation",
            "Pronunciation",
            None,
            "editable",
            no_shortcut_reason="Enter edits the pronunciation field.",
        ),
        MenuItem("preview", "Preview", "p", "action", "activate"),
        MenuItem("apply", "Apply", "a", "action", "activate"),
        MenuItem("save_dictionary", "Save to dictionary", "s", "action", "activate"),
        MenuItem("dictionary", "Dictionary menu", "d", "action", "activate"),
        MenuItem("edit_text", "Edit text", "e", "action", "activate"),
        MenuItem("clear", "Clear", "c", "action", "activate"),
        MenuItem("reset", "Reset", "r", "action", "activate"),
        MenuItem("back", "Back", "b", "action", "activate"),
    ),
    "english_word": (
        MenuItem(
            "phonemes",
            "Phonemes",
            None,
            "editable",
            no_shortcut_reason="Enter edits the phoneme field.",
        ),
        MenuItem("preview", "Preview", "p", "action", "activate"),
        MenuItem("apply", "Apply", "a", "action", "activate"),
        MenuItem("save_dictionary", "Save to dictionary", "s", "action", "activate"),
        MenuItem("dictionary", "Dictionary menu", "d", "action", "activate"),
        MenuItem("edit_text", "Edit text", "e", "action", "activate"),
        MenuItem("clear", "Clear", "c", "action", "activate"),
        MenuItem("reset", "Reset", "r", "action", "activate"),
        MenuItem("back", "Back", "b", "action", "activate"),
    ),
    "section_text": (
        MenuItem(
            "draft",
            "Text",
            None,
            "editable",
            no_shortcut_reason="Enter edits the section text field.",
        ),
        MenuItem("preview", "Preview", "p", "action", "activate"),
        MenuItem("apply", "Apply", "a", "action", "activate"),
        MenuItem("reset", "Reset", "r", "action", "activate"),
        MenuItem(
            "delete_section",
            "Delete section",
            "d",
            "action",
            "activate",
            condition_key="can_delete",
        ),
        MenuItem("back", "Back", "b", "action", "activate"),
    ),
    "add_section": (
        MenuItem(
            "language",
            "Language",
            None,
            "adjustable",
            no_shortcut_reason="Left/Right changes the focused language row.",
        ),
        MenuItem(
            "draft",
            "Text",
            None,
            "editable",
            no_shortcut_reason="Enter edits the new section text field.",
        ),
        MenuItem("add", "Add", "a", "action", "activate"),
        MenuItem("clear", "Clear", "c", "action", "activate"),
        MenuItem("reset", "Reset", "r", "action", "activate"),
        MenuItem("back", "Back", "b", "action", "activate"),
    ),
    "settings": (
        MenuItem("style_id", "Style", "s", "adjustable", "focus"),
        MenuItem("speed", "Speed", "v", "adjustable", "focus"),
        MenuItem("take_count", "Takes", "n", "adjustable", "focus"),
        MenuItem("output_dir", "Output", "o", "editable", "focus"),
        MenuItem("save_text", "TXT", "x", "adjustable", "focus"),
        MenuItem("top_k", "Top K", "k", "adjustable", "focus"),
        MenuItem("top_p", "Top P", "p", "adjustable", "focus"),
        MenuItem("temperature", "Temperature", "t", "adjustable", "focus"),
        MenuItem(
            "reset_sampling",
            "Reset sampling to Voiceger defaults",
            "d",
            "action",
            "activate",
        ),
        MenuItem("apply", "Apply and save", "a", "action", "activate"),
        MenuItem("reset", "Reset", "r", "action", "activate"),
        MenuItem("back", "Back", "b", "action", "activate"),
    ),
    "dictionary_menu": (
        MenuItem("japanese", "Japanese", "j", "action", "activate"),
        MenuItem("english", "English", "e", "action", "activate"),
        MenuItem("back", "Back", "b", "action", "activate"),
    ),
    "dictionary_japanese_list": (
        MenuItem("add", "Add", "a", "action", "activate"),
        MenuItem("delete", "Delete", "x", "action", "activate"),
        MenuItem("back", "Back", "b", "action", "activate"),
    ),
    "dictionary_english_list": (
        MenuItem("add", "Add", "a", "action", "activate"),
        MenuItem("delete", "Delete", "x", "action", "activate"),
        MenuItem("back", "Back", "b", "action", "activate"),
    ),
    "dictionary_japanese_duplicates": (
        MenuItem("back", "Back", "b", "action", "activate"),
    ),
    "dictionary_japanese_entry": (
        MenuItem(
            "surface",
            "Surface",
            None,
            "editable",
            no_shortcut_reason="Enter edits the Surface field.",
        ),
        MenuItem(
            "pronunciation",
            "Pronunciation",
            None,
            "adjustable",
            no_shortcut_reason="Enter edits reading; Left/Right moves accent.",
        ),
        MenuItem(
            "word_type",
            "Word type",
            None,
            "adjustable",
            no_shortcut_reason="Left/Right changes the focused word type.",
        ),
        MenuItem(
            "priority",
            "Priority",
            None,
            "adjustable",
            no_shortcut_reason="Left/Right changes the focused priority.",
        ),
        MenuItem("preview", "Preview", "p", "action", "activate"),
        MenuItem("save", "Save", "s", "action", "activate"),
        MenuItem("dictionary", "Dictionary menu", "d", "action", "activate"),
        MenuItem("back", "Back", "b", "action", "activate"),
    ),
    "dictionary_english_entry": (
        MenuItem(
            "surface",
            "Surface",
            None,
            "editable",
            no_shortcut_reason="Enter edits the Surface field.",
        ),
        MenuItem(
            "phonemes",
            "Pronunciation",
            None,
            "adjustable",
            no_shortcut_reason="Enter edits ARPAbet; Left/Right moves primary stress.",
        ),
        MenuItem("preview", "Preview", "p", "action", "activate"),
        MenuItem("save", "Save", "s", "action", "activate"),
        MenuItem("dictionary", "Dictionary menu", "d", "action", "activate"),
        MenuItem("back", "Back", "b", "action", "activate"),
    ),
    "dictionary_delete_confirmation": (
        MenuItem("delete", "Delete", "d", "action", "activate"),
        MenuItem("cancel", "Cancel", "b", "action", "activate"),
    ),
    "dictionary_discard_confirmation": (
        MenuItem("discard", "Discard", "d", "action", "activate"),
        MenuItem("cancel", "Cancel", "b", "action", "activate"),
    ),
    "delete_confirmation": (
        MenuItem("delete", "Delete", "d", "action", "activate"),
        MenuItem("cancel", "Cancel", "b", "action", "activate"),
    ),
    "clear_candidates_confirmation": (
        MenuItem("clear", "Clear candidates", "c", "action", "activate"),
        MenuItem("cancel", "Cancel", "b", "action", "activate"),
    ),
    "help": (
        MenuItem("back", "Back", "b", "action", "activate"),
    ),
}


def main_shortcuts() -> tuple[MainShortcut, ...]:
    """Return the visible primary Main-screen shortcut declarations."""

    return _MAIN_SHORTCUTS


def main_shortcut(navigation_key: str) -> MainShortcut:
    """Return one declared Main shortcut by navigation key."""

    for item in _MAIN_SHORTCUTS:
        if item.navigation_key == navigation_key:
            return item
    raise KeyError(f"Main has no shortcut declaration for {navigation_key!r}")


def resolve_main_shortcut(key: Any) -> MainShortcut | None:
    """Resolve one lowercase visible Main shortcut."""

    if not isinstance(key, str) or len(key) != 1:
        return None
    for item in _MAIN_SHORTCUTS:
        if item.shortcut == key:
            return item
    return None


def menu_definitions() -> Mapping[str, tuple[MenuItem, ...]]:
    """Return all declared editor/modal menu definitions for architecture tests."""

    return _MENU_DEFINITIONS


def menu_items(
    screen_kind: str,
    payload: Mapping[str, Any] | None = None,
) -> tuple[MenuItem, ...]:
    """Return currently selectable items in declared order."""

    values = payload or {}
    return tuple(
        item
        for item in _MENU_DEFINITIONS.get(screen_kind, ())
        if item.condition_key is None or bool(values.get(item.condition_key))
    )


def menu_item(
    screen_kind: str,
    key: str,
    payload: Mapping[str, Any] | None = None,
) -> MenuItem:
    """Return one currently selectable item or fail on stale rendering code."""

    for item in menu_items(screen_kind, payload):
        if item.key == key:
            return item
    raise KeyError(f"{screen_kind!r} has no selectable item {key!r}")


def resolve_shortcut(
    screen_kind: str,
    key: Any,
    payload: Mapping[str, Any] | None = None,
) -> MenuItem | None:
    """Resolve a lowercase local shortcut against the current selectable items."""

    if not isinstance(key, str) or len(key) != 1:
        return None
    for item in menu_items(screen_kind, payload):
        if item.shortcut == key:
            return item
    return None


def validate_menu_definitions() -> tuple[str, ...]:
    """Return declaration errors used by focused architecture regression tests."""

    errors: list[str] = []
    for screen_kind, items in _MENU_DEFINITIONS.items():
        seen_keys: set[str] = set()
        seen_shortcuts: dict[str, str] = {}
        for item in items:
            if item.key in seen_keys:
                errors.append(f"{screen_kind}: duplicate selection key {item.key!r}")
            seen_keys.add(item.key)

            if item.shortcut is None:
                if item.no_shortcut_reason is None:
                    errors.append(
                        f"{screen_kind}:{item.key}: missing shortcut without explicit exemption"
                    )
                if item.kind == "action" and item.no_shortcut_reason is None:
                    errors.append(
                        f"{screen_kind}:{item.key}: ordinary action requires a shortcut"
                    )
                if item.shortcut_mode is not None:
                    errors.append(
                        f"{screen_kind}:{item.key}: no shortcut cannot declare shortcut mode"
                    )
                continue

            if item.no_shortcut_reason is not None:
                errors.append(
                    f"{screen_kind}:{item.key}: shortcut item cannot also be exempt"
                )
            if len(item.shortcut) != 1 or item.shortcut != item.shortcut.lower():
                errors.append(
                    f"{screen_kind}:{item.key}: shortcut must be one lowercase character"
                )
            previous = seen_shortcuts.get(item.shortcut)
            if previous is not None:
                errors.append(
                    f"{screen_kind}: duplicate shortcut {item.shortcut!r} "
                    f"for {previous!r} and {item.key!r}"
                )
            else:
                seen_shortcuts[item.shortcut] = item.key
            if item.shortcut_mode is None:
                errors.append(
                    f"{screen_kind}:{item.key}: shortcut requires activate/focus mode"
                )
        for item in menu_items(
            screen_kind,
            {
                candidate.condition_key: True
                for candidate in items
                if candidate.condition_key is not None
            },
        ):
            if item.shortcut is not None and item.key not in {
                candidate.key for candidate in items
            }:
                errors.append(
                    f"{screen_kind}:{item.key}: shortcut target is not declared selectable"
                )
    seen_main_keys: set[str] = set()
    seen_main_shortcuts: set[str] = set()
    for item in _MAIN_SHORTCUTS:
        if item.navigation_key in seen_main_keys:
            errors.append(
                f"main: duplicate navigation key {item.navigation_key!r}"
            )
        seen_main_keys.add(item.navigation_key)
        if len(item.shortcut) != 1 or item.shortcut != item.shortcut.lower():
            errors.append(
                f"main:{item.navigation_key}: shortcut must be one lowercase character"
            )
        if item.shortcut in seen_main_shortcuts:
            errors.append(f"main: duplicate shortcut {item.shortcut!r}")
        seen_main_shortcuts.add(item.shortcut)
    return tuple(errors)
