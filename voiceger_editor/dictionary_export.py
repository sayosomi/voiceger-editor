"""Frontend-neutral user dictionary export and collision-safe naming."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import errno
import hashlib
import json
import os
import stat
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from .japanese_pitch_metadata import serialize_pitch_metadata

from .user_dictionary import (
    UserDictionaryCore,
    serialize_english_dictionary,
    serialize_japanese_dictionary,
)


@dataclass(frozen=True)
class DictionaryExportResult:
    """Paths created by one dictionary export operation."""

    paths: tuple[Path, ...]
    lossy_pitch_event_uuids: tuple[str, ...] = ()


def _timestamp_prefix(timestamp: datetime | None) -> str:
    return (timestamp or datetime.now()).strftime("%Y%m%d%H%M")


def _remove_owned_paths(paths: Iterable[Path]) -> None:
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _stage_is_original(path: Path, expected: os.stat_result) -> bool:
    """Only touch the directory name if it still denotes our staging inode."""
    try:
        current = path.lstat()
    except FileNotFoundError:
        return False
    return (
        stat.S_ISDIR(current.st_mode)
        and (current.st_dev, current.st_ino) == (expected.st_dev, expected.st_ino)
    )


@contextmanager
def _pinned_staging(
    output_dir: Path, filenames: tuple[str, ...],
) -> Iterator[tuple[Path, int | None]]:
    """Clean only our known files; never recurse through a replaced dir name."""
    directory = Path(tempfile.mkdtemp(
        prefix=".voiceger-dictionary-", dir=output_dir,
    ))
    directory_fd = None
    original = directory.lstat()
    try:
        if os.name == "posix":
            directory_fd = os.open(
                directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            original = os.fstat(directory_fd)
        yield directory, directory_fd
    finally:
        try:
            if directory_fd is not None:
                # A rename of the staging directory cannot retarget these
                # unlink calls to another directory in Output.
                for name in filenames:
                    try:
                        os.unlink(name, dir_fd=directory_fd)
                    except FileNotFoundError:
                        pass
            elif _stage_is_original(directory, original):
                # Windows has no POSIX dirfd operations: fail closed if the
                # directory name no longer refers to the staging directory.
                for name in filenames:
                    (directory / name).unlink(missing_ok=True)

            if _stage_is_original(directory, original):
                try:
                    directory.rmdir()
                except OSError as error:
                    # Unexpected entries are not ours to remove. A concurrent
                    # writer may also have moved or replaced this path.
                    if error.errno not in (
                        errno.ENOENT, errno.ENOTEMPTY, errno.EEXIST, errno.ENOTDIR,
                    ):
                        raise
        finally:
            if directory_fd is not None:
                os.close(directory_fd)


def _export_payloads(
    *,
    output_dir: Path,
    timestamp: datetime | None,
    payloads: tuple[tuple[str, bytes], ...],
) -> DictionaryExportResult:
    """Publish complete JSON using private, pinned staging and exclusive links."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # A writer allowed to modify Output must not be able to replace source
    # entries in this mode-0700 directory. Keep its fd and source fds open
    # while publishing; a rename of the directory pathname cannot retarget it.
    stage_names = tuple(f"{index}.tmp" for index in range(len(payloads)))
    with _pinned_staging(output_dir, stage_names) as (staging_dir, stage_fd):
        with ExitStack() as opened:
            staged = []
            for index, (_stem, payload) in enumerate(payloads):
                source = Path(staging_dir) / f"{index}.tmp"
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if stage_fd is not None:
                    fd = os.open(
                        source.name, flags | getattr(os, "O_NOFOLLOW", 0),
                        0o600, dir_fd=stage_fd,
                    )
                else:
                    fd = os.open(source, flags, 0o600)
                handle = opened.enter_context(os.fdopen(fd, "wb"))
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                staged.append((source, handle, os.fstat(handle.fileno())))

            if stage_fd is None:
                # Preserve Windows hard-link compatibility with closed handles.
                for _source, handle, _info in staged:
                    handle.close()

            prefix = _timestamp_prefix(timestamp)
            collision_number = 1
            while True:
                suffix = "" if collision_number == 1 else f"-{collision_number}"
                paths = tuple(
                    output_dir / f"{prefix}_{stem}{suffix}.json"
                    for stem, _payload in payloads
                )
                published: list[Path] = []
                try:
                    for (source, _handle, source_info), destination in zip(staged, paths):
                        if stage_fd is not None:
                            # linkat() with AT_SYMLINK_FOLLOW disabled. Even a
                            # forcibly replaced source symlink is not followed.
                            os.link(
                                source.name, destination, src_dir_fd=stage_fd,
                                follow_symlinks=False,
                            )
                        else:
                            os.link(source, destination)
                        published.append(destination)
                        linked = destination.lstat()
                        if (
                            not stat.S_ISREG(linked.st_mode)
                            or (linked.st_dev, linked.st_ino)
                            != (source_info.st_dev, source_info.st_ino)
                        ):
                            raise OSError("Dictionary staging source changed")
                except FileExistsError:
                    _remove_owned_paths(published)
                    collision_number += 1
                    continue
                except BaseException:
                    _remove_owned_paths(published)
                    raise
                return DictionaryExportResult(paths=paths)


def export_voiceger_editor_dictionaries(
    core: UserDictionaryCore,
    output_dir: Path,
    *,
    timestamp: datetime | None = None,
) -> DictionaryExportResult:
    """Atomically publish one versioned, checksummed native ZIP backup."""

    if hasattr(core, "native_dictionary_backup_snapshot"):
        words, english_words, events = core.native_dictionary_backup_snapshot()
    else:
        # Support duck-typed dictionary cores used by client integrations.
        words = core.list_japanese_entries()
        english_words = core.list_english_entries()
        events = getattr(core, "list_japanese_pitch_events", lambda: {})()
    japanese = serialize_japanese_dictionary(words)
    english = serialize_english_dictionary(english_words)
    members = {
        "user_dict.json": japanese,
        "english_user_dict.json": english,
    }
    if events:
        members["user_dict_pitch_events.json"] = serialize_pitch_metadata(
            words, events, japanese
        )
    manifest = {
        "version": 1,
        "members": {
            name: hashlib.sha256(data).hexdigest()
            for name, data in members.items()
        },
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Keep the ZIP source inside a private directory, pinned by a directory
    # descriptor on POSIX. A concurrent Output writer cannot replace it.
    with _pinned_staging(output_dir, ("backup.tmp",)) as (staging_dir, stage_fd):
        with ExitStack() as opened:
            source = Path(staging_dir) / "backup.tmp"
            flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
            if stage_fd is not None:
                fd = os.open(
                    source.name, flags | getattr(os, "O_NOFOLLOW", 0),
                    0o600, dir_fd=stage_fd,
                )
            else:
                fd = os.open(source, flags, 0o600)
            temporary = opened.enter_context(os.fdopen(fd, "w+b"))
            with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", manifest_bytes)
                for name, data in members.items():
                    archive.writestr(name, data)
            temporary.flush()
            os.fsync(temporary.fileno())
            source_info = os.fstat(temporary.fileno())
            if stage_fd is None:
                # Windows cannot publish a file with this writable handle open.
                temporary.close()

            prefix = _timestamp_prefix(timestamp)
            collision = 1
            while True:
                suffix = "" if collision == 1 else f"-{collision}"
                destination = (
                    output_dir / f"{prefix}_voiceger_editor_dictionary{suffix}.zip"
                )
                try:
                    # Exclusive destination. POSIX must never follow a
                    # substituted staging source symlink during publication.
                    if stage_fd is not None:
                        os.link(
                            source.name, destination, src_dir_fd=stage_fd,
                            follow_symlinks=False,
                        )
                    else:
                        os.link(source, destination)
                except FileExistsError:
                    collision += 1
                    continue

                try:
                    linked = destination.lstat()
                    if (
                        not stat.S_ISREG(linked.st_mode)
                        or (linked.st_dev, linked.st_ino)
                        != (source_info.st_dev, source_info.st_ino)
                    ):
                        raise OSError("Dictionary ZIP staging source changed")
                except BaseException:
                    destination.unlink(missing_ok=True)
                    raise
                return DictionaryExportResult(paths=(destination,))


def export_voicevox_dictionary(
    core: UserDictionaryCore,
    output_dir: Path,
    *,
    timestamp: datetime | None = None,
) -> DictionaryExportResult:
    """Export the Japanese dictionary in VOICEVOX-compatible form."""

    japanese = serialize_japanese_dictionary(core.list_japanese_entries())
    result = _export_payloads(
        output_dir=output_dir,
        timestamp=timestamp,
        payloads=(("voicevox_user_dict", japanese),),
    )
    events = getattr(core, "list_japanese_pitch_events", lambda: {})()
    return DictionaryExportResult(
        paths=result.paths,
        lossy_pitch_event_uuids=tuple(events),
    )
