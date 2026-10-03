# TUI Architecture

The TUI is split between a composition root and focused owners. The composition root wires the terminal lifecycle and shared application state to the subsystem responsible for each interaction.

## Ownership map

| Module | Responsibility |
| --- | --- |
| `voiceger_editor/tui.py` | TUI composition root; curses run loop and cleanup lifecycle; top-level mode/key dispatch; shared session/settings application orchestration; dispatch between focused subsystems; CLI entrypoint. |
| `voiceger_editor/tui_cli.py` | CLI argument declarations and per-invocation settings overrides, re-exported by the composition root for compatibility. |
| `voiceger_editor/tui_batch.py` | Top-level Batch List collection ownership, focus/navigation state, inclusion toggling, Batch Item selection, and Batch List key interpretation. |
| `voiceger_editor/tui_dictionary.py` | User-dictionary modal state, keyboard interaction, quick-save resolution, CRUD drafts, confirmation policy, and dictionary preview intents. |
| `voiceger_editor/tui_navigation.py` | Selectable item ordering; focus state; remembered pronunciation segment; navigation revision; Up/Down and major-section movement; navigation action interpretation. |
| `voiceger_editor/tui_editors.py` | Editor state and drafts; text, Japanese, English, and settings interaction policy; English grouping cache; editor validation; typed editor intents and results. |
| `voiceger_editor/tui_shortcuts.py` | Declarative Main primary-action shortcuts plus editor/modal selectable-item metadata; visible shortcut labels and dispatch share the same declarations, while editor/modal declarations also own selection order, shortcut behavior, conditions, and explicit no-shortcut exceptions. |
| `voiceger_editor/tui_operations.py` | Synthesis worker lifecycle and event queue; operation progress; candidate playback and acceptance; typed operation effects. |
| `voiceger_editor/tui_rendering.py` | Batch List, Batch Item navigation, editor, and help document construction; terminal rendering; render-state presentation; terminal drawing behavior. |
| `voiceger_editor/tui_display.py` | Pure display-cell width; wrapping and truncation; cursor movement across wrapped input; phoneme and display-formatting helpers. |

## Dependency direction

The composition root may depend on focused TUI modules. Focused TUI modules may depend on reusable application/core modules and narrowly on other focused owners where the existing design requires it. The enforced boundary is one-way at the top: extracted TUI modules must not depend back on `tui.py` or `TuiApp`. The focused modules do not need to be completely independent of one another.

## Placement guidance

Frontend-only interaction belongs in TUI modules. Examples include key interpretation, focus movement, modal editor interaction, one-frame pressed feedback, terminal wrapping and rendering, and playback coordination initiated by TUI candidate review.

Reusable application or core behavior belongs outside TUI modules. Examples include pronunciation or query transformation used by other frontends, synthesis and session behavior, settings models and persistence primitives, output naming and saving, API-compatible models, and reusable business rules.

When a substantial new responsibility has no appropriate existing owner, give it a focused module instead of adding that state or policy to `TuiApp`.
