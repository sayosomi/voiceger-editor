"""Mac Output-only Batch recipe transactions for the authenticated Web UI.

No browser-supplied path is accepted. Review tokens bind the file contents and
Batch revision, and a staged replacement never alters live Takes before commit.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import secrets
import stat
import tempfile
from typing import Any

from .batch_recipe import (
    BatchRecipeError, RECOMMENDED_SUFFIX, read_batch_recipe,
    serialize_batch_recipe, write_batch_recipe,
)
from .settings import Settings, load_settings


_MAX_RECIPE_BYTES = 16 * 1024 * 1024
_DEFAULT_FILENAME = "batch" + RECOMMENDED_SUFFIX


class WebRecipeValidation(ValueError):
    """A safe, allowlisted reason for a recipe transaction rejection."""

    CODES = frozenset({
        "invalid_filename", "missing_preparation", "invalid_recipe",
        "recipe_changed", "review_expired", "recipe_io",
    })

    def __init__(self, code: str, *, item_index: int | None = None) -> None:
        if code not in self.CODES:
            raise ValueError("Unknown recipe error code")
        super().__init__(code)
        self.code = code
        self.item_index = item_index


@dataclass
class _RecipeReview:
    token: str
    kind: str
    filename: str
    revision: int
    fingerprint: str | None
    replacement: Any = None
    directory_identity: tuple[int, int] | None = None

    def dispose(self) -> None:
        batch = self.replacement
        self.replacement = None
        if batch is not None:
            for item in batch.items:
                _close_item(item)


def _close_item(item: Any) -> None:
    try:
        closer = getattr(item.session, "close", None)
        if callable(closer):
            closer()
        else:
            item.session.discard_takes()
    except Exception:
        # Cleanup must not roll back an already-committed swap.
        pass


def _filename(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value or len(value) > 180
        or value.startswith(".") or ".." in value
        or "/" in value or "\\" in value or "\x00" in value
        or ":" in value or not value.endswith(RECOMMENDED_SUFFIX)
        or value == RECOMMENDED_SUFFIX
        or Path(value).is_absolute()
    ):
        raise WebRecipeValidation("invalid_filename")
    return value


@contextmanager
def _open_root(root: Path, *, create: bool = False):
    """Pin all filesystem operations to an opened, non-symlink Output directory."""
    try:
        if create:
            root.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError:
        raise WebRecipeValidation("recipe_io") from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise WebRecipeValidation("recipe_io")
        yield descriptor, (info.st_dev, info.st_ino)
    finally:
        os.close(descriptor)


def _secure_bytes(
    directory: int, filename: str, *, optional: bool = False,
) -> tuple[bytes, tuple] | None:
    """Open only regular files relative to the pinned Output fd."""
    name = _filename(filename)
    try:
        before = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        if optional:
            return None
        raise WebRecipeValidation("recipe_changed") from None
    except OSError:
        raise WebRecipeValidation("recipe_io") from None
    if not stat.S_ISREG(before.st_mode):
        raise WebRecipeValidation("recipe_io")
    try:
        descriptor = os.open(
            name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0), dir_fd=directory,
        )
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or (
                opened.st_dev, opened.st_ino
            ) != (before.st_dev, before.st_ino):
                raise WebRecipeValidation("recipe_changed")
            data = handle.read(_MAX_RECIPE_BYTES + 1)
            after = os.fstat(handle.fileno())
        latest = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        raise WebRecipeValidation("recipe_changed") from None
    except OSError:
        raise WebRecipeValidation("recipe_io") from None
    if len(data) > _MAX_RECIPE_BYTES:
        raise WebRecipeValidation("invalid_recipe")
    def identity(info):
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
    if (
        identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or identity(after) != identity(latest)
        or not stat.S_ISREG(latest.st_mode)
    ):
        raise WebRecipeValidation("recipe_changed")
    return data, (hashlib.sha256(data).hexdigest(), *identity(latest))


def _fingerprint(directory: int, filename: str) -> tuple | None:
    snapshot = _secure_bytes(directory, filename, optional=True)
    return None if snapshot is None else snapshot[1]


def _publish_checked(directory: int, filename: str, temporary: str, expected: tuple | None):
    """Publish without ever replacing an unverified destination.

    For overwrites, move the previous file to a private sibling, validate the
    moved inode, then use exclusive hard-link creation. Other writers may race
    to recreate the name, but we never overwrite their file. On conflicts,
    restore the original name when vacant; otherwise retain the backup.
    """
    if _fingerprint(directory, filename) != expected:
        raise WebRecipeValidation("recipe_changed")
    if expected is None:
        os.link(temporary, filename, src_dir_fd=directory,
                dst_dir_fd=directory, follow_symlinks=False)
        return
    backup = ".voiceger-backup-" + secrets.token_hex(16) + ".tmp"
    os.rename(filename, backup, src_dir_fd=directory, dst_dir_fd=directory)
    published = False
    try:
        if _fingerprint(directory, backup) != expected:
            raise WebRecipeValidation("recipe_changed")
        os.link(temporary, filename, src_dir_fd=directory,
                dst_dir_fd=directory, follow_symlinks=False)
        published = True
    finally:
        if not published:
            try:
                os.link(backup, filename, src_dir_fd=directory,
                        dst_dir_fd=directory, follow_symlinks=False)
            except FileExistsError:
                # Preserve both the independently created target and our backup.
                pass
            else:
                os.unlink(backup, dir_fd=directory)
        else:
            os.unlink(backup, dir_fd=directory)


def _stage_recipe_file(directory: int, batch) -> str:
    """Reuse the core writer, then stage its exact bytes in the pinned directory."""
    with tempfile.TemporaryDirectory(prefix="voiceger-recipe-write-") as folder:
        source = Path(folder) / _DEFAULT_FILENAME
        write_batch_recipe(source, batch)
        payload = source.read_bytes()
    name = ".voiceger-save-" + secrets.token_hex(16) + ".tmp"
    descriptor = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600, dir_fd=directory,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return name


class WebRecipeMixin:
    """Recipe operations under the session registry's existing RLock."""

    def _recipe_settings(self) -> Settings:
        if self._batch_settings is None:
            self._batch_settings = load_settings()
        return self._batch_settings

    def _recipe_root(self) -> Path:
        # Resolve once per service lifetime to prevent config retargeting mid-session.
        if getattr(self, "_web_recipe_root", None) is None:
            self._web_recipe_root = self._recipe_settings().output_dir.resolve()
        return self._web_recipe_root

    def _recipe_guard(self, identifier: str, revision: int):
        from .web_sessions import WebSessionConflict

        session = self._session(identifier)
        if revision != session.revision:
            raise WebSessionConflict("Stale Batch revision", code="revision_conflict")
        if self._active is not None:
            raise WebSessionConflict("Web worker is active", code="worker_busy")
        return session

    @staticmethod
    def _discard_review(session) -> None:
        review = session.pending_recipe
        session.pending_recipe = None
        if review is not None:
            review.dispose()

    def list_recipes(self, identifier: str) -> dict:
        with self._lock:
            self._session(identifier)
            root = self._recipe_root()
            if not root.exists() and not root.is_symlink():
                return {"files": [], "scope": "Mac Output folder"}
            with _open_root(root) as (directory, _identity):
                try:
                    files = sorted(
                        name for name in os.listdir(directory)
                        if _eligible_name(directory, name)
                    )
                except OSError:
                    raise WebRecipeValidation("recipe_io") from None
            return {"files": files, "scope": "Mac Output folder"}

    def review_recipe_save(self, identifier: str, revision: int, filename: str) -> dict:
        with self._lock:
            session = self._recipe_guard(identifier, revision)
            name = _filename(filename)
            # Fail before touching the filesystem if even an excluded item is unprepared.
            for index, item in enumerate(session.batch.items, 1):
                if not item.session.is_prepared:
                    raise WebRecipeValidation("missing_preparation", item_index=index)
            try:
                serialize_batch_recipe(session.batch)
            except (BatchRecipeError, TypeError, ValueError):
                raise WebRecipeValidation("invalid_recipe") from None
            self._discard_review(session)
            with _open_root(self._recipe_root(), create=True) as (directory, identity):
                digest = _fingerprint(directory, name)
            review = _RecipeReview(
                secrets.token_urlsafe(24), "save", name, revision, digest,
                directory_identity=identity,
            )
            session.pending_recipe = review
            return {
                "token": review.token, "filename": name,
                "exists": digest is not None, "scope": "Mac Output folder",
            }

    def commit_recipe_save(
        self, identifier: str, revision: int, token: str, confirmed_overwrite: bool,
    ) -> dict:
        with self._lock:
            session = self._recipe_guard(identifier, revision)
            review = self._require_review(session, "save", revision, token)
            if review.fingerprint is not None and confirmed_overwrite is not True:
                raise WebRecipeValidation("review_expired")
            try:
                with _open_root(self._recipe_root()) as (directory, identity):
                    if identity != review.directory_identity:
                        raise WebRecipeValidation("recipe_changed")
                    # Core serialization completes before the live file is touched.
                    temporary = _stage_recipe_file(directory, session.batch)
                    try:
                        _publish_checked(
                            directory, review.filename, temporary, review.fingerprint,
                        )
                    finally:
                        os.unlink(temporary, dir_fd=directory)
            except FileExistsError:
                self._discard_review(session)
                raise WebRecipeValidation("recipe_changed") from None
            except WebRecipeValidation:
                self._discard_review(session)
                raise
            except (BatchRecipeError, OSError, ValueError):
                self._discard_review(session)
                raise WebRecipeValidation("recipe_io") from None
            self._discard_review(session)
            return {"filename": review.filename, "saved": True}

    def review_recipe_read(self, identifier: str, revision: int, filename: str) -> dict:
        with self._lock:
            session = self._recipe_guard(identifier, revision)
            name = _filename(filename)
            root = self._recipe_root()
            with _open_root(root) as (directory, identity):
                snapshot = _secure_bytes(directory, name)
                assert snapshot is not None
                payload, fingerprint = snapshot
            self._discard_review(session)
            try:
                if self._batch_adapter is None:
                    from .voiceger_adapter import VoicegerAdapter
                    self._batch_adapter = VoicegerAdapter()
                # Reuse the unmodified canonical reader on an isolated, exact-byte copy.
                with tempfile.TemporaryDirectory(prefix="voiceger-recipe-") as folder:
                    source = Path(folder) / _DEFAULT_FILENAME
                    source.write_bytes(payload)
                    replacement = read_batch_recipe(
                        source, adapter=self._batch_adapter,
                        runtime_settings=self._recipe_settings(), max_items=200,
                    )
            except WebRecipeValidation:
                raise
            except (BatchRecipeError, OSError, ValueError, TypeError):
                raise WebRecipeValidation("invalid_recipe") from None
            except Exception:
                raise WebRecipeValidation("recipe_io") from None
            review = _RecipeReview(
                secrets.token_urlsafe(24), "read", name, revision,
                fingerprint, replacement, identity,
            )
            session.pending_recipe = review
            return {
                "token": review.token, "filename": name,
                "item_count": len(replacement), "replace_required": bool(len(session.batch)),
            }

    def commit_recipe_read(
        self, identifier: str, revision: int, token: str, confirmed_replace: bool,
    ) -> dict:
        with self._lock:
            session = self._recipe_guard(identifier, revision)
            review = self._require_review(session, "read", revision, token)
            if len(session.batch) and confirmed_replace is not True:
                raise WebRecipeValidation("review_expired")
            try:
                with _open_root(self._recipe_root()) as (directory, identity):
                    if identity != review.directory_identity or (
                        _fingerprint(directory, review.filename) != review.fingerprint
                    ):
                        raise WebRecipeValidation("recipe_changed")
            except WebRecipeValidation:
                self._discard_review(session)
                raise
            incoming = review.replacement
            if incoming is None:
                self._discard_review(session)
                raise WebRecipeValidation("review_expired")
            old = session.batch
            review.replacement = None
            session.pending_recipe = None
            session.batch = incoming
            session.revision += 1
            session.preview_audio = None
            session.english_groupings.clear()
            for item in old.items:
                _close_item(item)
            return self._batch_snapshot(session)

    def cancel_recipe_review(self, identifier: str, revision: int) -> dict:
        with self._lock:
            session = self._recipe_guard(identifier, revision)
            self._discard_review(session)
            return {"cancelled": True}

    @staticmethod
    def _require_review(session, kind: str, revision: int, token: str) -> _RecipeReview:
        review = session.pending_recipe
        if not isinstance(token, str) or not token or (
            review is None or review.kind != kind
            or review.revision != revision or review.token != token
        ):
            raise WebRecipeValidation("review_expired")
        return review


def _eligible_name(directory: int, name: str) -> bool:
    try:
        _filename(name)
        info = os.stat(name, dir_fd=directory, follow_symlinks=False)
        return stat.S_ISREG(info.st_mode)
    except (WebRecipeValidation, OSError):
        return False
