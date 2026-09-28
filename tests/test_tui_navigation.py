import unittest

from voiceger_accent_adapter.tui_navigation import (
    AcceptCandidate,
    ClearAdjustmentFeedback,
    EditPronunciationSegment,
    NavigationContext,
    OpenHelp,
    OpenSettingsEditor,
    OpenTextEditor,
    PlayCandidate,
    Quit,
    RebuildPronunciation,
    RegenerateAll,
    RegenerateCandidate,
    StartGeneration,
    TuiNavigation,
    UpdateNavigationStatus,
)


def context(
    *,
    has_session=True,
    pronunciation_needs_rebuild=False,
    segment_count=2,
    candidate_numbers=(1, 2),
    busy=False,
    has_active_batch=False,
):
    return NavigationContext(
        has_session=has_session,
        pronunciation_needs_rebuild=pronunciation_needs_rebuild,
        segment_count=segment_count,
        candidate_numbers=tuple(candidate_numbers),
        busy=busy,
        has_active_batch=has_active_batch,
    )


class TuiNavigationTests(unittest.TestCase):
    def setUp(self):
        self.navigation = TuiNavigation()

    def test_full_item_order_preserves_mixed_language_segments_and_candidate_order(self):
        self.assertEqual(
            self.navigation.navigation_items(
                context(segment_count=3, candidate_numbers=(5, 2, 8))
            ),
            (
                ("settings_summary", None),
                ("output", None),
                ("text", None),
                ("segment", 0),
                ("segment", 1),
                ("segment", 2),
                ("rebuild", None),
                ("generate", None),
                ("candidate", 5),
                ("candidate", 2),
                ("candidate", 8),
                ("settings", None),
                ("help", None),
                ("quit", None),
            ),
        )

    def test_no_session_item_order_omits_session_actions_and_rows(self):
        self.assertEqual(
            self.navigation.navigation_items(
                context(
                    has_session=False,
                    segment_count=3,
                    candidate_numbers=(4, 2),
                    has_active_batch=True,
                )
            ),
            (
                ("settings_summary", None),
                ("output", None),
                ("text", None),
                ("settings", None),
                ("help", None),
                ("quit", None),
            ),
        )

    def test_rebuild_required_context_omits_segment_rows(self):
        items = self.navigation.navigation_items(
            context(pronunciation_needs_rebuild=True, segment_count=4)
        )
        self.assertFalse(any(name == "segment" for name, _number in items))
        self.assertIn(("rebuild", None), items)

    def test_major_stops_collapse_all_consecutive_segments_and_candidates(self):
        self.assertEqual(
            self.navigation.major_navigation_stops(
                context(segment_count=3, candidate_numbers=(5, 2, 8))
            ),
            (
                ("settings_summary", None),
                ("output", None),
                ("text", None),
                ("segment", 0),
                ("rebuild", None),
                ("generate", None),
                ("candidate", 5),
                ("settings", None),
                ("help", None),
                ("quit", None),
            ),
        )

    def test_major_stops_have_no_candidate_section_when_candidates_are_empty(self):
        stops = self.navigation.major_navigation_stops(context(candidate_numbers=()))
        self.assertIn(("generate", None), stops)
        self.assertNotIn(("candidate", None), stops)
        self.assertEqual(stops[-3:], (("settings", None), ("help", None), ("quit", None)))

    def test_up_and_down_move_one_selectable_item_and_candidate_move_requests_playback(self):
        state = context(candidate_numbers=(4, 7))
        self.assertEqual(
            self.navigation.move(state, 1),
            (ClearAdjustmentFeedback(),),
        )
        self.assertEqual(self.navigation.focus_key, ("output", None))
        self.navigation.focus_key = ("generate", None)
        self.assertEqual(
            self.navigation.move(state, 1),
            (ClearAdjustmentFeedback(), PlayCandidate(4)),
        )
        self.assertEqual(self.navigation.focus_key, ("candidate", 4))
        self.assertEqual(
            self.navigation.move(state, 1),
            (ClearAdjustmentFeedback(), PlayCandidate(7)),
        )
        self.assertEqual(self.navigation.focus_key, ("candidate", 7))
        self.assertEqual(
            self.navigation.move(state, -1),
            (ClearAdjustmentFeedback(), PlayCandidate(4)),
        )
        self.assertEqual(self.navigation.focus_key, ("candidate", 4))

    def test_up_and_down_movement_clamps_without_wrapping(self):
        state = context(has_session=False)
        self.assertEqual(self.navigation.move(state, -1), ())
        self.navigation.focus_key = ("quit", None)
        self.assertEqual(self.navigation.move(state, 1), ())
        self.assertEqual(self.navigation.focus_key, ("quit", None))

    def test_tab_and_shift_tab_move_between_major_stops(self):
        state = context(segment_count=2, candidate_numbers=(3, 6))
        self.assertEqual(
            self.navigation.move_section(state, 1),
            (ClearAdjustmentFeedback(),),
        )
        self.assertEqual(self.navigation.focus_key, ("output", None))
        self.navigation.focus_key = ("generate", None)
        self.assertEqual(
            self.navigation.move_section(state, 1),
            (ClearAdjustmentFeedback(), PlayCandidate(3)),
        )
        self.assertEqual(
            self.navigation.move_section(state, -1),
            (ClearAdjustmentFeedback(),),
        )
        self.assertEqual(self.navigation.focus_key, ("generate", None))

    def test_tab_from_later_segment_or_candidate_uses_its_section_stop(self):
        state = context(segment_count=3, candidate_numbers=(4, 9))
        self.navigation.focus_key = ("segment", 2)
        self.assertEqual(
            self.navigation.move_section(state, 1),
            (ClearAdjustmentFeedback(),),
        )
        self.assertEqual(self.navigation.focus_key, ("rebuild", None))
        self.navigation.focus_key = ("segment", 2)
        self.navigation.move_section(state, -1)
        self.assertEqual(self.navigation.focus_key, ("text", None))

        self.navigation.focus_key = ("candidate", 9)
        self.assertEqual(
            self.navigation.move_section(state, 1),
            (ClearAdjustmentFeedback(),),
        )
        self.assertEqual(self.navigation.focus_key, ("settings", None))
        self.navigation.focus_key = ("candidate", 9)
        self.assertEqual(
            self.navigation.move_section(state, -1),
            (ClearAdjustmentFeedback(),),
        )
        self.assertEqual(self.navigation.focus_key, ("generate", None))

    def test_tab_and_shift_tab_clamp_at_the_ends(self):
        state = context(has_session=False)
        self.assertEqual(self.navigation.move_section(state, -1), ())
        self.navigation.focus_key = ("quit", None)
        self.assertEqual(self.navigation.move_section(state, 1), ())
        self.assertEqual(self.navigation.focus_key, ("quit", None))

    def test_focus_fallback_prefers_remembered_segment_then_rebuild_then_text(self):
        state_with_segments = context(segment_count=3)
        self.navigation.segment_index = 2
        self.assertEqual(
            self.navigation.set_focus_key(state_with_segments, ("candidate", 99)),
            (ClearAdjustmentFeedback(),),
        )
        self.assertEqual(self.navigation.focus_key, ("segment", 2))

        rebuild_only = context(
            pronunciation_needs_rebuild=True,
            segment_count=0,
            candidate_numbers=(),
        )
        self.navigation.segment_index = 5
        self.assertEqual(
            self.navigation.set_focus_key(rebuild_only, ("segment", 5)),
            (ClearAdjustmentFeedback(),),
        )
        self.assertEqual(self.navigation.focus_key, ("rebuild", None))

        no_session = context(has_session=False)
        self.assertEqual(
            self.navigation.set_focus_key(no_session, ("rebuild", None)),
            (ClearAdjustmentFeedback(),),
        )
        self.assertEqual(self.navigation.focus_key, ("text", None))

    def test_focus_falls_back_to_first_available_item_when_text_is_unavailable(self):
        class MinimalNavigation(TuiNavigation):
            def navigation_items(self, _context):
                return (("settings_summary", None),)

        navigation = MinimalNavigation()
        navigation.focus_key = ("quit", None)
        self.assertEqual(
            navigation.set_focus_key(context(has_session=False), ("missing", None)),
            (ClearAdjustmentFeedback(),),
        )
        self.assertEqual(navigation.focus_key, ("settings_summary", None))

    def test_remembered_segment_updates_when_segment_focus_is_set(self):
        self.navigation.set_focus_key(context(segment_count=3), ("segment", 2))
        self.assertEqual(self.navigation.segment_index, 2)

    def test_same_segment_focus_refreshes_remembered_index_without_revision_or_effect(self):
        self.navigation.focus_key = ("segment", 2)
        self.navigation.segment_index = 0
        self.assertEqual(
            self.navigation.set_focus_key(
                context(segment_count=3),
                ("segment", 2),
                moved=True,
            ),
            (),
        )
        self.assertEqual(self.navigation.segment_index, 2)
        self.assertEqual(self.navigation.revision, 0)

    def test_revision_changes_only_for_actual_explicit_focus_movement(self):
        state = context(has_session=False)
        self.assertEqual(
            self.navigation.set_focus_key(state, ("settings_summary", None), moved=True),
            (),
        )
        self.assertEqual(self.navigation.revision, 0)
        self.navigation.set_focus_key(state, ("output", None))
        self.assertEqual(self.navigation.revision, 0)
        self.navigation.set_focus_key(state, ("text", None), moved=True)
        self.assertEqual(self.navigation.revision, 1)
        self.navigation.set_focus_key(state, ("text", None), moved=True)
        self.assertEqual(self.navigation.revision, 1)

    def test_adjustment_feedback_clears_only_when_focus_changes(self):
        state = context(has_session=False)
        self.assertEqual(
            self.navigation.set_focus_key(state, ("settings_summary", None)),
            (),
        )
        self.assertEqual(
            self.navigation.set_focus_key(state, ("output", None)),
            (ClearAdjustmentFeedback(),),
        )

    def test_plain_candidate_focus_does_not_request_playback(self):
        self.assertEqual(
            self.navigation.set_focus_key(context(), ("candidate", 2)),
            (ClearAdjustmentFeedback(),),
        )
        self.assertEqual(self.navigation.focus_key, ("candidate", 2))

    def test_candidate_number_focus_plays_valid_candidate_and_reports_unavailable(self):
        state = context(candidate_numbers=(2, 5))
        self.assertEqual(
            self.navigation.focus_candidate(state, 5),
            (ClearAdjustmentFeedback(), PlayCandidate(5)),
        )
        self.assertEqual(self.navigation.focus_key, ("candidate", 5))
        self.assertEqual(
            self.navigation.focus_candidate(state, 8),
            (UpdateNavigationStatus("Take 8 has not been generated yet."),),
        )
        self.assertEqual(self.navigation.focus_key, ("candidate", 5))

    def test_candidate_escape_returns_to_remembered_segment_and_keeps_selection_unmanaged(self):
        state = context(segment_count=3, candidate_numbers=(1,))
        self.navigation.segment_index = 2
        self.navigation.focus_key = ("candidate", 1)
        self.assertEqual(
            self.navigation.escape_candidate(state),
            (
                ClearAdjustmentFeedback(),
                UpdateNavigationStatus("Returned to the last pronunciation segment."),
            ),
        )
        self.assertEqual(self.navigation.focus_key, ("segment", 2))
        self.assertEqual(self.navigation.revision, 1)
        self.assertIsNone(self.navigation.escape_candidate(state))

    def test_focused_action_mapping_for_all_navigation_rows(self):
        state = context(candidate_numbers=(1,))
        mappings = (
            (("settings_summary", None), OpenSettingsEditor("style_id")),
            (("output", None), OpenSettingsEditor("output_dir", edit=True)),
            (("text", None), OpenTextEditor()),
            (("segment", 1), EditPronunciationSegment(1)),
            (("generate", None), StartGeneration()),
            (("rebuild", None), RebuildPronunciation()),
            (("candidate", 1), AcceptCandidate(1)),
            (("settings", None), OpenSettingsEditor("style_id")),
            (("help", None), OpenHelp()),
            (("quit", None), Quit()),
        )
        for focus_key, expected in mappings:
            with self.subTest(focus_key=focus_key):
                self.navigation.focus_key = focus_key
                self.assertEqual(
                    self.navigation.activate_focused_item(state),
                    (expected,),
                )

    def test_generate_selects_initial_generation_or_regenerate_all(self):
        self.navigation.focus_key = ("generate", None)
        self.assertEqual(
            self.navigation.activate_focused_item(context(has_active_batch=False)),
            (StartGeneration(),),
        )
        self.assertEqual(
            self.navigation.activate_focused_item(context(has_active_batch=True)),
            (RegenerateAll(),),
        )
        self.assertEqual(
            self.navigation.activate_generate(
                context(has_session=False, has_active_batch=True)
            ),
            (StartGeneration(),),
        )

    def test_focused_actions_return_existing_busy_statuses(self):
        busy_context = context(busy=True, candidate_numbers=(1,))
        statuses = (
            (("text", None), "Wait for synthesis to finish before editing text."),
            (
                ("segment", 0),
                "Wait for synthesis to finish before editing pronunciation.",
            ),
            (("generate", None), "A sequential take operation is already running."),
            (
                ("rebuild", None),
                "Wait for the current synthesis operation to finish.",
            ),
            (
                ("candidate", 1),
                "Wait for generation to finish before accepting a take.",
            ),
        )
        for focus_key, expected_status in statuses:
            with self.subTest(focus_key=focus_key):
                self.navigation.focus_key = focus_key
                self.assertEqual(
                    self.navigation.activate_focused_item(busy_context),
                    (UpdateNavigationStatus(expected_status),),
                )

    def test_focused_candidate_regeneration_and_invalid_or_busy_statuses(self):
        state = context(candidate_numbers=(2, 6))
        self.navigation.focus_key = ("candidate", 6)
        self.assertEqual(
            self.navigation.activate_regenerate_focused(state),
            (RegenerateCandidate(6),),
        )
        self.navigation.focus_key = ("generate", None)
        self.assertEqual(
            self.navigation.activate_regenerate_focused(state),
            (UpdateNavigationStatus("Select a candidate before regenerating it."),),
        )
        self.navigation.focus_key = ("candidate", 9)
        self.assertEqual(
            self.navigation.activate_regenerate_focused(state),
            (UpdateNavigationStatus("Select a candidate before regenerating it."),),
        )
        self.navigation.focus_key = ("candidate", 6)
        self.assertEqual(
            self.navigation.activate_regenerate_focused(
                context(busy=True, candidate_numbers=(2, 6))
            ),
            (
                UpdateNavigationStatus(
                    "Wait for the current synthesis operation to finish."
                ),
            ),
        )

    def test_open_help_focuses_explicitly_before_returning_open_action(self):
        self.assertEqual(
            self.navigation.open_help(context(has_session=False)),
            (ClearAdjustmentFeedback(), OpenHelp()),
        )
        self.assertEqual(self.navigation.focus_key, ("help", None))
        self.assertEqual(self.navigation.revision, 1)

    def test_rebuild_reset_uses_navigation_focus_api_and_remembers_first_segment(self):
        self.navigation.segment_index = 4
        self.navigation.focus_key = ("candidate", 1)
        self.assertEqual(
            self.navigation.reset_after_rebuild(context(segment_count=2)),
            (ClearAdjustmentFeedback(),),
        )
        self.assertEqual(self.navigation.segment_index, 0)
        self.assertEqual(self.navigation.focus_key, ("segment", 0))


if __name__ == "__main__":
    unittest.main()
