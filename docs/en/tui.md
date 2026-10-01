# TUI

Voiceger Editor provides a keyboard-first terminal interface.

Start it with:

```bash
voiceger-editor
```

Or provide the first Caption:

```bash
voiceger-editor "このずんだ餅はvery sweetなのだ。"
```

## Basic workflow

```text
Caption
→ check or edit pronunciation
→ Generate
→ listen to Takes
→ accept one Take
```

## Main controls

- Up / Down: move through selectable rows.
- Enter: open or activate the selected row.
- Left / Right: adjust a supported value on the selected row.
- Tab / Shift+Tab: move between major areas.
- Space: replay the selected Take.
- Esc: go back, stop playback, or request batch cancellation when available.
- `?`: Help.
- `q`: Quit.

The TUI uses one vertical navigation flow. Editing opens a focused editor instead of changing values accidentally during normal navigation.

## Caption

Select the Caption row and press Enter to edit the source text.

Example:

```text
今日は雨なのだ。
```

Mixed Japanese-English text is also supported:

```text
このずんだ餅はvery sweetなのだ。
```

After changing the Caption, apply the edit before continuing.

## Build pronunciation

`Build pronunciation` rebuilds pronunciation from the current Caption.

Shortcut:

```text
b
```

If manual pronunciation edits already exist, the TUI asks for confirmation before replacing them.

Rebuilding pronunciation clears existing candidate Takes.

## Japanese pronunciation

A Japanese pronunciation row shows the current reading and accent.

- Left / Right moves the accent by one mora.
- Enter opens the Japanese pronunciation editor.

The editor can:

- edit the reading;
- preview the draft;
- apply the draft;
- save the pronunciation to the Japanese dictionary;
- edit the section text.

Preview generates temporary audio from the draft. Preview does not apply the edit and does not create a normal Take batch.

Applying a pronunciation change clears existing candidate Takes.

See [Pronunciation](pronunciation.md).

## English pronunciation

English text is edited by word group.

- Left / Right moves primary stress between stress-bearing vowels when possible.
- Enter opens the ARPAbet editor.

The editor can:

- edit phoneme tokens;
- preview the draft;
- apply the draft;
- save the pronunciation to the English dictionary;
- edit the section text.

See [Pronunciation](pronunciation.md).

## Sections

Mixed text is stored as Japanese and English sections.

Use `Add section` or shortcut:

```text
a
```

In the Add Section editor:

- Left / Right changes the language;
- Enter edits the text;
- Apply adds the section.

Existing section text can also be edited from a pronunciation editor.

## Generate Takes

Select `Generate` and press Enter, or press:

```text
g
```

The default number of Takes is 4.

The Generate row can adjust the Take count with Left / Right.

If Takes already exist, Generate replaces the complete candidate set.

During a multi-Take generation batch, Esc requests cancellation. Cancellation occurs at a safe Take boundary rather than interrupting synthesis in the middle of one Take.

## Listen to Takes

Moving onto a Take selects it for review.

Use:

- Space to replay the selected Take;
- number keys `1` through `9` to jump to a visible candidate;
- `r` to regenerate only the selected Take when that action is available.

Regenerating one Take leaves the other candidates unchanged.

## Accept a Take

Select a Take and press Enter.

The accepted Take is saved as WAV.

If enabled, TXT and LAB sidecars are saved with the same basename.

After acceptance, temporary candidates are cleared and the TUI returns to the pronunciation workflow.

## Clear candidates

Use `Clear candidates` or shortcut:

```text
c
```

The TUI asks for confirmation before deleting the current candidate set.

Candidate clearing is not available while synthesis is actively running.

## Changes that clear Takes

Applying a synthesis-affecting change clears existing candidate Takes.

This includes:

- Japanese pronunciation or accent;
- English phonemes or stress;
- section text;
- rebuilt pronunciation;
- Style;
- Speed;
- Top K;
- Top P;
- Temperature.

Changing the configured Take count does not change the synthesis parameters of Takes that already exist.

## Main shortcuts

| Key | Action |
| --- | --- |
| `b` | Build pronunciation |
| `a` | Add section |
| `g` | Generate / regenerate all Takes |
| `c` | Clear candidates |
| `s` | Settings |
| `d` | Dictionary |
| `?` | Help |
| `q` | Quit |

## Settings and dictionary

Settings contain style, speed, Take count, output, sidecars, and sampling controls.

See [Settings](settings.md).

The Dictionary screen contains separate Japanese and English dictionaries.

See [User Dictionary](dictionary.md).

## Quit

Press `q` from the Main screen to quit.

If synthesis is running, Voiceger Editor performs safe cleanup. A cancellable batch stops at a supported boundary rather than leaving partial application state.
