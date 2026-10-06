# TUI UI Guidelines

This document is the canonical owner of interaction and presentation conventions shared across the keyboard-first TUI.

Keep this document limited to durable cross-screen UI rules. Feature-specific behavior, screen-specific menu order, and exact feature semantics belong in the feature owner, its Issue contract, and focused tests. Implementation ownership and module boundaries belong in [TUI Architecture](./tui-architecture.md).

## Navigation

Up / Down moves focus to the previous / next selectable item.

Screens that present entries followed by actions should use one vertical Up / Down navigation list unless a stronger interaction requirement justifies another structure. Selectable order should follow the visible order.

Initial focus should normally represent the screen's primary purpose and Enter on that initial row should perform a meaningful action rather than a no-op. Do not move initial focus to a secondary status or navigation control merely because it is visually first.

Destructive or replacement confirmation screens should initially focus Cancel. The explicit destructive shortcut remains available for users who intend to confirm immediately.

An adjustment or action that does not leave the current screen should normally keep focus on the row that was operated.

## Adjustable values

Angle brackets are an interaction promise.

A row rendered as:

```text
Label        < Value >
```

must allow the focused value to be changed with Left / Right.

Do not use `< >` for a read-only status, a row that only opens another screen, or a state where Left / Right currently has no meaningful effect. If a value is not currently adjustable, render it without angle brackets.

When a Left / Right key press actually changes an angle-bracket value, the next render should temporarily double the arrow on the pressed side:

```text
<<Value >
< Value>>
```

Do not show the doubled arrow when the value did not change, including at a bounded endpoint or when the control is not currently adjustable. Equivalent shortcuts such as a dedicated cycle key do not use this Left / Right press feedback.

Angle-bracket position navigators, such as the current Batch Item or Dictionary entry position, follow the same feedback rule when they are adjusted with Left / Right.

## Left / Right semantics

When a focused row exposes an ordered set of values:

- Left selects the previous value.
- Right selects the next value.

Values with a meaningful lower / upper bound, positional end, or directional order must not wrap. At an endpoint, further movement toward that endpoint leaves the value unchanged. This includes bounded numeric values, positions, and ordered levels where jumping from the maximum back to the minimum would change the meaning of the scale.

Categorical values with no meaningful minimum / maximum may wrap when cyclic navigation is intentional and tested.

A two-state toggle is explicitly cyclic and may therefore toggle in either direction.

Changing an adjustable value should keep focus on that row.

## Enter and editing

Enter activates the focused row's primary interaction.

For an editable field, Enter starts editing when the field is focused and normally finishes editing while text entry is active.

While text entry is active, printable shortcut letters are input text rather than menu shortcuts.

For a row that supports both direct Left / Right adjustment and a detailed chooser or editor, Enter should open the detailed interaction rather than silently behaving like Right.

Feature-specific multiline input keys or other editing exceptions belong with that feature unless they become a shared convention.

## File and output paths

Editable filesystem path rows use `[F]` as the shared direct shortcut.

`Output` always means the shared `Settings.output_dir`. Screens that expose Output display that same current directory. Outside the Settings screen, `F` edits and saves that shared setting in place without navigating to Settings. Inside Settings, `F` starts editing the same field, while the normal Apply action remains the persistence boundary for the Settings draft.

Input-only `File path` fields, such as Read Batch and Import Dictionary, are temporary operation values rather than settings. They may initialize from the saved Output directory, but editing them must not change `Settings.output_dir`.

Pressing `F` from the containing screen starts editing the relevant path immediately rather than only moving focus to the row. Enter on a focused path row also starts editing.

A dedicated input-path screen may start with its File path already in editing mode when entering that screen is itself an explicit request to provide a path.

While path text entry is active, `f` is input text rather than a shortcut, consistent with the general editing rule above.

## Visible shortcuts

Visible shortcuts are accelerators for frequent operations.

Ordinary visible actions should have a direct shortcut unless there is an explicit reason not to provide one. Render ordinary shortcut labels as:

```text
[X] Action
```

The displayed shortcut and the actual key behavior must agree.

When a visible shortcut/action label must wrap and the complete label fits on one line, keep the shortcut and action together rather than splitting inside the shortcut token. For example, `[Ctrl+C] Cancel generation` should move as a unit to the next line instead of breaking `[Ctrl+C]` across rows.

A shortcut may intentionally provide a faster action than Enter on the same row when that distinction is useful and explicit. Such differences must be deliberate and covered by focused interaction tests.

## Escape actions

Esc is the standard one-level-back or cancel key for editor and modal navigation.

Rows whose direct key is Esc must show that key explicitly:

```text
[Esc] Back
[Esc] Cancel
```

Do not render a selectable Back or Cancel row without the `[Esc]` hint.

Background work must not steal Esc from the current screen's normal one-level-back or local cancel behavior. In particular, leaving a Batch Item while Take generation is active returns to the Batch List and leaves that generation running.

During cancellable Take generation, Ctrl+C requests cooperative cancellation at a safe Take boundary. Ctrl+C does not quit while that generation is active. After the generation completes, the cancellation guard remains armed until the next non-Ctrl+C user interaction so a completion race cannot turn an intended cancellation into a quit. Repeated Ctrl+C while that guard is armed is harmless. The explicit `q` action remains Quit.

## Confirmation screens

Two-choice confirmation screens should use one ordered vertical action list backed by the declarative menu metadata.

- Up / Down moves between confirmation actions without wrapping.
- Enter activates the focused action.
- A visible direct action shortcut activates that action immediately.
- When cancellation is available, Esc activates Cancel and the visible cancel row is labeled `[Esc] Cancel`.

The shared confirmation shell may own these interaction and presentation mechanics. Feature owners retain what is being confirmed, feature-specific payload/state, action execution, dirty-state rules, asynchronous behavior, and success/failure Status text.

## Feedback for long-running work

An action that may take perceptible time must provide visible feedback promptly enough that the TUI does not appear frozen.

Foreground work that blocks the current interaction may use Status for its in-progress feedback.

Background work that remains active while the user can continue other interactions must keep its operation progress separate from ordinary semantic Status. The background indicator and Status may share the footer area, but their lifecycles are independent:

```text
background operation progress
Status: result of the user's most recent relevant interaction
```

Progress updates must not overwrite a Status message that explains why a user action succeeded, failed, or was blocked. Conversely, an unrelated Status update must not hide an active background operation. When no background operation exists, do not reserve a permanent extra row for it.

Completion, failure, and cancellation may replace the transient Status with the operation outcome while clearing the background indicator.

Exact Status wording and feature-specific progress semantics belong with the feature or operation owner rather than in this document.

## Reversible state

Disabling a reversible control should preserve its configured value unless an explicit Clear or Reset action removes it.

## Maintenance

Any Task that changes TUI-visible presentation, navigation, focus behavior, key interaction, editor or modal interaction, or Status behavior must read this document before settling the implementation contract.

When a change introduces a new reusable cross-screen convention, or changes an existing one, update this document in the same change.

Do not add a rule here merely because one screen behaves a certain way. Keep screen-specific behavior in its feature owner, Issue contract, and focused tests.

Exceptions to a shared rule should be intentional, narrow, and tested. If the same exception starts recurring across screens, revisit the shared rule instead of accumulating screen-specific exceptions here.
