# TUI UI Guidelines

This document defines reusable interaction and presentation conventions for the keyboard-first TUI. Feature-specific behavior remains owned by the relevant focused TUI module.

## Adjustable values

Angle brackets are an interaction promise.

A row rendered as:

```text
Label        < Value >
```

must allow the focused value to be changed with Left / Right.

Do not use `< >` for a read-only status, an action that only opens another screen, or any value that does not respond to Left / Right.

Not every adjustable value must use angle brackets when another established visualization better communicates the interaction, but every angle-bracket value must be Left / Right adjustable.

## Left / Right semantics

When a focused row exposes an ordered set of values:

- Left selects the previous value.
- Right selects the next value.
- Cyclic values may wrap at the ends when that behavior is intentional and tested.

For binary enabled state:

- Left means Off.
- Right means On.

If enabling a control requires missing configuration, Right should open the focused editor needed to supply that configuration instead of enabling an ineffective empty state.

## Enter semantics

Enter activates the focused row's primary detailed interaction.

For an adjustable row with a useful direct chooser or editor, Enter should open that chooser or editor rather than silently behaving like Right.

Examples:

- Dictionary Sort: Left / Right steps through sort modes; Enter opens the sort chooser.
- Dictionary Filter: Left / Right changes Off / On; Enter opens the filter editor.

## Visible shortcuts

Visible shortcuts remain accelerators for frequent operations.

A shortcut may intentionally provide a faster action than Enter on the same hybrid row when the distinction is useful and explicit. This behavior must be covered by focused interaction tests.

Example:

- `S` cycles Dictionary Sort immediately.
- Enter on the focused Sort row opens the complete sort chooser.

Shortcut declarations, labels, selectable order, and conditions remain owned by `tui_shortcuts.py`.

## Preserving configuration while disabled

A reversible On / Off control should keep its configured value when disabled unless Clear or Reset explicitly removes it.

For Dictionary Filter:

- Off disables filtering but retains the query and other filter criteria.
- Right re-enables the retained criteria.
- Enter opens the editor with the retained criteria.
- Clear removes the criteria and leaves filtering Off.

## Navigation

Screens that present entries followed by actions should keep one vertical Up / Down navigation list unless a feature has a stronger interaction reason to do otherwise.

Changing an adjustable value must keep focus on that adjustable row. Recomputed collections must retain stable item identity separately from the currently focused action row so later Edit / Delete actions cannot be retargeted by display-index changes.

## Ownership

- Interaction state and key behavior belong to the focused TUI owner, such as `tui_dictionary.py`.
- Declarative row and shortcut metadata belong to `tui_shortcuts.py`.
- Rendering consumes state and metadata; it must not reimplement business semantics.
- Shared reusable sorting/filtering semantics belong outside rendering and should have one state owner.
