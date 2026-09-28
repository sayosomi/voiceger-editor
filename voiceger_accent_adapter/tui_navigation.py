"""Navigation state, movement policy, and application action requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Union


FocusKey = Tuple[str, Optional[int]]


@dataclass(frozen=True)
class NavigationContext:
    """Immutable facts needed to derive the current selectable navigation rows."""

    has_session: bool
    pronunciation_needs_rebuild: bool
    segment_count: int
    candidate_numbers: tuple[int, ...]
    busy: bool
    has_active_batch: bool


@dataclass(frozen=True)
class ClearAdjustmentFeedback:
    pass


@dataclass(frozen=True)
class UpdateNavigationStatus:
    status: str


@dataclass(frozen=True)
class OpenSettingsEditor:
    selected_field: str
    edit: bool = False


@dataclass(frozen=True)
class OpenTextEditor:
    pass


@dataclass(frozen=True)
class EditPronunciationSegment:
    index: int


@dataclass(frozen=True)
class StartGeneration:
    pass


@dataclass(frozen=True)
class RegenerateAll:
    pass


@dataclass(frozen=True)
class RebuildPronunciation:
    pass


@dataclass(frozen=True)
class AcceptCandidate:
    number: int


@dataclass(frozen=True)
class RegenerateCandidate:
    number: int


@dataclass(frozen=True)
class PlayCandidate:
    number: int


@dataclass(frozen=True)
class OpenHelp:
    pass


@dataclass(frozen=True)
class Quit:
    pass


NavigationAction = Union[
    ClearAdjustmentFeedback,
    UpdateNavigationStatus,
    OpenSettingsEditor,
    OpenTextEditor,
    EditPronunciationSegment,
    StartGeneration,
    RegenerateAll,
    RebuildPronunciation,
    AcceptCandidate,
    RegenerateCandidate,
    PlayCandidate,
    OpenHelp,
    Quit,
]


class TuiNavigation:
    """Own focus and navigation policy without depending on application objects."""

    def __init__(self) -> None:
        self.focus_key: FocusKey = ("settings_summary", None)
        self.segment_index = 0
        self.revision = 0

    def navigation_items(self, context: NavigationContext) -> tuple[FocusKey, ...]:
        items: list[FocusKey] = [
            ("settings_summary", None),
            ("output", None),
            ("text", None),
        ]
        if context.has_session:
            if not context.pronunciation_needs_rebuild:
                items.extend(
                    ("segment", index)
                    for index in range(context.segment_count)
                )
            items.extend((("rebuild", None), ("generate", None)))
            items.extend(
                ("candidate", number) for number in context.candidate_numbers
            )
        items.extend((("settings", None), ("help", None), ("quit", None)))
        return tuple(items)

    def major_navigation_stops(
        self,
        context: NavigationContext,
    ) -> tuple[FocusKey, ...]:
        """Collapse consecutive pronunciation and candidate rows into sections."""

        stops: list[FocusKey] = []
        previous_section: str | None = None
        for key in self.navigation_items(context):
            name = key[0]
            if name in {"segment", "candidate"}:
                if name == previous_section:
                    continue
                previous_section = name
            else:
                previous_section = None
            stops.append(key)
        return tuple(stops)

    def set_focus_key(
        self,
        context: NavigationContext,
        key: FocusKey,
        *,
        moved: bool = False,
    ) -> tuple[NavigationAction, ...]:
        items = self.navigation_items(context)
        if key not in items:
            remembered_segment = ("segment", self.segment_index)
            if remembered_segment in items:
                key = remembered_segment
            elif ("rebuild", None) in items:
                key = ("rebuild", None)
            else:
                key = ("text", None)
        if key not in items:
            key = items[0]

        changed = key != self.focus_key
        self.focus_key = key
        if key[0] == "segment" and key[1] is not None:
            self.segment_index = key[1]
        if not changed:
            return ()
        if moved:
            self.revision += 1
        return (ClearAdjustmentFeedback(),)

    def move(self, context: NavigationContext, delta: int) -> tuple[NavigationAction, ...]:
        items = self.navigation_items(context)
        if not items:
            return ()
        try:
            index = items.index(self.focus_key)
        except ValueError:
            index = 0
        target = min(max(index + delta, 0), len(items) - 1)
        if target == index:
            return ()
        key = items[target]
        actions = list(self.set_focus_key(context, key, moved=True))
        actions.extend(self._candidate_playback_action(key))
        return tuple(actions)

    def move_section(
        self,
        context: NavigationContext,
        delta: int,
    ) -> tuple[NavigationAction, ...]:
        stops = self.major_navigation_stops(context)
        if not stops:
            return ()
        try:
            index = stops.index(self.focus_key)
        except ValueError:
            index = next(
                (
                    position
                    for position, key in enumerate(stops)
                    if key[0] == self.focus_key[0]
                ),
                0,
            )
        target = min(max(index + delta, 0), len(stops) - 1)
        if target == index:
            return ()
        key = stops[target]
        actions = list(self.set_focus_key(context, key, moved=True))
        actions.extend(self._candidate_playback_action(key))
        return tuple(actions)

    def focus_candidate(
        self,
        context: NavigationContext,
        number: int,
    ) -> tuple[NavigationAction, ...]:
        key = ("candidate", number)
        if key not in self.navigation_items(context):
            return (UpdateNavigationStatus(f"Take {number} has not been generated yet."),)
        actions = list(self.set_focus_key(context, key, moved=True))
        actions.extend(self._candidate_playback_action(key))
        return tuple(actions)

    def escape_candidate(
        self,
        context: NavigationContext,
    ) -> tuple[NavigationAction, ...] | None:
        if self.focus_key[0] != "candidate":
            return None
        actions = list(
            self.set_focus_key(
                context,
                ("segment", self.segment_index),
                moved=True,
            )
        )
        actions.append(
            UpdateNavigationStatus("Returned to the last pronunciation segment.")
        )
        return tuple(actions)

    def activate_focused_item(
        self,
        context: NavigationContext,
    ) -> tuple[NavigationAction, ...]:
        name, number = self.focus_key
        if name == "settings_summary":
            return (OpenSettingsEditor("style_id"),)
        if name == "output":
            return (OpenSettingsEditor("output_dir", edit=True),)
        if name == "text":
            if context.busy:
                return (
                    UpdateNavigationStatus(
                        "Wait for synthesis to finish before editing text."
                    ),
                )
            return (OpenTextEditor(),)
        if name == "segment" and number is not None:
            if context.busy:
                return (
                    UpdateNavigationStatus(
                        "Wait for synthesis to finish before editing pronunciation."
                    ),
                )
            return (EditPronunciationSegment(number),)
        if name == "generate":
            return self.activate_generate(context)
        if name == "rebuild":
            if context.busy:
                return (
                    UpdateNavigationStatus(
                        "Wait for the current synthesis operation to finish."
                    ),
                )
            return (RebuildPronunciation(),)
        if name == "candidate" and number is not None:
            if context.busy:
                return (
                    UpdateNavigationStatus(
                        "Wait for generation to finish before accepting a take."
                    ),
                )
            return (AcceptCandidate(number),)
        if name == "settings":
            return (OpenSettingsEditor("style_id"),)
        if name == "help":
            return self.open_help(context)
        if name == "quit":
            return (Quit(),)
        return ()

    def activate_generate(
        self,
        context: NavigationContext,
    ) -> tuple[NavigationAction, ...]:
        if context.busy:
            return (
                UpdateNavigationStatus(
                    "A sequential take operation is already running."
                ),
            )
        if context.has_session and context.has_active_batch:
            return (RegenerateAll(),)
        return (StartGeneration(),)

    def activate_regenerate_focused(
        self,
        context: NavigationContext,
    ) -> tuple[NavigationAction, ...]:
        if context.busy:
            return (
                UpdateNavigationStatus(
                    "Wait for the current synthesis operation to finish."
                ),
            )
        if (
            self.focus_key[0] != "candidate"
            or self.focus_key not in self.navigation_items(context)
        ):
            return (
                UpdateNavigationStatus("Select a candidate before regenerating it."),
            )
        number = self.focus_key[1]
        if number is None:
            return (
                UpdateNavigationStatus("Select a candidate before regenerating it."),
            )
        return (RegenerateCandidate(number),)

    def open_help(self, context: NavigationContext) -> tuple[NavigationAction, ...]:
        actions = list(self.set_focus_key(context, ("help", None), moved=True))
        actions.append(OpenHelp())
        return tuple(actions)

    def reset_after_rebuild(
        self,
        context: NavigationContext,
    ) -> tuple[NavigationAction, ...]:
        self.segment_index = 0
        focus_key = (
            ("segment", 0)
            if context.has_session and context.segment_count > 0
            else ("generate", None)
        )
        return self.set_focus_key(context, focus_key, moved=True)

    def reset_segment_index(self) -> None:
        self.segment_index = 0

    def set_segment_index(self, index: int) -> None:
        self.segment_index = index

    @staticmethod
    def _candidate_playback_action(key: FocusKey) -> tuple[NavigationAction, ...]:
        name, number = key
        if name == "candidate" and number is not None:
            return (PlayCandidate(number),)
        return ()
