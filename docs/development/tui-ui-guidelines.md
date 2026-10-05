# TUI UI Guidelines

This document defines interaction and presentation conventions shared across the keyboard-first TUI. Feature-specific behavior belongs in the feature owner, its Issue contract, and focused tests.

## Adjustable values

Angle brackets are an interaction promise.

A row rendered as:

```text
Label        < Value >
```

must allow the focused value to be changed with Left / Right.

Do not use `< >` for a read-only status, a row that only opens another screen, or any state where Left / Right has no meaningful effect.

If a value is not currently adjustable, render it without angle brackets.

## Left / Right semantics

When a focused row exposes an ordered set of values:

- Left selects the previous value.
- Right selects the next value.
- Cyclic values may wrap at the ends when that behavior is intentional and tested.

For a binary adjustable state:

- Left means Off.
- Right means On.

Changing an adjustable value should keep focus on that row.

## Enter semantics

Enter activates the focused row's primary detailed interaction.

For a row that supports both direct adjustment and a detailed chooser or editor, Enter should open the detailed interaction rather than silently behaving like Right.

## Visible shortcuts

Visible shortcuts are accelerators for frequent operations.

A shortcut may intentionally provide a faster action than Enter on the same row when that distinction is useful and explicit. Such differences must be deliberate and covered by focused interaction tests.

Shortcut declarations, labels, selectable order, and conditions remain centralized in the shared shortcut metadata.

## Reversible state

Disabling a reversible control should preserve its configured value unless an explicit Clear or Reset action removes it.

## Escape actions

Rows whose direct key is Esc must show that key explicitly.

Use:

```text
[Esc] Back
[Esc] Cancel
```

Do not render a selectable Back or Cancel row without the `[Esc]` hint. Esc is not treated as an ordinary letter shortcut; the visible hint communicates the direct key for that action.

## Navigation

Screens that present entries followed by actions should keep one vertical Up / Down navigation list unless a stronger interaction requirement justifies another structure.

When a collection is recomputed, retain stable item identity separately from display position so later actions cannot be retargeted by index changes.

## Ownership

- Interaction state and key behavior belong to the focused feature owner.
- Declarative row and shortcut metadata belong to the shared shortcut metadata owner.
- Rendering consumes state and metadata; it must not reimplement business semantics.
- Shared semantic state should have one owner rather than parallel UI-specific implementations.
