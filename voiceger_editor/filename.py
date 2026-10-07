"""Helpers for user-facing synthesized audio filenames."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Optional


_INVALID_FILENAME_CHARS = re.compile(r'[\x00-\x1f"*/:<>?\\|\x7f]')
DEFAULT_FILENAME_TEMPLATE = "{YYYYMMDDHHmm}_{text}"

_DATE_TIME_TOKEN_RENDERERS = {
    "YYYY": lambda value: f"{value.year:04d}",
    "MM": lambda value: f"{value.month:02d}",
    "DD": lambda value: f"{value.day:02d}",
    "HH": lambda value: f"{value.hour:02d}",
    "mm": lambda value: f"{value.minute:02d}",
    "ss": lambda value: f"{value.second:02d}",
}
_DATE_TIME_TOKENS = tuple(
    sorted(_DATE_TIME_TOKEN_RENDERERS, key=len, reverse=True)
)


class FilenameTemplateError(ValueError):
    """Raised when an accepted-output filename template is invalid."""


def sanitize_filename_part(value: str) -> str:
    """Mirror VOICEVOX's filename sanitization for user-facing fields."""

    return _INVALID_FILENAME_CHARS.sub("", value)


def _render_date_time_pattern(pattern: str, value: datetime) -> str:
    rendered: list[str] = []
    index = 0
    saw_token = False
    while index < len(pattern):
        matched = next(
            (
                token
                for token in _DATE_TIME_TOKENS
                if pattern.startswith(token, index)
            ),
            None,
        )
        if matched is not None:
            rendered.append(_DATE_TIME_TOKEN_RENDERERS[matched](value))
            index += len(matched)
            saw_token = True
            continue

        character = pattern[index]
        if character.isalpha():
            raise FilenameTemplateError(
                f"unsupported date/time token in {{{pattern}}}"
            )
        rendered.append(character)
        index += 1

    if not saw_token:
        raise FilenameTemplateError(
            f"unknown template variable {{{pattern}}}"
        )
    return "".join(rendered)


def _render_template(
    template: str,
    *,
    text: str,
    style: str,
    timestamp: datetime,
) -> str:
    rendered: list[str] = []
    index = 0
    while index < len(template):
        character = template[index]
        if character == "}":
            raise FilenameTemplateError("unmatched '}' in filename template")
        if character != "{":
            next_open = template.find("{", index)
            next_close = template.find("}", index)
            boundaries = tuple(
                boundary
                for boundary in (next_open, next_close)
                if boundary >= 0
            )
            end = min(boundaries) if boundaries else len(template)
            rendered.append(template[index:end])
            index = end
            continue

        close = template.find("}", index + 1)
        if close < 0:
            raise FilenameTemplateError("unmatched '{' in filename template")
        if template.find("{", index + 1, close) >= 0:
            raise FilenameTemplateError("nested '{' in filename template")

        field = template[index + 1 : close]
        if not field:
            raise FilenameTemplateError("empty '{}' field in filename template")
        if field == "text":
            rendered.append(text)
        elif field == "style":
            rendered.append(style)
        else:
            rendered.append(_render_date_time_pattern(field, timestamp))
        index = close + 1

    return "".join(rendered)


def validate_filename_template(template: str) -> None:
    """Validate one filename template without exposing host formatting syntax."""

    if not isinstance(template, str):
        raise FilenameTemplateError("filename template must be a string")
    if not template:
        raise FilenameTemplateError("filename template must not be empty")
    _render_template(
        template,
        text="text",
        style="style",
        timestamp=datetime(2000, 1, 2, 3, 4, 5),
    )


def render_output_basename(
    *,
    template: str,
    text: str,
    style: str,
    timestamp: Optional[datetime] = None,
) -> str:
    """Render and sanitize an accepted-output basename."""

    validate_filename_template(template)
    local_time = timestamp if timestamp is not None else datetime.now()
    rendered = _render_template(
        template,
        text=text,
        style=style,
        timestamp=local_time,
    )
    sanitized = sanitize_filename_part(rendered)
    if not sanitized:
        raise FilenameTemplateError(
            "filename template renders an empty basename after sanitization"
        )
    return sanitized


def build_output_filename(
    *,
    text: str,
    timestamp: Optional[datetime] = None,
    style: str = "",
    filename_template: str = DEFAULT_FILENAME_TEMPLATE,
) -> str:
    """Build the current WAV output filename from a validated template."""

    basename = render_output_basename(
        template=filename_template,
        text=text,
        style=style,
        timestamp=timestamp,
    )
    return f"{basename}.wav"
