# TUI Architecture

The TUI is split between a composition root and focused owners. The composition root wires the terminal lifecycle and shared application state to the subsystem responsible for each interaction.

Keyboard interaction and presentation conventions are documented separately in [TUI UI Guidelines](./tui-ui-guidelines.md).

## Ownership map

| Module | Responsibility |
| --- | --- |
| `voiceger_editor/tui.py` | TUI composition root; curses run loop and cleanup lifecycle; top-level mode routing; shared session ownership and focused-owner wiring; dispatch between focused subsystems; CLI entrypoint. |
| `voiceger_editor/tui_cli.py` | CLI argument declarations and per-invocation settings overrides, re-exported by the composition root for compatibility. |
| `voiceger_editor/tui_batch.py` | Top-level Batch List collection ownership, focus/navigation state, inclusion toggling, stable-ID Caption deletion confirmation and operation-owned deletion guards, removed-session cleanup, validated batch replacement, Batch Item selection state, and Batch List key interpretation. |
| `voiceger_editor/tui_batch_recipe.py` | Batch recipe Read input-path editing, Write file-name state, replacement-confirmation interaction state, and delegation to the frontend-neutral recipe core; Write resolves its target under the shared Output directory and owns no JSON/schema policy. |
| `voiceger_editor/tui_batch_item.py` | Batch Item key interpretation and action routing; same-level Caption movement; stable-item mutation conflict routing; candidate review/accept/regeneration coordination; Build pronunciation and Take-count interaction policy; Batch Item segment/pronunciation-row derivation. |
| `voiceger_editor/tui_dictionary.py` | Dictionary coordination and routing: top-level menu and export flow, Japanese / English list coordination, sort / filter interaction with `DictionaryListStateOwner`, shared editor and parent-stack coordination, key routing between Dictionary owners, and guarded background-operation dispatch. |
| `voiceger_editor/tui_dictionary_import.py` | Dictionary Import path, review, and detail interaction state; item identity and selection policy; Japanese word-type adjustment; load / commit requests; and UI-thread application of Import completion, Status, and error outcomes. |
| `voiceger_editor/tui_dictionary_entry.py` | Japanese / English Dictionary entry editors and drafts; quick-save resolution; validation, dirty-state, and entry navigation policy; pronunciation and preview requests; save / delete confirmation and requests; and UI-thread application of entry-operation outcomes with stable list-focus restoration. |
| `voiceger_editor/tui_dictionary_operations.py` | Typed Dictionary background-operation identity, language, request, and intent boundary; snapshots worker input while retaining the originating editor identity. |
| `voiceger_editor/tui_dictionary_word_types.py` | Shared Japanese Dictionary word-type choices and labels used by Import review and entry editing. |
| `voiceger_editor/tui_help.py` | Help open/closed state, scroll position, close/quit key outcomes, and Help scroll/clamping policy. |
| `voiceger_editor/tui_input.py` | Terminal input decoding; Add captions paste-newline inference from already queued input while preserving ordinary curses keys and terminal modes; normalizes signal-form Ctrl+C to the shared key representation. |
| `voiceger_editor/tui_interrupts.py` | Global Ctrl+C interpretation: cooperative Take-generation cancellation, post-completion cancellation-race guard handling, and idle Ctrl+C quit routing; safety state remains owned by the operation lifecycle. |
| `voiceger_editor/tui_text_editing.py` | Shared feature-neutral editable-field text/cursor key mechanics: horizontal and wrapped vertical cursor movement, Home/End, deletion, printable insertion, and handled/change result reporting. |
| `voiceger_editor/tui_output_path.py` | Shared in-place `Settings.output_dir` editor used by Batch Item, Batch Write, and Dictionary Export; owns the F-key text-edit lifecycle and delegates persistence to the Settings owner. |
| `voiceger_editor/tui_navigation.py` | Selectable item ordering; focus state; remembered pronunciation segment; navigation revision; Up/Down and major-section movement; navigation action interpretation. |
| `voiceger_editor/tui_numbered_list.py` | Shared 1-based direct numeric shortcut and explicit arbitrary-number input state for numbered lists; owns digit collection, validation, cancel/backspace handling, and timeout-free key suppression without owning feature-specific activation. |
| `voiceger_editor/tui_selection.py` | Pure shared clamped Up / Down selection movement over owner-provided ordered sequences; resolves current item/index and reports resulting selection plus changed state without owning selectable-item lists or feature side effects. |
| `voiceger_editor/tui_confirmation.py` | Reusable narrow confirmation-screen shell: declarative action ordering/labels, Up / Down / Enter / direct-shortcut / Esc input interpretation, and shared detail/warning/action-row document construction; feature owners retain payload semantics, action execution, dirty state, async behavior, and Status outcomes. |
| `voiceger_editor/tui_adjustments.py` | Pure shared Left / Right value-stepping helpers for bounded values and intentionally cyclic categorical choices; returns updated values plus changed / unchanged state without owning feature-specific ranges, steps, or options. |
| `voiceger_editor/tui_editors.py` | Compatibility facade and feature-neutral editor coordination; owns the single active editor reference, shared selection/text-field routing, generic confirmation routing, and delegation across focused editor-family owners. |
| `voiceger_editor/tui_editor_common.py` | Shared editor state plus typed editor intent/result contracts and focused-owner plumbing. |
| `voiceger_editor/tui_editor_text.py` | Caption, multiline Add Captions, Add Section, and section-text draft/preview/apply/delete interaction policy. |
| `voiceger_editor/tui_editor_pronunciation.py` | Pronunciation-row construction plus Japanese/English direct pronunciation editor interaction, validation, preview, and apply routing. |
| `voiceger_editor/tui_editor_english.py` | English word grouping snapshots, grouping cache/error state, reconciliation/remapping, and Main stress adjustment policy. |
| `voiceger_editor/tui_editor_settings.py` | Settings and Audio Output Settings drafts, navigation, validation, adjustment, filename-preview, reset, and apply policy. |
| `voiceger_editor/tui_shortcuts.py` | Declarative Main primary-action shortcuts plus editor/modal selectable-item metadata; visible shortcut labels and dispatch share the same declarations, while editor/modal declarations also own selection order, shortcut behavior, conditions, and explicit no-shortcut exceptions. |
| `voiceger_editor/tui_settings.py` | TUI runtime/persisted Settings reconciliation, persistence outcomes, operation-aware settings conflict checks, synthesis-setting invalidation policy, and Batch default Take-count synchronization. |
| `voiceger_editor/tui_operations.py` | Compatibility facade and authoritative single-worker lifecycle, queue, progress, cancellation, stable Caption ownership, deferred start, completion transitions, and UI-thread effect application. Delegates execution and pure operation policy to focused owners. |
| `voiceger_editor/tui_operation_contracts.py` | Typed operation effects, completion/progress events, and immutable cross-screen progress snapshots; no shared mutable state. |
| `voiceger_editor/tui_operation_workers.py` | Background work builders for Batch/individual synthesis, Preview, preparation, and Dictionary; accept call-time inputs, cancellation events, and typed event callbacks; do not own lifecycle state. |
| `voiceger_editor/tui_operation_playback.py` | Focused owner for the single playback process, pronunciation-preview temporary audio, player selection, and current Take playback selection; owns no synthesis worker state. |
| `voiceger_editor/tui_operation_conflicts.py` | Stateless authoritative policy for shared-resource, Caption-mutation, Settings, and generation conflict Status outcomes; evaluates lifecycle snapshots supplied by `TuiOperations` without copying operation state. |
| `voiceger_editor/tui_operation_acceptance.py` | Focused Take-save execution and saved-output completion policy; builds deferred acceptance work and completion effects while shared worker lifecycle state remains in `TuiOperations`. |
| `voiceger_editor/tui_status.py` | Shared semantic TUI Status model, severity constructors, and the single visible prefix formatter. |
| `voiceger_editor/tui_rendering.py` | Low-level curses drawing, semantic terminal attributes, shared Status/background footer layout, viewport clipping/cursor placement, and compatibility delegation to focused document builders. |
| `voiceger_editor/tui_rendering_shared.py` | Read-only render-state protocols/dataclasses plus reusable pure presentation helpers shared across screen document builders. |
| `voiceger_editor/tui_rendering_help.py` | Help document construction and Help shortcut/explanation presentation data. |
| `voiceger_editor/tui_rendering_batch.py` | Batch List document construction, including numbered-caption rows, selection/review state, Take-count presentation, and action grouping. |
| `voiceger_editor/tui_rendering_navigation.py` | Batch Item navigation document construction for Caption, pronunciation, candidate, generation, and top-level action rows. |
| `voiceger_editor/tui_rendering_editor_common.py` | Shared editor-document accumulation primitives for wrapping, selectable rows, editable fields, and shared Output-path presentation. |
| `voiceger_editor/tui_rendering_editor.py` | Editor document dispatch and shared title/Dictionary-entry navigator construction. |
| `voiceger_editor/tui_rendering_editor_general.py` | General editor-family documents: confirmations, Caption/pronunciation editors, batch-recipe path screens, and section text/add flows. |
| `voiceger_editor/tui_rendering_settings.py` | Settings and Audio Output Settings document construction. |
| `voiceger_editor/tui_rendering_dictionary.py` | Dictionary menu/import/list/filter/entry/detail document construction and Dictionary-specific row formatting. |
| `voiceger_editor/tui_display.py` | Pure display-cell width; wrapping and truncation; cursor movement across wrapped input; phoneme and display-formatting helpers. |

## Dependency direction

The composition root may depend on focused TUI modules. Focused TUI modules may depend on reusable application/core modules and narrowly on other focused owners where the existing design requires it. The enforced boundary is one-way at the top: extracted TUI modules must not depend back on `tui.py` or `TuiApp`. The focused modules do not need to be completely independent of one another.

## Placement guidance

Frontend-only interaction belongs in TUI modules. Examples include key interpretation, focus movement, modal editor interaction, one-frame pressed feedback, terminal wrapping and rendering, and playback coordination initiated by TUI candidate review.

Reusable application or core behavior belongs outside TUI modules. Examples include pronunciation or query transformation used by other frontends, synthesis and session behavior, settings models and persistence primitives, output naming and saving, API-compatible models, and reusable business rules.

When new TUI state, policy, interaction behavior, rendering behavior, operation behavior, or another responsibility has no appropriate existing owner, give it a focused module instead of adding it to `TuiApp`.

## Module and structure growth review guards

The repository unit suite scans Python modules under `voiceger_editor/` and `tests/` for silent large-file growth. The current module review triggers are 1,500 physical source lines for production modules and 3,500 lines for test modules.

A second AST-based guard reviews extreme local concentration that module length alone can miss. Its current triggers are 250 source lines for a single function or method and 50 direct methods for a class.

These values are review triggers, not architecture definitions. When a module or symbol reaches a trigger, first decide whether the responsibility belongs in an existing focused owner or a coherent new owner. Do not extract arbitrary fragments merely to reduce a number, split one coherent method into meaningless helpers, or use formatting compression, code golf, or other metric-gaming tricks to evade the guards.

Current modules that intentionally remain above a module trigger are recorded in `tests/module_growth_exceptions.json`. Reviewed local concentrations are recorded in `tests/structure_growth_exceptions.json` by path, qualified symbol, metric, and reviewed maximum. Each exception has a responsibility justification, plus a follow-up Issue when the exception is temporary debt. An excepted module or symbol may not silently grow beyond its reviewed baseline. Once a refactor brings it below the trigger, remove the exception.

File length and structural metrics therefore remain subordinate to responsibility ownership. `tui.py` may grow or shrink as composition wiring changes, but it must not become the owner of new feature behavior. The existing dependency boundary preventing extracted TUI modules from importing `tui.py` or `TuiApp` remains independently enforced.
