# TUI

Voiceger Editor provides a keyboard-first terminal interface.

The normal workflow is:

```text
Caption
→ check or edit pronunciation
→ Generate
→ listen to Takes
→ accept one Take
```

## Basic controls

- Up / Down — move between rows.
- Enter — open or activate the selected row.
- Left / Right — adjust supported values.
- Tab / Shift+Tab — move between major sections where available.
- Space — replay the selected Take.
- Esc — go back, stop playback, or request batch cancellation when available.
- `?` — Help.
- `q` — Quit.

## Caption

Start Voiceger Editor with an empty Caption:

```bash
voiceger-editor
```

or provide the first Caption on the command line:

```bash
voiceger-editor "今日は雨なのだ。"
```

Mixed Japanese-English text is also supported:

```text
このずんだ餅はvery sweetなのだ。
```

## Pronunciation

After building pronunciation, the main screen shows editable Japanese and English sections.

### Japanese rows

Left and Right move the accent by one mora.

Press Enter for the Japanese pronunciation editor.

The editor lets you:

- edit the reading;
- preview the draft;
- apply it;
- save it to the dictionary;
- edit the section text.

### English rows

English pronunciation is edited as word groups.

Left and Right move primary stress when possible.

Press Enter to edit ARPAbet phonemes directly.

See [Pronunciation](pronunciation.md).

## Preview

Preview generates temporary audio from the current draft.

Preview does not apply the draft to the whole utterance and does not create the normal Take batch.

## Sections

A mixed Caption can contain Japanese and English sections.

Use Add section to add another section.

Choose the section language with Left or Right, then enter its text.

A section can also be edited or deleted from its editor.

## Build pronunciation

`b` opens Build pronunciation.

Rebuilding pronunciation replaces manual pronunciation edits, so Voiceger Editor asks for confirmation when needed.

Existing Takes are cleared because they no longer match the new pronunciation state.

## Generate Takes

Select Generate and press Enter, or press:

```text
g
```

The default Take count is `4`.

You can change the Take count in Settings. The supported range is `1` through `100`.

If Takes already exist, Generate regenerates the complete candidate set.

## Cancel generation

During an initial batch or Regenerate all operation, press Esc to request cancellation.

Cancellation happens at a Take boundary. It does not interrupt a Voiceger synthesis call in the middle of one Take.

## Listen to Takes

Moving the selection onto a Take plays it automatically.

Press Space to replay the selected Take.

Number keys `1` through `9` can jump to a visible candidate and play it.

## Accept a Take

Select a Take and press Enter.

The accepted Take is saved as WAV.

If TXT or LAB output is enabled, the corresponding sidecar is also created when possible.

After acceptance, the temporary candidate batch is cleared.

## Regenerate one Take

When a Take is selected and single-Take regeneration is available, press:

```text
r
```

Only the selected candidate is replaced.

## Clear candidates

Press:

```text
c
```

and confirm to clear generated candidates without accepting one.

Candidates cannot be cleared while synthesis is actively running.

## Changes that clear Takes

Existing Takes are cleared when a synthesis-affecting setting changes.

Examples include:

- Japanese pronunciation or accent;
- English phonemes or stress;
- section text;
- rebuilt pronunciation;
- Style;
- Speed;
- Top K;
- Top P;
- Temperature.

This prevents an old Take from being mistaken for audio generated from the current state.

## Main shortcuts

| Key | Action |
| --- | --- |
| `b` | Build pronunciation |
| `a` | Add section |
| `g` | Generate / regenerate all |
| `c` | Clear candidates |
| `s` | Settings |
| `d` | Dictionary |
| `?` | Help |
| `q` | Quit |

Settings also provides quick focus keys such as `v` for Speed, `n` for Takes, `o` for Output, `x` for TXT, and `l` for LAB.

## Quit

If synthesis is running, Voiceger Editor completes the currently active safe operation and requests cancellation of a cancellable batch at the next Take boundary.
