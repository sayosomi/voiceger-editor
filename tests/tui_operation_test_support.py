"""Small shared operation-session fakes for focused TUI operation tests."""

from pathlib import Path
import sys
from types import SimpleNamespace


def candidate(number):
    return SimpleNamespace(number=number, wav_path=Path(f"/tmp/take-{number}.wav"))


class FakeSession:
    def __init__(self, candidates=()):
        self.candidates = list(candidates)
        self.has_active_batch = bool(candidates)
        self.generated = ()
        self.generate_error = None
        self.regenerate_all_error = None
        self.regenerate_error = None
        self.accept_error = None
        self.discard_calls = 0
        self.accept_calls = []
        self.regenerate_calls = []
        self.regenerate_all_calls = 0
        self.preview_calls = []
        self.preview_error = None
        self.preview_result = {"audio": "preview", "sampling_rate": 22050}
        self.accepted = SimpleNamespace(
            wav_path=Path("/tmp/saved.wav"),
            text_path=Path("/tmp/saved.txt"),
        )

    @property
    def active_candidate_count(self):
        return len(self.candidates)

    def generate_takes(self):
        if self.generate_error is not None:
            raise self.generate_error

        def values():
            for item in self.generated:
                self.candidates.append(item)
                yield item

        return values()

    def regenerate_take(self, number):
        self.regenerate_calls.append(number)
        if self.regenerate_error is not None:
            raise self.regenerate_error
        return next(item for item in self.candidates if item.number == number)

    def regenerate_all_takes(self):
        self.regenerate_all_calls += 1
        if self.regenerate_all_error is not None:
            raise self.regenerate_all_error

        def values():
            for item in self.candidates:
                yield item

        return values()

    def preview_synthesis(self, query):
        self.preview_calls.append(query)
        print("preview stdout")
        print("preview stderr", file=sys.stderr)
        if self.preview_error is not None:
            raise self.preview_error
        return self.preview_result

    def discard_takes(self):
        self.discard_calls += 1
        self.candidates = []

    def accept_take(self, number):
        self.accept_calls.append(number)
        if self.accept_error is not None:
            raise self.accept_error
        self.candidates = [item for item in self.candidates if item.number != number]
        return self.accepted
