"""Batch Item navigation document construction."""

from __future__ import annotations

from .tui_display import (
    _adjustable_value,
    _display_width,
    _english_display_tokens,
    _japanese_mora_tokens,
    _wrap_tokens_with_prefixes,
    _wrap_text,
)
from .tui_editors import PronunciationRow
from .tui_rendering_shared import (
    NavigationLine,
    TuiRenderState,
    _duration_seconds,
    _numbered_shortcut_token,
    adjustment_press_direction,
)
from .tui_shortcuts import main_shortcut

def navigation_document(
    state: TuiRenderState,
    width: int,
) -> list[NavigationLine]:
    lines: list[NavigationLine] = []
    row_limit = max(1, width - 1)

    def plain(value: str = "") -> None:
        lines.append(NavigationLine(value, None))

    def action(key: tuple[str, int | None], label: str) -> None:
        marker = "▶ " if key == state.focus_key else "  "
        lines.append(NavigationLine(marker + label, key, key))

    def caption_action(key: tuple[str, int | None], value: str) -> None:
        marker = "▶ " if key == state.focus_key else "  "
        prefix = (
            f"{marker}{main_shortcut('caption').display_with_label('Caption')} : "
        )
        available = max(1, width - 1 - _display_width(prefix))
        pieces = _wrap_text(value, available) or [""]
        lines.append(NavigationLine(prefix + pieces[0], key, key))
        continuation = " " * _display_width(prefix)
        lines.extend(
            NavigationLine(continuation + piece, None, key)
            for piece in pieces[1:]
        )

    def pronunciation_action(index: int, item: PronunciationRow) -> None:
        key = ("pronunciation", index)
        marker = "▶ " if key == state.focus_key else "  "
        language_prefix = (
            f"{item.language.upper()} | "
            if item.first_in_segment
            else "   | "
        )
        first_prefix = marker + language_prefix
        continuation_prefix = "     | "

        if item.language == "ja":
            tokens = _japanese_mora_tokens(item.moras, item.accent or 1)
            if item.punctuation_suffix:
                tokens[-1] += item.punctuation_suffix
            physical, _cursor = _wrap_tokens_with_prefixes(
                first_prefix,
                continuation_prefix,
                tokens,
                row_limit,
            )
            for physical_index, value in enumerate(physical):
                lines.append(
                    NavigationLine(
                        value,
                        key if physical_index == 0 else None,
                        key,
                    )
                )
            return

        if item.language == "en" and item.word is not None:
            word_width = item.word_column_width or _display_width(item.word)
            word_field = item.word + " " * max(
                3, word_width - _display_width(item.word) + 3
            )
            tokens = _english_display_tokens(item.phonemes) or ["(none)"]
            widest_phone = max((_display_width(token) for token in tokens), default=1)
            source_column = _display_width(first_prefix)
            source_span = _display_width(item.word)
            if source_column + _display_width(word_field) + widest_phone > row_limit:
                physical = [first_prefix + item.word]
                wrapped, _cursor = _wrap_tokens_with_prefixes(
                    continuation_prefix,
                    continuation_prefix,
                    tokens,
                    row_limit,
                )
                physical.extend(wrapped)
                bold_spans = ((source_column, source_span),)
            else:
                phone_prefix = first_prefix + word_field
                wrapped, _cursor = _wrap_tokens_with_prefixes(
                    phone_prefix,
                    continuation_prefix + " " * (word_width + 3),
                    tokens,
                    row_limit,
                )
                physical = wrapped
                bold_spans = ((source_column, source_span),)
            for physical_index, value in enumerate(physical):
                lines.append(
                    NavigationLine(
                        value,
                        key if physical_index == 0 else None,
                        key,
                        bold_spans if physical_index == 0 else (),
                    )
                )
            return

        label = item.source_text or "Unavailable"
        value_prefix = first_prefix
        pieces = _wrap_text(label, max(1, row_limit - _display_width(value_prefix)))
        physical = [value_prefix + (pieces[0] if pieces else "Unavailable")]
        physical.extend(continuation_prefix + piece for piece in pieces[1:])
        for physical_index, value in enumerate(physical):
            lines.append(
                NavigationLine(
                    value,
                    key if physical_index == 0 else None,
                    key,
                )
            )

    session = state.session
    caption_action(("caption", None), session.caption if session else "")
    if session is not None:
        action(
            ("build_pronunciation", None),
            main_shortcut("build_pronunciation").display_label,
        )
        plain()
        for index, item in enumerate(state.pronunciation_rows):
            pronunciation_action(index, item)
        plain()
        action(
            ("add_section", None),
            main_shortcut("add_section").display_label,
        )
        has_batch = session.has_active_batch
        owns_generation = (
            state.busy
            and state.batch_item_id is not None
            and state.batch_item_id == state.active_generation_item_id
        )
        if owns_generation:
            if state.worker_operation == "regenerate_one":
                generate_label = f"Regenerating take {state.worker_target}"
            else:
                current = min(
                    state.operation_completed + 1,
                    max(1, state.operation_total),
                )
                verb = (
                    "Regenerating"
                    if state.worker_operation == "regenerate_all"
                    else "Generating"
                )
                generate_label = f"{verb} {current}/{state.operation_total}"
        else:
            adjustable_count = _adjustable_value(
                str(state.settings.take_count),
                adjustment_press_direction(state, "navigation", "generate"),
            )
            generate_label = (
                f"Regenerate all {adjustable_count} takes"
                if has_batch
                else f"Generate {adjustable_count} takes"
            )
            if (
                state.busy
                and state.worker_operation
                in {"initial", "regenerate_one", "regenerate_all", "batch_generate"}
            ):
                generate_label += " [busy]"
        plain()
        candidates = tuple(session.candidates)
        if not candidates:
            plain("Candidates   No candidates yet.")
        else:
            plain("Candidates")
            if len(candidates) >= 10:
                if state.batch_item_number_jump_active:
                    plain(
                        "▶ Jump to Take: "
                        f"{state.batch_item_number_jump_value}_ / {len(candidates)}"
                    )
                    plain("  [Enter] Play   [Esc] Cancel")
                else:
                    plain("  [0] Jump to Take")
                plain()
        for candidate in candidates:
            duration = _duration_seconds(
                candidate.frame_count,
                candidate.sampling_rate,
            )
            number_token = _numbered_shortcut_token(
                candidate.number,
                len(candidates),
            )
            accepted_marker = (
                " ✓" if candidate.number == state.accepted_take_number else ""
            )
            label = (
                f"{number_token}  Take {candidate.number}  {duration:.2f}s"
                f"{accepted_marker}"
            )
            action(
                ("candidate", candidate.number),
                label,
            )
        if session.candidates:
            plain()
        action(
            ("generate", None),
            main_shortcut("generate").display_with_label(generate_label),
        )
        if session.candidates:
            action(
                ("clear_candidates", None),
                main_shortcut("clear_candidates").display_label,
            )
        plain()
        action(
            ("delete_caption", None),
            main_shortcut("delete_caption").display_label,
        )
        plain()

    action(("settings", None), main_shortcut("settings").display_label)
    action(("dictionary", None), main_shortcut("dictionary").display_label)
    action(("help", None), main_shortcut("help").display_label)
    action(("quit", None), main_shortcut("quit").display_label)
    return lines
