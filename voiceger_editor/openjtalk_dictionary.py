"""OpenJTalk dictionary conversion and process-global activation.

Japanese dictionary records live in :mod:`user_dictionary`; this module owns
their VOICEVOX-compatible OpenJTalk representation and the Voiceger merge.
"""

from __future__ import annotations

import csv
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping

from .runtime_locks import OPENJTALK_LOCK


class OpenJTalkDictionaryError(RuntimeError):
    """Raised when the merged Japanese dictionary cannot be activated."""


@dataclass(frozen=True)
class WordTypeData:
    part_of_speech: str
    part_of_speech_detail_1: str
    part_of_speech_detail_2: str
    part_of_speech_detail_3: str
    context_id: int
    cost_candidates: tuple[int, ...]
    accent_associative_rules: tuple[str, ...]


_NOUN_RULES = ("*", "C1", "C2", "C3", "C4", "C5")
WORD_TYPE_DATA: dict[str, WordTypeData] = {
    "PROPER_NOUN": WordTypeData(
        "名詞", "固有名詞", "一般", "*", 1348,
        (-988, 3488, 4768, 6048, 7328, 8609, 8734, 8859, 8984, 9110, 14176),
        _NOUN_RULES,
    ),
    "COMMON_NOUN": WordTypeData(
        "名詞", "一般", "*", "*", 1345,
        (-4445, 49, 1473, 2897, 4321, 5746, 6554, 7362, 8170, 8979, 15001),
        _NOUN_RULES,
    ),
    "VERB": WordTypeData(
        "動詞", "自立", "*", "*", 642,
        (3100, 6160, 6360, 6561, 6761, 6962, 7414, 7866, 8318, 8771, 13433),
        ("*",),
    ),
    "ADJECTIVE": WordTypeData(
        "形容詞", "自立", "*", "*", 20,
        (1527, 3266, 3561, 3857, 4153, 4449, 5149, 5849, 6549, 7250, 10001),
        ("*",),
    ),
    "SUFFIX": WordTypeData(
        "名詞", "接尾", "一般", "*", 1358,
        (4399, 5373, 6041, 6710, 7378, 8047, 9440, 10834, 12228, 13622, 15847),
        _NOUN_RULES,
    ),
}
_DATA_BY_CONTEXT_ID = {value.context_id: value for value in WORD_TYPE_DATA.values()}
_HANKAKU_TO_ZENKAKU = str.maketrans(
    {chr(code): chr(code + 0xFEE0) for code in range(0x21, 0x7F)}
)


def normalize_surface(surface: str) -> str:
    """Apply VOICEVOX's printable half-width ASCII normalization."""

    return surface.translate(_HANKAKU_TO_ZENKAKU)


def expand_word_type(word_type: str) -> dict[str, Any]:
    """Return the canonical OpenJTalk fields associated with a word type."""

    try:
        data = WORD_TYPE_DATA[str(word_type)]
    except KeyError as exc:
        raise ValueError("不明な品詞です") from exc
    return {
        "context_id": data.context_id,
        "part_of_speech": data.part_of_speech,
        "part_of_speech_detail_1": data.part_of_speech_detail_1,
        "part_of_speech_detail_2": data.part_of_speech_detail_2,
        "part_of_speech_detail_3": data.part_of_speech_detail_3,
    }


def validate_imported_pos(word: Mapping[str, Any]) -> None:
    """Reject imported POS/context/accent-rule combinations VOICEVOX rejects."""

    data = _DATA_BY_CONTEXT_ID.get(word.get("context_id"))
    fields = (
        "part_of_speech",
        "part_of_speech_detail_1",
        "part_of_speech_detail_2",
        "part_of_speech_detail_3",
    )
    if data is None or any(word.get(field) != getattr(data, field) for field in fields):
        raise ValueError("対応していない品詞です")
    if word.get("accent_associative_rule") not in data.accent_associative_rules:
        raise ValueError("対応していないアクセント結合規則です")


def priority_to_cost(context_id: int, priority: int) -> int:
    """Map VOICEVOX priority 0..10 to the POS-specific MeCab cost."""

    data = _DATA_BY_CONTEXT_ID.get(context_id)
    if data is None:
        raise ValueError("品詞IDが不正です")
    if isinstance(priority, bool) or not 0 <= priority <= 10:
        raise ValueError("優先度の値が無効です")
    return data.cost_candidates[10 - priority]


def render_word_csv(word: Any) -> str:
    """Render one canonical Japanese word as a MeCab dictionary CSV row."""

    values = (
        word.surface,
        str(word.context_id),
        str(word.context_id),
        str(priority_to_cost(word.context_id, word.priority)),
        word.part_of_speech,
        word.part_of_speech_detail_1,
        word.part_of_speech_detail_2,
        word.part_of_speech_detail_3,
        word.inflectional_type,
        word.inflectional_form,
        word.stem,
        word.yomi,
        word.pronunciation,
        f"{word.accent_type}/{word.mora_count}",
        word.accent_associative_rule,
    )
    return ",".join(values) + "\n"


def render_words_csv(words: Iterable[Any]) -> str:
    return "".join(render_word_csv(word) for word in words)


@dataclass
class CompiledDictionary:
    signature: str
    directory: tempfile.TemporaryDirectory
    path: Path

    def close(self) -> None:
        self.directory.cleanup()


@dataclass(frozen=True)
class ActiveDictionaryState:
    manager: Any
    compilation: CompiledDictionary | None
    signature: str | None


_ACTIVE_COMPILATION: CompiledDictionary | None = None
_ACTIVE_SIGNATURE: str | None = None
_ACTIVE_MANAGER: Any = None
_BASELINE_JTALK_MANAGER: Any = None


@contextmanager
def _suppress_native_output():
    """Keep native dictionary compiler progress from corrupting terminal UIs."""

    saved_fds: list[tuple[int, int]] = []
    null_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        for fd in (1, 2):
            try:
                saved_fd = os.dup(fd)
            except OSError:
                continue
            try:
                os.dup2(null_fd, fd)
            except Exception:
                os.close(saved_fd)
                raise
            saved_fds.append((fd, saved_fd))
        yield
    finally:
        for fd, saved_fd in reversed(saved_fds):
            try:
                os.dup2(saved_fd, fd)
            finally:
                os.close(saved_fd)
        os.close(null_fd)


class OpenJTalkDictionary:
    """Compile and apply Voiceger plus adapter-owned Japanese entries."""

    def __init__(
        self,
        voiceger_root: str | os.PathLike[str],
        *,
        pyopenjtalk_module: Any | None = None,
    ) -> None:
        self.voiceger_root = Path(voiceger_root).expanduser().resolve()
        self.source_csv = (
            self.voiceger_root
            / "GPT-SoVITS"
            / "GPT_SoVITS"
            / "text"
            / "ja_userdic"
            / "userdict.csv"
        )
        self.opaque_dictionary = self.source_csv.with_name("user.dict")
        self._engine = pyopenjtalk_module

    def _pyopenjtalk(self):
        if self._engine is None:
            try:
                import pyopenjtalk
            except ImportError as exc:
                raise OpenJTalkDictionaryError(
                    "pyopenjtalk is required to activate the Japanese user dictionary"
                ) from exc
            self._engine = pyopenjtalk
        return self._engine

    @staticmethod
    def _entry_data(entries: Mapping[str, Any]) -> list[tuple[str, Any]]:
        return sorted(entries.items(), key=lambda item: item[0])

    def _signature(self, entries: Mapping[str, Any]) -> tuple[str, bool, bool]:
        has_source = self.source_csv.is_file()
        has_opaque = self.opaque_dictionary.is_file()
        source_marker = "missing"
        if has_source:
            stat = self.source_csv.stat()
            source_marker = f"{self.source_csv}:{stat.st_size}:{stat.st_mtime_ns}"
        encoded = json.dumps(
            [
                (word_uuid, word.model_dump(mode="json"))
                for word_uuid, word in self._entry_data(entries)
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        opaque_marker = ""
        if has_opaque and not has_source:
            stat = self.opaque_dictionary.stat()
            opaque_marker = f"opaque:{self.opaque_dictionary}:{stat.st_size}:{stat.st_mtime_ns}"
        return f"{source_marker}|{opaque_marker}|{digest}", has_source, has_opaque

    def _merged_csv(self, entries: Mapping[str, Any]) -> str:
        adapter_words = [word for _word_uuid, word in self._entry_data(entries)]
        adapter_surfaces = {normalize_surface(word.surface) for word in adapter_words}
        source = ""
        if self.source_csv.is_file():
            try:
                source = self.source_csv.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError) as exc:
                raise OpenJTalkDictionaryError(
                    f"could not read Voiceger dictionary CSV: {self.source_csv}"
                ) from exc

        retained_lines: list[str] = []
        for raw_line in source.splitlines(keepends=True):
            try:
                row = next(csv.reader([raw_line]))
            except (csv.Error, StopIteration) as exc:
                raise OpenJTalkDictionaryError(
                    f"Voiceger dictionary CSV has an invalid row: {raw_line[:80]!r}"
                ) from exc
            if row and normalize_surface(row[0]) in adapter_surfaces:
                continue
            retained_lines.append(raw_line)

        voiceger_csv = "".join(retained_lines)
        if voiceger_csv and not voiceger_csv.endswith(("\n", "\r")):
            voiceger_csv += "\n"
        return voiceger_csv + render_words_csv(adapter_words)

    def _compile(self, entries: Mapping[str, Any], signature: str) -> CompiledDictionary:
        directory = tempfile.TemporaryDirectory(prefix="voiceger-accent-openjtalk-")
        root = Path(directory.name)
        csv_path = root / "merged-user-dictionary.csv"
        compiled_path = root / "merged-user-dictionary.dic"
        try:
            csv_path.write_text(self._merged_csv(entries), encoding="utf-8")
            # pyopenjtalk's native MeCab compiler writes progress directly to
            # process stdout/stderr, bypassing curses and Python stream
            # redirection. Suppress only that native compilation call.
            with OPENJTALK_LOCK, _suppress_native_output():
                self._pyopenjtalk().mecab_dict_index(
                    str(csv_path), str(compiled_path)
                )
            if not compiled_path.is_file():
                raise OpenJTalkDictionaryError(
                    "OpenJTalk dictionary compilation produced no dictionary file"
                )
            return CompiledDictionary(signature, directory, compiled_path)
        except OpenJTalkDictionaryError:
            directory.cleanup()
            raise
        except Exception as exc:
            directory.cleanup()
            raise OpenJTalkDictionaryError(
                "OpenJTalk dictionary compilation failed"
            ) from exc

    def snapshot(self) -> ActiveDictionaryState:
        with OPENJTALK_LOCK:
            engine = self._pyopenjtalk()
            manager = getattr(engine, "_global_jtalk", None)
            if manager is None:
                raise OpenJTalkDictionaryError(
                    "pyopenjtalk does not expose a restorable global OpenJTalk manager"
                )
            return ActiveDictionaryState(
                manager=manager,
                compilation=_ACTIVE_COMPILATION,
                signature=_ACTIVE_SIGNATURE,
            )

    def _last_known_good_state(
        self,
        fallback: ActiveDictionaryState,
    ) -> ActiveDictionaryState:
        if _ACTIVE_MANAGER is None:
            return fallback
        return ActiveDictionaryState(
            manager=_ACTIVE_MANAGER,
            compilation=_ACTIVE_COMPILATION,
            signature=_ACTIVE_SIGNATURE,
        )

    def restore(self, state: ActiveDictionaryState) -> None:
        """Restore the exact previously active pyopenjtalk manager."""

        global _ACTIVE_COMPILATION, _ACTIVE_SIGNATURE, _ACTIVE_MANAGER
        with OPENJTALK_LOCK:
            engine = self._pyopenjtalk()
            try:
                # pyopenjtalk exposes no reset-to-default API. Its manager
                # closure owns the loaded OpenJTalk instance, so restoring the
                # saved manager recovers the exact last-known-good dictionary.
                engine._global_jtalk = state.manager
            except Exception as exc:
                raise OpenJTalkDictionaryError(
                    "could not restore the previous OpenJTalk dictionary"
                ) from exc
            _ACTIVE_COMPILATION = state.compilation
            _ACTIVE_SIGNATURE = state.signature
            _ACTIVE_MANAGER = state.manager

    def _activate_compilation(
        self, compiled: CompiledDictionary
    ) -> ActiveDictionaryState:
        global _ACTIVE_COMPILATION, _ACTIVE_SIGNATURE, _ACTIVE_MANAGER
        with OPENJTALK_LOCK:
            previous = self.snapshot()
            last_good = self._last_known_good_state(previous)
            try:
                self._pyopenjtalk().update_global_jtalk_with_user_dict(
                    str(compiled.path.resolve())
                )
            except Exception as exc:
                self.restore(last_good)
                compiled.close()
                raise OpenJTalkDictionaryError(
                    "OpenJTalk dictionary application failed"
                ) from exc
            _ACTIVE_COMPILATION = compiled
            _ACTIVE_SIGNATURE = compiled.signature
            _ACTIVE_MANAGER = self._pyopenjtalk()._global_jtalk
            return previous

    def _activate_opaque(self, signature: str) -> ActiveDictionaryState:
        global _ACTIVE_COMPILATION, _ACTIVE_SIGNATURE, _ACTIVE_MANAGER
        with OPENJTALK_LOCK:
            previous = self.snapshot()
            last_good = self._last_known_good_state(previous)
            try:
                self._pyopenjtalk().update_global_jtalk_with_user_dict(
                    str(self.opaque_dictionary.resolve())
                )
            except Exception as exc:
                self.restore(last_good)
                raise OpenJTalkDictionaryError(
                    "Voiceger compiled Japanese dictionary application failed"
                ) from exc
            _ACTIVE_COMPILATION = None
            _ACTIVE_SIGNATURE = signature
            _ACTIVE_MANAGER = self._pyopenjtalk()._global_jtalk
            return previous

    def activate_entries(self, entries: Mapping[str, Any]) -> ActiveDictionaryState:
        """Compile and apply an entry set, returning the rollback state.

        The caller may keep :data:`OPENJTALK_LOCK` held through persistence,
        then call :meth:`commit` or :meth:`restore`.
        """

        global _ACTIVE_COMPILATION, _ACTIVE_SIGNATURE, _ACTIVE_MANAGER
        global _BASELINE_JTALK_MANAGER
        with OPENJTALK_LOCK:
            signature, has_source, has_opaque = self._signature(entries)
            if not has_source and has_opaque and entries:
                raise OpenJTalkDictionaryError(
                    "adapter Japanese entries cannot be applied because Voiceger "
                    "has only an opaque compiled dictionary and no mergeable CSV"
                )
            if not has_source and has_opaque and not entries:
                previous = self._activate_opaque(signature)
                if previous.compilation is not None:
                    previous.compilation.close()
                return previous

            if not has_source and not entries:
                engine = self._pyopenjtalk()
                if _BASELINE_JTALK_MANAGER is None:
                    _BASELINE_JTALK_MANAGER = engine._global_jtalk
                previous = self.snapshot()
                engine._global_jtalk = _BASELINE_JTALK_MANAGER
                _ACTIVE_COMPILATION = None
                _ACTIVE_SIGNATURE = signature
                _ACTIVE_MANAGER = _BASELINE_JTALK_MANAGER
                return previous

            compiled = self._compile(entries, signature)
            return self._activate_compilation(compiled)

    def ensure_active(
        self,
        entries: Mapping[str, Any],
        *,
        force: bool = False,
    ) -> CompiledDictionary | None:
        """Ensure this core's merged dictionary is the process-global one."""

        global _ACTIVE_COMPILATION, _ACTIVE_SIGNATURE, _ACTIVE_MANAGER
        global _BASELINE_JTALK_MANAGER
        with OPENJTALK_LOCK:
            signature, has_source, has_opaque = self._signature(entries)
            if not has_source and has_opaque and entries:
                raise OpenJTalkDictionaryError(
                    "adapter Japanese entries cannot be applied because Voiceger "
                    "has only an opaque compiled dictionary and no mergeable CSV"
                )
            if not has_source and has_opaque and not entries:
                if force or _ACTIVE_SIGNATURE != signature:
                    previous = self._activate_opaque(signature)
                    if previous.compilation is not None:
                        previous.compilation.close()
                return _ACTIVE_COMPILATION

            if not has_source and not entries:
                engine = self._pyopenjtalk()
                if _BASELINE_JTALK_MANAGER is None:
                    _BASELINE_JTALK_MANAGER = engine._global_jtalk
                if force or _ACTIVE_SIGNATURE != signature:
                    previous = self.snapshot()
                    engine._global_jtalk = _BASELINE_JTALK_MANAGER
                    _ACTIVE_COMPILATION = None
                    _ACTIVE_SIGNATURE = signature
                    _ACTIVE_MANAGER = _BASELINE_JTALK_MANAGER
                    if previous.compilation is not None:
                        previous.compilation.close()
                return None

            if _ACTIVE_SIGNATURE == signature and _ACTIVE_COMPILATION is not None:
                if force:
                    previous = self.snapshot()
                    last_good = (
                        ActiveDictionaryState(
                            manager=_ACTIVE_MANAGER,
                            compilation=_ACTIVE_COMPILATION,
                            signature=_ACTIVE_SIGNATURE,
                        )
                        if _ACTIVE_MANAGER is not None
                        else previous
                    )
                    try:
                        self._pyopenjtalk().update_global_jtalk_with_user_dict(
                            str(_ACTIVE_COMPILATION.path.resolve())
                        )
                    except Exception as exc:
                        self.restore(last_good)
                        raise OpenJTalkDictionaryError(
                            "OpenJTalk dictionary application failed"
                        ) from exc
                    _ACTIVE_MANAGER = self._pyopenjtalk()._global_jtalk
                return _ACTIVE_COMPILATION
            if _ACTIVE_SIGNATURE == signature and _ACTIVE_COMPILATION is None:
                return None

            compiled = self._compile(entries, signature)
            previous = self._activate_compilation(compiled)
            if previous.compilation is not None and previous.compilation is not compiled:
                previous.compilation.close()
            return compiled

    def commit(self, previous: ActiveDictionaryState) -> None:
        """Release the previous compiled file after persistent commit."""

        if previous.compilation is not None and previous.compilation is not _ACTIVE_COMPILATION:
            previous.compilation.close()

    def discard_current_after_restore(self, current: ActiveDictionaryState) -> None:
        """Remove a candidate compilation after a transaction rolls back."""

        if current.compilation is not None and current.compilation is not _ACTIVE_COMPILATION:
            current.compilation.close()
