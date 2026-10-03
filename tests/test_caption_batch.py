import unittest

from voiceger_editor.caption_batch import CaptionBatch, CaptionBatchItem


class FakeSession:
    """Small UI/runtime-free stand-in for single-utterance state."""

    def __init__(self, caption):
        self.caption = caption
        self.pronunciation = "initial"
        self.settings = {"style_id": 3, "speed": 1.0}

    def replace_caption(self, caption):
        self.caption = caption

    def replace_pronunciation(self, pronunciation):
        self.pronunciation = pronunciation

    def replace_settings(self, settings):
        self.settings = settings


class CaptionBatchTests(unittest.TestCase):
    def make_item(self, caption, **kwargs):
        return CaptionBatchItem(FakeSession(caption), **kwargs)

    def test_multiline_text_creates_one_included_item_per_non_empty_line(self):
        batch = CaptionBatch(default_take_count=4)

        created = batch.add_captions_from_text(
            "first\n\n  second  \r\n   \nthird",
            session_factory=FakeSession,
        )

        self.assertEqual(
            [item.caption for item in created],
            ["first", "  second  ", "third"],
        )
        self.assertEqual(batch.items, created)
        self.assertEqual(len({item.item_id for item in created}), 3)
        self.assertTrue(all(item.included_for_generation for item in created))

    def test_stable_item_identity_survives_insertion_and_reordering(self):
        first = self.make_item("first")
        second = self.make_item("second")
        inserted = self.make_item("inserted")
        batch = CaptionBatch(
            default_take_count=4,
            items=[first, second],
        )
        original_ids = {
            "first": first.item_id,
            "second": second.item_id,
            "inserted": inserted.item_id,
        }

        batch.insert_item(1, inserted)
        batch.move_item(first.item_id, 2)

        self.assertEqual(
            [item.caption for item in batch.items],
            ["inserted", "second", "first"],
        )
        self.assertEqual(first.item_id, original_ids["first"])
        self.assertEqual(second.item_id, original_ids["second"])
        self.assertEqual(inserted.item_id, original_ids["inserted"])

    def test_remove_item_targets_stable_identity_and_preserves_remaining_order(self):
        first = self.make_item("first", item_id="first-id")
        second = self.make_item("second", item_id="second-id")
        third = self.make_item("third", item_id="third-id")
        batch = CaptionBatch(default_take_count=4, items=[first, second, third])

        removed = batch.remove_item("second-id")

        self.assertIs(removed, second)
        self.assertEqual(batch.items, (first, third))
        with self.assertRaises(KeyError):
            batch.get_item("second-id")

    def test_effective_take_count_uses_batch_default_and_optional_override(self):
        defaulted = self.make_item("default")
        overridden = self.make_item("override", take_count_override=2)
        batch = CaptionBatch(
            default_take_count=5,
            items=[defaulted, overridden],
        )

        self.assertEqual(batch.effective_take_count(defaulted), 5)
        self.assertEqual(batch.effective_take_count(overridden), 2)

        batch.default_take_count = 7
        self.assertEqual(batch.effective_take_count(defaulted), 7)
        self.assertEqual(batch.effective_take_count(overridden), 2)

        overridden.take_count_override = None
        self.assertEqual(batch.effective_take_count(overridden), 7)

    def test_acceptance_state_tracks_stable_item_identity_across_reordering(self):
        first = self.make_item("first", item_id="first-id")
        second = self.make_item("second", item_id="second-id")
        batch = CaptionBatch(default_take_count=4, items=[first, second])

        marked = batch.mark_accepted("second-id", 2)
        batch.move_item("second-id", 0)

        self.assertIs(marked, second)
        self.assertTrue(second.is_accepted)
        self.assertEqual(second.accepted_take_number, 2)
        self.assertEqual(batch.accepted_items, (second,))
        self.assertFalse(first.is_accepted)

        cleared = batch.clear_acceptance("second-id")
        self.assertIs(cleared, second)
        self.assertFalse(second.is_accepted)
        self.assertIsNone(second.accepted_take_number)
        self.assertEqual(batch.accepted_items, ())

    def test_nullable_take_override_survives_ordinary_session_edits(self):
        item = self.make_item("before")
        batch = CaptionBatch(default_take_count=6, items=[item])

        item.session.replace_caption("after")
        item.session.replace_pronunciation("edited pronunciation")
        item.session.replace_settings({"style_id": 1, "speed": 1.2})

        self.assertIsNone(item.take_count_override)
        self.assertEqual(batch.effective_take_count(item), 6)

        item.take_count_override = 3
        item.session.replace_caption("after again")
        item.session.replace_pronunciation("edited again")
        item.session.replace_settings({"style_id": 3, "speed": 0.9})

        self.assertEqual(item.take_count_override, 3)
        self.assertEqual(batch.effective_take_count(item), 3)

    def test_inclusion_toggles_by_stable_identity_not_list_position(self):
        first = self.make_item("first")
        second = self.make_item("second")
        third = self.make_item("third")
        batch = CaptionBatch(
            default_take_count=4,
            items=[first, second, third],
        )

        batch.set_included(second.item_id, False)
        batch.move_item(second.item_id, 0)

        self.assertFalse(batch.items[0].included_for_generation)
        self.assertTrue(first.included_for_generation)
        self.assertTrue(third.included_for_generation)

        toggled = batch.toggle_included(second.item_id)
        self.assertIs(toggled, second)
        self.assertTrue(second.included_for_generation)
        self.assertEqual(batch.included_items, batch.items)

    def test_caption_pronunciation_and_settings_edits_preserve_inclusion(self):
        item = self.make_item("before")
        batch = CaptionBatch(default_take_count=4, items=[item])
        batch.set_included(item.item_id, False)

        item.session.replace_caption("after")
        item.session.replace_pronunciation("new pronunciation")
        item.session.replace_settings({"style_id": 1, "speed": 1.4})

        self.assertEqual(item.caption, "after")
        self.assertFalse(item.included_for_generation)

    def test_existing_single_utterance_session_object_is_reused_per_item(self):
        session = FakeSession("caption")
        item = CaptionBatchItem(session)
        batch = CaptionBatch(default_take_count=4, items=[item])

        self.assertIs(item.session, session)
        self.assertIs(batch.items[0].session, session)

    def test_batch_state_requires_no_tui_or_curses_objects(self):
        sessions = []

        def factory(caption):
            session = FakeSession(caption)
            sessions.append(session)
            return session

        batch = CaptionBatch(default_take_count=4)
        batch.add_captions_from_text(
            "one\ntwo",
            session_factory=factory,
        )

        self.assertEqual(
            [item.session for item in batch.items],
            sessions,
        )

    def test_duplicate_item_id_is_rejected(self):
        first = self.make_item("first", item_id="stable-id")
        duplicate = self.make_item("second", item_id="stable-id")
        batch = CaptionBatch(default_take_count=4, items=[first])

        with self.assertRaisesRegex(ValueError, "duplicate item_id"):
            batch.add_item(duplicate)

        self.assertEqual(batch.items, (first,))

    def test_failed_multiline_session_creation_is_atomic(self):
        existing = self.make_item("existing")
        batch = CaptionBatch(default_take_count=4, items=[existing])

        def factory(caption):
            if caption == "bad":
                raise RuntimeError("cannot build session")
            return FakeSession(caption)

        with self.assertRaisesRegex(RuntimeError, "cannot build session"):
            batch.add_captions_from_text(
                "good\nbad\nlater",
                session_factory=factory,
            )

        self.assertEqual(batch.items, (existing,))


if __name__ == "__main__":
    unittest.main()
