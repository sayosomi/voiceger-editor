"""Shared notice and explicit acceptance state for Voiceger:Zundamon terms."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .settings import default_config_path


CURRENT_NOTICE_VERSION = 1
OFFICIAL_TERMS_URL = "https://zunko.jp/con_ongen_kiyaku.html"
ACCEPTANCE_FILENAME = "voiceger-terms-acceptance.json"
ACCEPTANCE_COMMAND = "voiceger-editor --accept-voiceger-terms"

_RECORD_FIELDS = {
    "accepted_explicitly",
    "notice_version",
    "terms_url",
}

NOTICE_LANGUAGE_JAPANESE = "ja"
NOTICE_LANGUAGE_ENGLISH = "en"

_NOTICES = {
    NOTICE_LANGUAGE_JAPANESE: f"""必ずお読みください

・このツールで生成した音声には「Voicegerずんだもん音源利用規約」が適用されます
・生成音声の利用にはクレジット表記が必要です

公式利用規約:
{OFFICIAL_TERMS_URL}""",
    NOTICE_LANGUAGE_ENGLISH: f"""Please read before continuing

• Audio generated with this tool is subject to the Voiceger:Zundamon Voice Source Terms of Use
• Credit is required when using generated audio

Official Terms of Use:
{OFFICIAL_TERMS_URL}""",
}


class VoicegerTermsAcceptanceError(RuntimeError):
    """Raised when current explicit terms acceptance is required but absent."""


class TermsAcceptanceRecordError(ValueError):
    """Raised when the persisted terms acceptance record is not current and valid."""


@dataclass(frozen=True)
class TermsAcceptanceRecord:
    accepted_explicitly: bool
    notice_version: int
    terms_url: str


@dataclass(frozen=True)
class TermsAcceptanceStatus:
    accepted: bool
    path: Path
    notice_version: int
    terms_url: str
    detail: str


def default_acceptance_path() -> Path:
    """Return the dedicated acceptance file beside the default settings file."""

    return default_config_path().with_name(ACCEPTANCE_FILENAME)


def preferred_notice_language(
    environ: Mapping[str, str] | None = None,
) -> str:
    """Select the initial notice language from the process locale."""

    values = os.environ if environ is None else environ
    locale_value = ""
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = values.get(name)
        if value and value.strip():
            locale_value = value.strip()
            break

    normalized = locale_value.lower().replace("-", "_")
    if normalized == "ja" or normalized.startswith("ja_"):
        return NOTICE_LANGUAGE_JAPANESE
    return NOTICE_LANGUAGE_ENGLISH


def format_current_notice(language: str | None = None) -> str:
    """Return the localized notice shared by CLI and interactive startup paths."""

    selected = preferred_notice_language() if language is None else language
    if selected not in _NOTICES:
        raise ValueError(f"unsupported notice language: {selected!r}")
    return _NOTICES[selected]


def _resolve_acceptance_path(
    path: str | os.PathLike[str] | None,
) -> Path:
    try:
        return default_acceptance_path() if path is None else Path(path).expanduser()
    except (TypeError, RuntimeError, ValueError) as exc:
        raise TermsAcceptanceRecordError(
            f"invalid terms acceptance path: {exc}"
        ) from exc


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in pairs:
        if key in values:
            raise TermsAcceptanceRecordError(
                f"duplicate field {key!r} in terms acceptance record"
            )
        values[key] = value
    return values


def load_acceptance_record(
    path: str | os.PathLike[str] | None = None,
) -> TermsAcceptanceRecord | None:
    """Load and strictly validate a current acceptance record; return None if absent."""

    resolved_path = _resolve_acceptance_path(path)
    try:
        contents = resolved_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as exc:
        raise TermsAcceptanceRecordError(
            f"cannot read terms acceptance file {resolved_path}: {exc}"
        ) from exc

    try:
        values = json.loads(contents, object_pairs_hook=_reject_duplicate_keys)
    except TermsAcceptanceRecordError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise TermsAcceptanceRecordError(
            f"terms acceptance file {resolved_path} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(values, dict):
        raise TermsAcceptanceRecordError(
            "terms acceptance record must be a JSON object"
        )

    missing_fields = _RECORD_FIELDS - values.keys()
    unknown_fields = values.keys() - _RECORD_FIELDS
    if missing_fields:
        raise TermsAcceptanceRecordError(
            "terms acceptance record is missing fields: "
            + ", ".join(sorted(missing_fields))
        )
    if unknown_fields:
        raise TermsAcceptanceRecordError(
            "terms acceptance record has unknown fields: "
            + ", ".join(sorted(unknown_fields))
        )

    if values["accepted_explicitly"] is not True:
        raise TermsAcceptanceRecordError(
            "accepted_explicitly must be the literal true value"
        )

    notice_version = values["notice_version"]
    if isinstance(notice_version, bool) or not isinstance(notice_version, int):
        raise TermsAcceptanceRecordError("notice_version must be an integer")
    if notice_version != CURRENT_NOTICE_VERSION:
        raise TermsAcceptanceRecordError(
            f"notice_version {notice_version} is not current; "
            f"current notice version is {CURRENT_NOTICE_VERSION}"
        )

    terms_url = values["terms_url"]
    if not isinstance(terms_url, str):
        raise TermsAcceptanceRecordError("terms_url must be a string")
    if terms_url != OFFICIAL_TERMS_URL:
        raise TermsAcceptanceRecordError(
            "terms_url does not match the current official terms URL"
        )

    return TermsAcceptanceRecord(
        accepted_explicitly=True,
        notice_version=notice_version,
        terms_url=terms_url,
    )


def current_acceptance_status(
    path: str | os.PathLike[str] | None = None,
) -> TermsAcceptanceStatus:
    """Return an inspectable status, treating every invalid state as not accepted."""

    resolved_path = _resolve_acceptance_path(path)
    try:
        record = load_acceptance_record(resolved_path)
    except TermsAcceptanceRecordError as exc:
        return TermsAcceptanceStatus(
            accepted=False,
            path=resolved_path,
            notice_version=CURRENT_NOTICE_VERSION,
            terms_url=OFFICIAL_TERMS_URL,
            detail=str(exc),
        )

    if record is None:
        detail = "No acceptance record exists."
        accepted = False
    else:
        detail = "The current notice version has been explicitly accepted."
        accepted = True

    return TermsAcceptanceStatus(
        accepted=accepted,
        path=resolved_path,
        notice_version=CURRENT_NOTICE_VERSION,
        terms_url=OFFICIAL_TERMS_URL,
        detail=detail,
    )


def record_explicit_acceptance(
    path: str | os.PathLike[str] | None = None,
) -> TermsAcceptanceRecord:
    """Persist the current record after a caller has obtained explicit consent."""

    resolved_path = _resolve_acceptance_path(path)
    values = {
        "accepted_explicitly": True,
        "notice_version": CURRENT_NOTICE_VERSION,
        "terms_url": OFFICIAL_TERMS_URL,
    }
    temporary_path: Path | None = None
    try:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=resolved_path.parent,
            prefix=f".{resolved_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(values, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, resolved_path)
    except OSError as exc:
        raise OSError(
            f"cannot write terms acceptance file {resolved_path}: {exc}"
        ) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    return TermsAcceptanceRecord(
        accepted_explicitly=True,
        notice_version=CURRENT_NOTICE_VERSION,
        terms_url=OFFICIAL_TERMS_URL,
    )


def require_current_acceptance(
    path: str | os.PathLike[str] | None = None,
) -> None:
    """Raise an actionable error unless the persisted record is current and valid."""

    status = current_acceptance_status(path)
    if status.accepted:
        return
    raise VoicegerTermsAcceptanceError(
        "Voiceger:Zundamon terms acceptance is required before Voiceger can be "
        "used. Open and read the official terms at "
        f"{OFFICIAL_TERMS_URL}, then run {ACCEPTANCE_COMMAND}. "
        f"Acceptance status: {status.detail}"
    )


def format_acceptance_status(
    status: TermsAcceptanceStatus | None = None,
    *,
    path: str | os.PathLike[str] | None = None,
) -> str:
    """Format current acceptance state for CLI inspection."""

    status = status or current_acceptance_status(path)
    state = "current and accepted" if status.accepted else "not accepted"
    return "\n".join(
        (
            f"Voiceger:Zundamon terms acceptance: {state}",
            f"Current notice version: {status.notice_version}",
            f"Official terms: {status.terms_url}",
            f"Acceptance file: {status.path}",
            f"Status: {status.detail}",
        )
    )
