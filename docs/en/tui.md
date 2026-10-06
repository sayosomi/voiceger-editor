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

Voiceger Editor starts at the top-level `BATCH LIST`.

```text
BATCH LIST
→ Enter a Caption
→ BATCH ITEM n/m
→ check or edit pronunciation
→ Generate
→ listen to Takes
→ accept one Take
```

On `BATCH LIST`, Space toggles whether the focused Caption is selected for
outer batch generation. Left / Right on `Takes` changes the batch default Take
count. Open a Caption to use its visible Batch Item actions, including Caption
deletion. `Generate selected` is the entry point for the sequential multi-Caption
generation workflow; the scheduling behavior is implemented separately from the
navigation layer.

`Add captions` accepts multiple lines at once. Paste a multiline block directly,
or press Ctrl+N to insert a line break manually. Enter finishes text editing;
then activate `Apply`. Each non-empty line becomes one independent Caption in
the same order, while blank-only lines are ignored. The normal editor for an
existing Caption still uses Enter to finish editing and never splits that
Caption into multiple items.

When an individual Caption is still generating in the background, `Add captions`
remains available from BATCH LIST and does not cancel or retarget that generation.
Editing an existing Caption remains unavailable until its synthesis-affecting work
is finished.

## Read and Write batch recipes

The Batch List exposes `[R] Read batch` and `[W] Write batch` for logical
batch recipe files. The recommended suffix is `.voiceger.json`.

Write uses the same saved Output directory used elsewhere in the TUI.
`[F] Output` edits that shared `Settings.output_dir` in place. The recipe
file name defaults to `batch.voiceger.json` and is edited separately; Write
always resolves that file name under the current Output directory.

Read accepts a temporary filesystem path, including paths that begin with
`~`. Its initial File path is the saved Output directory, ready for a file
name to be entered, but changing the Read path does not change Output. The
recipe core expands and validates the complete file before the active Batch
List is changed. If the current batch is non-empty, Voiceger Editor asks for
explicit replacement confirmation first. Cancelling the confirmation or
reading an invalid file leaves the current batch unchanged.

The recipe stores the logical batch needed to reconstruct prepared Captions,
including explicit pronunciation/source sections and synthesis settings. A
Caption must therefore have prepared pronunciation before it can be written.

Recipe files are intended to be human-readable working files. For example, you
can Write a `.voiceger.json` file, edit it in VS Code, then Read it back into
the Batch List.

Recipes are not runtime-resume snapshots. Generated candidate Takes, accepted
Take state, playback state, and generation progress are not written and are not
resumed by Read. After Read, the reconstructed Captions are immediately
editable and can generate new Takes.

## Main controls

- Up / Down: move through selectable rows.
- Enter: open the focused Batch List Caption or activate the selected Batch Item row.
- Left / Right: adjust Batch List Takes or a supported Batch Item value.
- Tab / Shift+Tab: move between major areas inside a Batch Item.
- Space: toggle Batch List inclusion, or replay the selected Take inside a Batch Item.
- Esc: go back one level. Active Take generation continues in the background.
- Ctrl+C: cancel active cancellable Take generation; otherwise quit.
- `?`: Help.
- `q`: Quit explicitly, including while generation is active.

The TUI uses one vertical navigation flow. Editing opens a focused editor instead of changing values accidentally during normal navigation.

## Caption

From `BATCH LIST`, select a Caption and press Enter to open its `BATCH ITEM n/m`
screen. Inside the Batch Item, select the Caption row and press Enter, or press
`e` from anywhere on the screen, to edit the source text.

Example:

```text
今日は雨なのだ。
```

Mixed Japanese-English text is also supported:

```text
このずんだ餅はvery sweetなのだ。
```

After changing the Caption, apply the edit before continuing.

Use `[X] Delete caption` from the Batch Item action menu to remove the current
Caption. The confirmation is a normal two-row modal: Up/Down selects
`[D] Delete caption` or `[Esc] Cancel`, Enter activates the selected row,
`D` confirms directly, and Esc cancels directly and returns to the same Batch
Item.

## Build pronunciation

`Build pronunciation` rebuilds pronunciation from the current Caption.

Shortcut:

```text
p
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

During cancellable Take generation, Esc keeps its normal Back meaning. You can return from a generating Batch Item to BATCH LIST and generation continues for that Caption in the background.

While an individual Generate or regenerate-all operation remains active, the originating Caption row in BATCH LIST shows live completed-Take progress as a percentage, including `[0%]` before the first Take completes. When that operation ends, the row returns to the normal candidate-state display.

Voiceger Editor keeps a single synthesis slot and does not queue another Generate request behind active work. When another Batch Item is open during generation, its Generate row remains visible but is marked `[busy]` and does not show the other Caption's progress. BATCH LIST similarly marks `Generate selected` as `[busy]`. Activating either action does not start, replace, or queue work; Status identifies the active Caption or batch generation and tells you to finish or cancel it first. Busy Generate rows omit adjustable angle brackets because the Take count is not currently actionable.

Press Ctrl+C to request generation cancellation. Cancellation occurs at a safe Take boundary rather than interrupting synthesis in the middle of one Take, so any completed Takes are preserved and the application remains open. While cancellation is available, the Status area shows `[Ctrl+C] Cancel generation`.

If generation finishes at the same moment you press Ctrl+C, Voiceger Editor keeps a completion guard so that Ctrl+C does not accidentally quit or discard the finished results. Repeated Ctrl+C remains harmless until another non-Ctrl+C interaction restores the normal idle Ctrl+C Quit meaning. The `q` shortcut remains the explicit Quit action at all times.

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

## Batch List shortcuts

| Key | Action |
| --- | --- |
| Space | Toggle focused Caption `[x] / [ ]` |
| Enter | Open focused Caption |
| Left / Right | Change batch default Takes when `Takes` is focused |
| `a` | Add captions |
| `g` | Generate selected |
| `r` | Read batch recipe |
| `w` | Write batch recipe |
| `s` | Settings |
| `d` | Dictionary |
| `?` | Help |
| `q` | Quit |

## Batch Item shortcuts

| Key | Action |
| --- | --- |
| `f` | Edit Output path |
| `e` | Caption |
| `p` | Build pronunciation |
| `a` | Add section |
| `g` | Generate / regenerate all Takes |
| `c` | Clear candidates |
| `x` | Delete caption (with confirmation) |
| `s` | Settings |
| `d` | Dictionary |
| `?` | Help |
| `q` | Quit |

Press `f` from Batch Item to jump directly into Output path editing.
Other Settings-local shortcuts are available after opening Settings.

## Settings and dictionary

Settings contain style, speed, Take count, output, sidecars, and sampling controls.

See [Settings](settings.md).

The Dictionary screen contains separate Japanese and English dictionaries.

See [User Dictionary](dictionary.md).

## Quit

Press `q` from Batch List or Batch Item to quit.

If synthesis is running, Voiceger Editor performs safe cleanup. A cancellable batch stops at a supported boundary rather than leaving partial application state.
