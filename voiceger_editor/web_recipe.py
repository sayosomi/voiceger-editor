"""Mac Output-only Batch recipe transactions for the authenticated Web UI.

No browser-supplied path is accepted. Review tokens bind the file contents and
Batch revision, and a staged replacement never alters live Takes before commit.
"""

from __future__ import annotations

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


def _secure_bytes(root: Path, filename: str, *, optional: bool = False) -> bytes | None:
    """Read one regular, non-symlink file with identity checks, never paths from UI."""
    target = root / _filename(filename)
    try:
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            raise WebRecipeValidation("recipe_io")
        before = target.lstat()
    except FileNotFoundError:
        if optional:
            return None
        raise WebRecipeValidation("recipe_changed") from None
    except OSError:
        raise WebRecipeValidation("recipe_io") from None
    if not stat.S_ISREG(before.st_mode) or target.is_symlink():
        raise WebRecipeValidation("recipe_io")
    try:
        # O_NOFOLLOW prevents a symlink swap between lstat and open on macOS.
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(str(target), flags)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or (
                opened.st_dev, opened.st_ino
            ) != (before.st_dev, before.st_ino):
                raise WebRecipeValidation("recipe_changed")
            data = handle.read(_MAX_RECIPE_BYTES + 1)
            after = os.fstat(handle.fileno())
        latest = target.lstat()
    except FileNotFoundError:
        raise WebRecipeValidation("recipe_changed") from None
    except OSError:
        raise WebRecipeValidation("recipe_io") from None
    if len(data) > _MAX_RECIPE_BYTES:
        raise WebRecipeValidation("invalid_recipe")
    if (
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        or (latest.st_dev, latest.st_ino, latest.st_size, latest.st_mtime_ns)
        != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        or not stat.S_ISREG(latest.st_mode)
    ):
        raise WebRecipeValidation("recipe_changed")
    return data


def _fingerprint(root: Path, filename: str) -> str | None:
    contents = _secure_bytes(root, filename, optional=True)
    return None if contents is None else hashlib.sha256(contents).hexdigest()


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
            try:
                if not root.exists():
                    return {"files": [], "scope": "Mac Output folder"}
                if root.is_symlink() or not root.is_dir():
                    raise WebRecipeValidation("recipe_io")
                with os.scandir(root) as entries:
                    files = sorted(
                        entry.name for entry in entries
                        if _eligible_entry(entry)
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
            digest = _fingerprint(self._recipe_root(), name)
            review = _RecipeReview(
                secrets.token_urlsafe(24), "save", name, revision, digest,
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
            root = self._recipe_root()
            if _fingerprint(root, review.filename) != review.fingerprint:
                self._discard_review(session)
                raise WebRecipeValidation("recipe_changed")
            try:
                # All serialization and core atomic writing happen before publication.
                root.mkdir(parents=True, exist_ok=True)
                if root.is_symlink() or not root.is_dir():
                    raise WebRecipeValidation("recipe_io")
                fd, temporary_name = tempfile.mkstemp(prefix=".voiceger-save-", suffix=".tmp", dir=root)
                os.close(fd)
                temporary = Path(temporary_name)
                try:
                    write_batch_recipe(temporary, session.batch)
                    if _fingerprint(root, review.filename) != review.fingerprint:
                        raise WebRecipeValidation("recipe_changed")
                    target = root / review.filename
                    if review.fingerprint is None:
                        # A hard link is an atomic create-if-absent (never overwrites).
                        os.link(temporary, target)
                    else:
                        os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
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
            payload = _secure_bytes(root, name)
            assert payload is not None
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
                        runtime_settings=self._recipe_settings(),
                    )
                if len(replacement) > 200:
                    for item in replacement.items:
                        _close_item(item)
                    raise WebRecipeValidation("invalid_recipe")
            except WebRecipeValidation:
                raise
            except (BatchRecipeError, OSError, ValueError, TypeError):
                raise WebRecipeValidation("invalid_recipe") from None
            except Exception:
                raise WebRecipeValidation("recipe_io") from None
            review = _RecipeReview(
                secrets.token_urlsafe(24), "read", name, revision,
                hashlib.sha256(payload).hexdigest(), replacement,
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
                actual = _fingerprint(self._recipe_root(), review.filename)
                if actual != review.fingerprint:
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


def _eligible_entry(entry: os.DirEntry) -> bool:
    try:
        _filename(entry.name)
        return not entry.is_symlink() and entry.is_file(follow_symlinks=False)
    except (WebRecipeValidation, OSError):
        return False
