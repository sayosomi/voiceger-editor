"""Semantic Status values shared across TUI subsystems."""

from __future__ import annotations

from enum import Enum


class StatusKind(str, Enum):
    """Presentation severity for one TUI Status message."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Status(str):
    """A message whose severity is semantic rather than encoded in its text."""

    kind: StatusKind

    def __new__(cls, kind: StatusKind, message: str) -> "Status":
        value = str.__new__(cls, message)
        value.kind = kind
        return value

    def __copy__(self) -> "Status":
        return self

    def __deepcopy__(self, _memo: dict[int, object]) -> "Status":
        return self

    def __reduce_ex__(self, _protocol: int):
        return type(self), (self.kind, str(self))


def info_status(message: str) -> Status:
    return Status(StatusKind.INFO, message)


def warning_status(message: str) -> Status:
    return Status(StatusKind.WARNING, message)


def error_status(message: str) -> Status:
    return Status(StatusKind.ERROR, message)


EMPTY_STATUS = info_status("")


def format_status(status: Status) -> str:
    """Format one semantic Status for terminal presentation."""

    if not status:
        return ""
    prefix = {
        StatusKind.INFO: "Status",
        StatusKind.WARNING: "Warning",
        StatusKind.ERROR: "Error",
    }[status.kind]
    return f"{prefix}: {status}"
