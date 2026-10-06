"""Navigation state, movement policy, and application action requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple, Union

from .tui_selection import move_clamped_selection
from .tui_status import Status, info_status


FocusKey = Tuple[str, Optional[int]]


@dataclass(frozen=True)
class NavigationContext:
    """Immutable facts needed to derive the current selectable navigation rows."""

    has_session: bool
    pronunciation_count: int
    candidate_numbers: tuple[int, ...]
    busy: bool
    has_active_batch: bool
    has_item_navigator: bool = False

    @classmethod
    def from_session(
        cls,
        session: Any | None,
        *,
        pronunciation_count: int,
        busy: bool,
        has_item_navigator: bool,
    ) -> "NavigationContext":
        return cls(
            has_session=session is not None,
            pronunciation_count=pronunciation_count,
            candidate_numbers=(
                tuple(candidate.number for candidate in session.candidates)
                if session is not None
                else ()
            ),
            busy=busy,
            has_active_batch=(
                session.has_active_batch if session is not None else False
            ),
            has_item_navigator=has_item_navigator,
        )


@dataclass(frozen=True)
class ClearAdjustmentFeedback:
    pass


@dataclass(frozen=True)
class UpdateNavigationStatus:
    status: Status

    def __init__(self, status: Status | str) -> None:
        object.__setattr__(
            self,
            "status",
            status if isinstance(status, Status) else info_status(status),
        )


@dataclass(frozen=True)
class OpenSettingsEditor:
    selected_field: str
    edit: bool = False


@dataclass(frozen=True)
class EditOutputPath:
    pass


@dataclass(frozen=True)
class OpenCaptionEditor:
    pass


@dataclass(frozen=True)
class EditPronunciationItem:
    index: int


@dataclass(frozen=True)
class AddSectionEditor:
    pass


@dataclass(frozen=True)
class StartGeneration:
    pass


@dataclass(frozen=True)
class RegenerateAll:
    pass


@dataclass(frozen=True)
class BuildPronunciation:
    pass


@dataclass(frozen=True)
class AcceptCandidate:
    number: int


@dataclass(frozen=True)
class RegenerateCandidate:
    number: int


@dataclass(frozen=True)
class OpenClearCandidatesConfirmation:
    pass


@dataclass(frozen=True)
class DeleteCaption:
    pass


@dataclass(frozen=True)
class PlayCandidate:
    number: int


@dataclass(frozen=True)
class OpenHelp:
    pass


@dataclass(frozen=True)
class OpenDictionary:
    pass


@dataclass(frozen=True)
class Quit:
    pass


NavigationAction = Union[
    ClearAdjustmentFeedback,
    UpdateNavigationStatus,
    OpenSettingsEditor,
    EditOutputPath,
    OpenCaptionEditor,
    EditPronunciationItem,
    AddSectionEditor,
    StartGeneration,
    RegenerateAll,
    BuildPronunciation,
    AcceptCandidate,
    RegenerateCandidate,
    OpenClearCandidatesConfirmation,
    DeleteCaption,
    PlayCandidate,
    OpenHelp,
    OpenDictionary,
    Quit,
]


class TuiNavigation:
    """Own focus and navigation policy without depending on application objects."""

    def __init__(self) -> None:
        self.focus_key: FocusKey = ("caption", None)
        self.pronunciation_index = 0
        self.revision = 0

    def navigation_items(self, context: NavigationContext) -> tuple[FocusKey, ...]:
        items: list[FocusKey] = []
        if context.has_item_navigator:
            items.append(("batch_item", None))
        items.extend([
            ("settings_summary", None),
            ("output", None),
            ("caption", None),
        ])
        if context.has_session:
            items.append(("build_pronunciation", None))
            items.extend(
                ("pronunciation", index)
                for index in range(context.pronunciation_count)
            )
            items.append(("add_section", None))
            items.extend(
                ("candidate", number) for number in context.candidate_numbers
            )
            items.append(("generate", None))
            if context.candidate_numbers:
                items.append(("clear_candidates", None))
            items.append(("delete_caption", None))
        items.extend(
            (("settings", None), ("dictionary", None), ("help", None), ("quit", None))
        )
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
            if name in {"pronunciation", "candidate"}:
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
            remembered_item = ("pronunciation", self.pronunciation_index)
            if remembered_item in items:
                key = remembered_item
            elif ("build_pronunciation", None) in items:
                key = ("build_pronunciation", None)
            else:
                key = ("caption", None)
        if key not in items:
            key = items[0]

        changed = key != self.focus_key
        self.focus_key = key
        if key[0] == "pronunciation" and key[1] is not None:
            self.pronunciation_index = key[1]
        if not changed:
            return ()
        if moved:
            self.revision += 1
        return (ClearAdjustmentFeedback(),)

    def move(self, context: NavigationContext, delta: int) -> tuple[NavigationAction, ...]:
        result = move_clamped_selection(
            self.focus_key,
            self.navigation_items(context),
            delta=delta,
        )
        if result is None or not result.changed:
            return ()
        key = result.selection
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
        current = self.focus_key
        if current not in stops:
            current = next(
                (
                    key
                    for key in stops
                    if key[0] == self.focus_key[0]
                ),
                stops[0],
            )
        result = move_clamped_selection(current, stops, delta=delta)
        if result is None or not result.changed:
            return ()
        key = result.selection
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

    def activate_focused_item(
        self,
        context: NavigationContext,
    ) -> tuple[NavigationAction, ...]:
        return self.activate_item(context, self.focus_key)

    def activate_item(
        self,
        context: NavigationContext,
        key: FocusKey,
    ) -> tuple[NavigationAction, ...]:
        if key == ("clear_candidates", None) and context.busy:
            return (
                UpdateNavigationStatus(
                    "Finish or cancel synthesis before clearing candidates."
                ),
            )
        if key not in self.navigation_items(context):
            return ()
        name, number = key
        if name == "settings_summary":
            return (OpenSettingsEditor("style_id"),)
        if name == "output":
            return (EditOutputPath(),)
        if name == "caption":
            if context.busy:
                return (
                    UpdateNavigationStatus(
                        "Wait for synthesis to finish before editing Caption."
                    ),
                )
            return (OpenCaptionEditor(),)
        if name == "pronunciation" and number is not None:
            if context.busy:
                return (
                    UpdateNavigationStatus(
                        "Wait for synthesis to finish before editing pronunciation."
                    ),
                )
            return (EditPronunciationItem(number),)
        if name == "add_section":
            if context.busy:
                return (
                    UpdateNavigationStatus(
                        "Wait for synthesis to finish before adding a section."
                    ),
                )
            return (AddSectionEditor(),)
        if name == "generate":
            return self.activate_generate(context)
        if name == "build_pronunciation":
            if context.busy:
                return (
                    UpdateNavigationStatus(
                        "Wait for the current synthesis operation to finish."
                    ),
                )
            return (BuildPronunciation(),)
        if name == "candidate" and number is not None:
            if context.busy:
                return (
                    UpdateNavigationStatus(
                        "Wait for generation to finish before accepting a take."
                    ),
                )
            return (AcceptCandidate(number),)
        if name == "clear_candidates":
            return (OpenClearCandidatesConfirmation(),)
        if name == "delete_caption":
            if context.busy:
                return (UpdateNavigationStatus("Finish or cancel synthesis before deleting Caption."),)
            return (DeleteCaption(),)
        if name == "settings":
            return (OpenSettingsEditor("style_id"),)
        if name == "dictionary":
            return (OpenDictionary(),)
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
        self.pronunciation_index = 0
        focus_key = (
            ("pronunciation", 0)
            if context.has_session and context.pronunciation_count > 0
            else ("build_pronunciation", None)
        )
        return self.set_focus_key(context, focus_key, moved=True)

    def reset_pronunciation_index(self) -> None:
        self.pronunciation_index = 0

    def mark_context_change(self) -> None:
        """Advance the revision when navigation leaves the current screen context."""

        self.revision += 1

    @staticmethod
    def _candidate_playback_action(key: FocusKey) -> tuple[NavigationAction, ...]:
        name, number = key
        if name == "candidate" and number is not None:
            return (PlayCandidate(number),)
        return ()
