import curses
import unittest

from voiceger_editor.tui_batch import (
    AddCaptions,
    AdjustBatchTakeCount,
    GenerateSelected,
    OpenBatchDictionary,
    OpenBatchHelp,
    OpenBatchItem,
    OpenBatchSettings,
    QuitBatch,
    TuiBatchController,
)


class FakeSession:
    def __init__(self, caption):
        self.caption = caption
        self.closed = False
        self.close_calls = 0

    def close(self):
        self.closed = True
        self.close_calls += 1


class TuiBatchControllerTests(unittest.TestCase):
    def make_controller(self, text=""):
        controller = TuiBatchController(default_take_count=4)
        if text:
            controller.add_captions(text, session_factory=FakeSession)
        return controller

    def test_batch_list_items_keep_takes_captions_and_actions_in_vertical_order(self):
        controller = self.make_controller("first\nsecond")
        self.assertEqual(
            controller.navigation_items(),
            (
                ("takes", None),
                ("caption", 0),
                ("caption", 1),
                ("add_captions", None),
                ("generate_selected", None),
                ("settings", None),
                ("dictionary", None),
                ("help", None),
                ("quit", None),
            ),
        )

    def test_space_toggles_focused_caption_without_changing_focus(self):
        controller = self.make_controller("first\nsecond")
        controller.focus_key = ("caption", 1)

        self.assertTrue(controller.batch.items[1].included_for_generation)
        self.assertEqual(controller.handle_key(" "), ())
        self.assertFalse(controller.batch.items[1].included_for_generation)
        self.assertEqual(controller.focus_key, ("caption", 1))

        controller.handle_key(" ")
        self.assertTrue(controller.batch.items[1].included_for_generation)

    def test_x_requests_delete_only_for_focused_caption_and_escape_cancels(self):
        controller = self.make_controller("first\nsecond")
        target = controller.batch.items[1]
        controller.focus_key = ("takes", None)

        self.assertEqual(controller.handle_key("x"), ())
        self.assertFalse(controller.delete_confirmation_active)

        controller.focus_key = ("caption", 1)
        self.assertEqual(controller.handle_key("x"), ())
        self.assertTrue(controller.delete_confirmation_active)
        self.assertEqual(controller.delete_confirmation_caption, "second")
        self.assertTrue(target.included_for_generation)

        self.assertEqual(controller.handle_key(" "), ())
        self.assertTrue(target.included_for_generation)
        self.assertEqual(controller.handle_key("\x1b"), ())
        self.assertFalse(controller.delete_confirmation_active)
        self.assertEqual(controller.focus_key, ("caption", 1))
        self.assertEqual(
            [item.caption for item in controller.batch.items],
            ["first", "second"],
        )
        self.assertEqual(target.session.close_calls, 0)

    def test_open_item_delete_cancel_keeps_item_and_confirm_returns_to_list(self):
        controller = self.make_controller("first\nsecond")
        target = controller.batch.items[1]
        controller.focus_key = ("caption", 1)
        controller.open_item(1)

        controller.request_delete_open_item()
        self.assertTrue(controller.delete_confirmation_active)
        self.assertEqual(controller.delete_confirmation_caption, "second")
        controller.handle_key("\x1b")

        self.assertTrue(controller.in_item)
        self.assertEqual(controller.item_title, "BATCH ITEM 2/2")
        self.assertEqual(target.session.close_calls, 0)

        controller.request_delete_open_item()
        controller.handle_key("d")

        self.assertFalse(controller.in_item)
        self.assertEqual(
            [item.caption for item in controller.batch.items],
            ["first"],
        )
        self.assertEqual(controller.focus_key, ("caption", 0))
        self.assertEqual(target.session.close_calls, 1)

    def test_confirmed_delete_targets_pending_stable_id_and_closes_only_removed_session(self):
        controller = self.make_controller("first\nsecond\nthird")
        target = controller.batch.items[1]
        survivors = (controller.batch.items[0], controller.batch.items[2])
        controller.focus_key = ("caption", 1)
        controller.handle_key("x")

        controller.batch.move_item(target.item_id, 0)
        controller.handle_key("d")

        self.assertFalse(controller.delete_confirmation_active)
        self.assertEqual(
            [item.caption for item in controller.batch.items],
            ["first", "third"],
        )
        self.assertEqual(target.session.close_calls, 1)
        self.assertEqual([item.session.close_calls for item in survivors], [0, 0])
        self.assertEqual(controller.focus_key, ("caption", 0))

        controller.close_sessions()
        self.assertEqual(target.session.close_calls, 1)
        self.assertEqual([item.session.close_calls for item in survivors], [1, 1])

    def test_delete_repairs_focus_for_first_middle_last_and_final_caption(self):
        cases = (
            (0, ["second", "third"], ("caption", 0)),
            (1, ["first", "third"], ("caption", 1)),
            (2, ["first", "second"], ("caption", 1)),
        )
        for index, expected_captions, expected_focus in cases:
            with self.subTest(index=index):
                controller = self.make_controller("first\nsecond\nthird")
                controller.focus_key = ("caption", index)
                controller.handle_key("x")
                controller.handle_key("d")
                self.assertEqual(
                    [item.caption for item in controller.batch.items],
                    expected_captions,
                )
                self.assertEqual(controller.focus_key, expected_focus)

        final = self.make_controller("only")
        only_session = final.batch.items[0].session
        final.focus_key = ("caption", 0)
        final.handle_key("x")
        final.handle_key("d")
        self.assertEqual(final.batch.items, ())
        self.assertEqual(final.focus_key, ("takes", None))
        self.assertEqual(only_session.close_calls, 1)

    def test_enter_opens_focused_caption_by_list_position(self):
        controller = self.make_controller("first\nsecond")
        controller.focus_key = ("caption", 1)

        self.assertEqual(controller.handle_key("\n"), (OpenBatchItem(1),))
        session = controller.open_item(1)
        self.assertIs(session, controller.batch.items[1].session)
        self.assertTrue(controller.in_item)
        self.assertEqual(controller.item_title, "BATCH ITEM 2/2")

        controller.close_item()
        self.assertFalse(controller.in_item)
        self.assertEqual(controller.focus_key, ("caption", 1))

    def test_left_right_adjust_only_the_focused_batch_take_count(self):
        controller = self.make_controller("first")

        self.assertEqual(
            controller.handle_key(curses.KEY_RIGHT),
            (AdjustBatchTakeCount(1),),
        )
        controller.focus_key = ("caption", 0)
        self.assertEqual(controller.handle_key(curses.KEY_LEFT), ())

    def test_batch_list_shortcuts_emit_settled_actions(self):
        controller = self.make_controller("first")
        expected = {
            "a": AddCaptions(),
            "g": GenerateSelected(),
            "s": OpenBatchSettings(),
            "d": OpenBatchDictionary(),
            "?": OpenBatchHelp(),
            "q": QuitBatch(),
            "Q": QuitBatch(),
        }
        for key, action in expected.items():
            with self.subTest(key=key):
                self.assertEqual(controller.handle_key(key), (action,))

    def test_add_captions_uses_frontend_neutral_multiline_model(self):
        controller = self.make_controller()
        controller.add_captions(
            "first\n\nsecond\nthird",
            session_factory=FakeSession,
        )
        self.assertEqual(
            [item.caption for item in controller.batch.items],
            ["first", "second", "third"],
        )
        self.assertTrue(
            all(item.included_for_generation for item in controller.batch.items)
        )

    def test_close_sessions_closes_every_owned_item_session(self):
        controller = self.make_controller("first\nsecond")
        sessions = controller.sessions
        controller.close_sessions()
        self.assertTrue(all(session.closed for session in sessions))


if __name__ == "__main__":
    unittest.main()
