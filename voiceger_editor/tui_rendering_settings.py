"""Settings editor document construction."""

from __future__ import annotations

from .settings import (
    VOICEGER_DEFAULT_TEMPERATURE,
    VOICEGER_DEFAULT_TOP_K,
    VOICEGER_DEFAULT_TOP_P,
)
from .tui_display import _adjustable_value
from .tui_rendering_editor_common import EditorDocumentBuilder
from .tui_rendering_shared import adjustment_press_direction, setting_display
from .tui_shortcuts import menu_item

_OUTPUT_FORMAT_LABELS = {
    "wav": "WAV",
    "flac": "FLAC",
    "mp3": "MP3",
}
_OUTPUT_ENCODING_LABELS = {
    "source": "Source",
    "pcm16": "PCM 16-bit",
    "pcm24": "PCM 24-bit",
    "float32": "Float 32-bit",
}


def build_document(builder: EditorDocumentBuilder) -> bool:
    editor = builder.editor
    state = builder.state
    width = builder.width
    lines = builder.lines
    plain = builder.plain
    wrap = builder.wrap
    selectable = builder.selectable
    selectable_value = builder.selectable_value
    wrapped_selectable_text = builder.wrapped_selectable_text
    input_field = builder.input_field
    path_input_field = builder.path_input_field
    shared_output_field = builder.shared_output_field
    if editor.kind == "settings":
        draft = editor.payload["draft_settings"]
        values = (
            (
                "style_id",
                setting_display("style_id", draft["style_id"], state.voiceger_root),
            ),
            (
                "speed",
                setting_display("speed", draft["speed"], state.voiceger_root),
            ),
            ("take_count", str(draft["take_count"])),
            ("output_dir", str(draft["output_dir"])),
            ("top_k", str(draft.get("top_k", VOICEGER_DEFAULT_TOP_K))),
            (
                "top_p",
                f"{float(draft.get('top_p', VOICEGER_DEFAULT_TOP_P)):.2f}",
            ),
            (
                "temperature",
                f"{float(draft.get('temperature', VOICEGER_DEFAULT_TEMPERATURE)):.2f}",
            ),
        )
        section_headers = {
            "style_id": "Voice",
            "take_count": "Generation",
            "output_dir": "Output",
            "top_k": "Sampling",
        }
        candidate_clearing = {
            "style_id", "speed", "top_k", "top_p", "temperature"
        }
        for key, value in values:
            heading = section_headers.get(key)
            if heading is not None:
                plain(heading)
            item = menu_item(editor.kind, key, editor.payload)
            label = item.label + (" *" if key in candidate_clearing else "")
            if editor.active_field == key:
                input_field(
                    key,
                    _active_input_prefix(editor)
                    if key == "output_dir"
                    else f"▶ {label:<16}",
                )
            else:
                if key in {
                    "style_id", "speed", "take_count",
                    "top_k", "top_p", "temperature",
                }:
                    value = _adjustable_value(
                        value,
                        adjustment_press_direction(state, "settings", key),
                    )
                marker = "▶ " if editor.selection == key else "  "
                visible_label = (
                    f"[{item.shortcut.upper()}] {label}"
                    if item.shortcut is not None
                    else label
                )
                lines.append((f"{marker}{visible_label:<20}{value}", key))
            if key == "output_dir":
                selectable("audio_output")
        selectable("reset_sampling")
        plain("Actions")
        selectable("apply")
        selectable("reset")
        selectable("back")
        plain("* Applying this setting clears existing candidates.")
    elif editor.kind == "audio_output_settings":
        draft = editor.payload["draft_settings"]
        output_format = str(draft.get("output_format", "wav"))
        controls = [
            (
                "output_format",
                _OUTPUT_FORMAT_LABELS.get(output_format, output_format),
            )
        ]
        if output_format == "mp3":
            bitrate = str(draft.get("mp3_bitrate", "192k"))
            controls.append(("mp3_bitrate", bitrate.replace("k", " kbps")))
        else:
            encoding_key = (
                "wav_encoding" if output_format == "wav" else "flac_encoding"
            )
            output_encoding = str(draft.get(encoding_key, "source"))
            controls.append(
                (
                    "output_encoding",
                    _OUTPUT_ENCODING_LABELS.get(output_encoding, output_encoding),
                )
            )
        control_payload = dict(editor.payload)
        control_payload["show_output_encoding"] = output_format != "mp3"
        control_payload["show_mp3_bitrate"] = output_format == "mp3"
        plain()
        for key, value in controls:
            item = menu_item(editor.kind, key, control_payload)
            marker = "▶ " if editor.selection == key else "  "
            value = _adjustable_value(
                value,
                adjustment_press_direction(state, "settings", key),
            )
            lines.append((f"{marker}{item.display_label:<18}{value}", key))
        plain()
        if editor.active_field == "filename_template":
            input_field("filename_template")
        else:
            wrapped_selectable_text(
                "filename_template",
                "Filename template  " + str(draft["filename_template"]),
            )
        plain()
        plain("Preview")
        preview_error = str(editor.payload.get("filename_preview_error", ""))
        if preview_error:
            wrap("  Invalid: ", preview_error)
        else:
            wrap("  ", str(editor.payload.get("filename_preview", "")))
        plain()
        plain("Sidecars")
        for key in ("save_text", "save_lab"):
            item = menu_item(editor.kind, key, editor.payload)
            marker = "▶ " if editor.selection == key else "  "
            value = "ON" if draft.get(key, False) else "OFF"
            value = _adjustable_value(
                value,
                adjustment_press_direction(state, "settings", key),
            )
            lines.append((f"{marker}{item.display_label:<14}{value}", key))
        plain()
        plain("Tokens: YYYY MM DD HH mm ss · {text} {style}")
        selectable("back")
    else:
        return False
    return True
