import unittest

from voiceger_accent_adapter.tui_navigation import (
    AcceptCandidate,
    BuildPronunciation,
    ClearAdjustmentFeedback,
    EditPronunciationItem,
    NavigationContext,
    OpenHelp,
    OpenSettingsEditor,
    OpenCaptionEditor,
    PlayCandidate,
    Quit,
    RegenerateAll,
    RegenerateCandidate,
    StartGeneration,
    TuiNavigation,
    UpdateNavigationStatus,
)


def context(
    *,
    has_session=True,
    pronunciation_count=4,
    candidate_numbers=(1, 2),
    busy=False,
    has_active_batch=False,
):
    return NavigationContext(
        has_session=has_session,
        pronunciation_count=pronunciation_count,
        candidate_numbers=tuple(candidate_numbers),
        busy=busy,
        has_active_batch=has_active_batch,
    )


class TuiNavigationTests(unittest.TestCase):
    def setUp(self):
        self.navigation = TuiNavigation()

    def test_items_include_each_pronunciation_child_in_order(self):
        self.assertEqual(
            self.navigation.navigation_items(
                context(pronunciation_count=4, candidate_numbers=(5, 2))
            ),
            (
                ("settings_summary", None),
                ("output", None),
                ("caption", None),
                ("build_pronunciation", None),
                ("pronunciation", 0),
                ("pronunciation", 1),
                ("pronunciation", 2),
                ("pronunciation", 3),
                ("generate", None),
                ("candidate", 5),
                ("candidate", 2),
                ("settings", None),
                ("help", None),
                ("quit", None),
            ),
        )

    def test_no_session_omits_session_actions_and_rows(self):
        self.assertEqual(
            self.navigation.navigation_items(
                context(has_session=False, candidate_numbers=(4, 2))
            ),
            (
                ("settings_summary", None),
                ("output", None),
                ("caption", None),
                ("settings", None),
                ("help", None),
                ("quit", None),
            ),
        )

    def test_major_navigation_keeps_pronunciation_as_one_section(self):
        self.assertEqual(
            self.navigation.major_navigation_stops(
                context(candidate_numbers=(5, 2, 8))
            ),
            (
                ("settings_summary", None),
                ("output", None),
                ("caption", None),
                ("build_pronunciation", None),
                ("pronunciation", 0),
                ("generate", None),
                ("candidate", 5),
                ("settings", None),
                ("help", None),
                ("quit", None),
            ),
        )

    def test_up_and_down_visit_each_child_without_extra_wrap_stops(self):
        state = context(pronunciation_count=3, candidate_numbers=())
        self.navigation.focus_key = ("caption", None)
        self.assertEqual(
            self.navigation.move(state, 1), (ClearAdjustmentFeedback(),)
        )
        self.assertEqual(self.navigation.focus_key, ("build_pronunciation", None))
        for index in range(3):
            self.assertEqual(
                self.navigation.move(state, 1), (ClearAdjustmentFeedback(),)
            )
            self.assertEqual(self.navigation.focus_key, ("pronunciation", index))
        self.assertEqual(
            self.navigation.move(state, 1), (ClearAdjustmentFeedback(),)
        )
        self.assertEqual(self.navigation.focus_key, ("generate", None))
        self.navigation.focus_key = ("pronunciation", 1)
        self.assertEqual(
            self.navigation.move_section(state, 1), (ClearAdjustmentFeedback(),)
        )
        self.assertEqual(self.navigation.focus_key, ("generate", None))

    def test_candidate_rows_play_on_arrow_and_escape_restores_last_child(self):
        state = context(pronunciation_count=3, candidate_numbers=(4, 7))
        self.navigation.set_focus_key(state, ("pronunciation", 2))
        self.assertEqual(self.navigation.pronunciation_index, 2)
        self.navigation.set_focus_key(state, ("candidate", 4))
        self.assertEqual(
            self.navigation.move(state, 1),
            (ClearAdjustmentFeedback(), PlayCandidate(7)),
        )
        self.assertEqual(self.navigation.focus_key, ("candidate", 7))
        self.assertEqual(
            self.navigation.escape_candidate(state),
            (
                ClearAdjustmentFeedback(),
                UpdateNavigationStatus("Returned to pronunciation."),
            ),
        )
        self.assertEqual(self.navigation.focus_key, ("pronunciation", 2))

    def test_major_section_navigation_from_later_child_uses_pronunciation_stop(self):
        state = context(pronunciation_count=4, candidate_numbers=(3, 6))
        self.navigation.focus_key = ("pronunciation", 3)
        self.assertEqual(
            self.navigation.move_section(state, 1), (ClearAdjustmentFeedback(),)
        )
        self.assertEqual(self.navigation.focus_key, ("generate", None))
        self.navigation.focus_key = ("pronunciation", 3)
        self.assertEqual(
            self.navigation.move_section(state, -1), (ClearAdjustmentFeedback(),)
        )
        self.assertEqual(self.navigation.focus_key, ("build_pronunciation", None))

    def test_candidate_section_and_vertical_navigation_preserve_order(self):
        state = context(candidate_numbers=(4, 7))
        self.navigation.focus_key = ("generate", None)
        self.assertEqual(
            self.navigation.move(state, 1),
            (ClearAdjustmentFeedback(), PlayCandidate(4)),
        )
        self.assertEqual(
            self.navigation.move(state, 1),
            (ClearAdjustmentFeedback(), PlayCandidate(7)),
        )
        self.assertEqual(
            self.navigation.move_section(state, 1),
            (ClearAdjustmentFeedback(),),
        )
        self.assertEqual(self.navigation.focus_key, ("settings", None))

    def test_focus_fallback_prefers_remembered_child_then_build_then_caption(self):
        available = context(pronunciation_count=4)
        self.navigation.pronunciation_index = 3
        self.assertEqual(
            self.navigation.set_focus_key(available, ("candidate", 99)),
            (ClearAdjustmentFeedback(),),
        )
        self.assertEqual(self.navigation.focus_key, ("pronunciation", 3))

        build_only = context(pronunciation_count=0, candidate_numbers=())
        self.assertEqual(
            self.navigation.set_focus_key(build_only, ("pronunciation", 3)),
            (ClearAdjustmentFeedback(),),
        )
        self.assertEqual(self.navigation.focus_key, ("build_pronunciation", None))
        self.assertEqual(
            self.navigation.set_focus_key(
                context(has_session=False), ("build_pronunciation", None)
            ),
            (ClearAdjustmentFeedback(),),
        )
        self.assertEqual(self.navigation.focus_key, ("caption", None))

    def test_caption_build_and_pronunciation_are_consecutive_main_rows(self):
        state = context(pronunciation_count=2)
        self.navigation.focus_key = ("caption", None)
        self.navigation.move(state, 1)
        self.assertEqual(self.navigation.focus_key, ("build_pronunciation", None))
        self.navigation.move(state, 1)
        self.assertEqual(self.navigation.focus_key, ("pronunciation", 0))

    def test_set_focus_updates_remembered_index_even_when_key_is_unchanged(self):
        self.navigation.focus_key = ("pronunciation", 2)
        self.navigation.pronunciation_index = 0
        self.assertEqual(
            self.navigation.set_focus_key(
                context(pronunciation_count=3), ("pronunciation", 2), moved=True
            ),
            (),
        )
        self.assertEqual(self.navigation.pronunciation_index, 2)
        self.assertEqual(self.navigation.revision, 0)

    def test_focus_actions_and_busy_guards(self):
        state = context(candidate_numbers=(1,))
        mappings = (
            (("settings_summary", None), OpenSettingsEditor("style_id")),
            (("output", None), OpenSettingsEditor("output_dir", edit=True)),
            (("caption", None), OpenCaptionEditor()),
            (("pronunciation", 1), EditPronunciationItem(1)),
            (("generate", None), StartGeneration()),
            (("build_pronunciation", None), BuildPronunciation()),
            (("candidate", 1), AcceptCandidate(1)),
            (("settings", None), OpenSettingsEditor("style_id")),
            (("help", None), OpenHelp()),
            (("quit", None), Quit()),
        )
        for focus_key, expected in mappings:
            with self.subTest(focus_key=focus_key):
                self.navigation.focus_key = focus_key
                self.assertEqual(
                    self.navigation.activate_focused_item(state), (expected,)
                )
        self.navigation.focus_key = ("pronunciation", 1)
        self.assertEqual(
            self.navigation.activate_focused_item(context(busy=True)),
            (UpdateNavigationStatus("Wait for synthesis to finish before editing pronunciation."),),
        )

    def test_generate_regenerate_and_candidate_regeneration_behavior(self):
        self.navigation.focus_key = ("generate", None)
        self.assertEqual(
            self.navigation.activate_focused_item(context()), (StartGeneration(),)
        )
        self.assertEqual(
            self.navigation.activate_focused_item(context(has_active_batch=True)),
            (RegenerateAll(),),
        )
        self.navigation.focus_key = ("candidate", 6)
        self.assertEqual(
            self.navigation.activate_regenerate_focused(
                context(candidate_numbers=(2, 6))
            ),
            (RegenerateCandidate(6),),
        )
        self.assertEqual(
            self.navigation.activate_regenerate_focused(context(busy=True)),
            (UpdateNavigationStatus("Wait for the current synthesis operation to finish."),),
        )

    def test_rebuild_resets_to_first_pronunciation_child(self):
        self.navigation.pronunciation_index = 3
        self.navigation.focus_key = ("candidate", 1)
        self.assertEqual(
            self.navigation.reset_after_rebuild(context(pronunciation_count=4)),
            (ClearAdjustmentFeedback(),),
        )
        self.assertEqual(self.navigation.pronunciation_index, 0)
        self.assertEqual(self.navigation.focus_key, ("pronunciation", 0))


if __name__ == "__main__":
    unittest.main()
