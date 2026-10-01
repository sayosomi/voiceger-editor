# TUI

Voiceger Editor provides a keyboard-first terminal interface.

## Workflow

The normal workflow is:

~~~text
Caption
→ build/check pronunciation
→ Generate
→ listen to Takes
→ accept one Take
~~~

Start with:

~~~bash
voiceger-editor
~~~

or:

~~~bash
voiceger-editor "このずんだ餅はvery sweetなのだ。"
~~~

## Navigation

Main navigation uses:

- Up / Down — move between selectable rows.
- Enter — activate the selected row.
- Left / Right — adjust a value when the row supports it.
- Tab / Shift+Tab — move between major sections.
- Esc — go back, stop playback, or request batch cancellation when available.
- ? — Help.
- q — Quit.

The main screen also has direct shortcuts:

- b — Build pronunciation.
- a — Add section.
- g — Generate or regenerate all Takes.
- c — Clear candidates.
- s — Settings.
- d — Dictionary.

## Caption and sections

Select Caption and press Enter to edit the source text. Apply the edit before returning to the main screen.

Build pronunciation converts the current Caption into editable pronunciation sections. Rebuilding replaces manual pronunciation edits, so Voiceger Editor asks for confirmation when needed.

Japanese and English sections can be edited separately. Add section can append another section to the utterance.

## Japanese pronunciation

A Japanese pronunciation row shows the current reading and accent.

On the main screen, Left / Right moves the accent position by one mora. Press Enter for the detailed editor.

The detailed editor can:

- edit the pronunciation;
- preview the current draft;
- apply it;
- save it to the Japanese dictionary;
- edit the section text.

See [Pronunciation](pronunciation.md).

## English pronunciation

English pronunciation is edited in word groups.

Left / Right moves primary stress between stress-bearing vowels when possible. Press Enter to edit the ARPAbet phonemes directly.

The detailed editor can preview, apply, save to the English dictionary, or edit section text.

## Preview

Preview synthesizes temporary audio from the current draft. It does not apply the draft and does not create the normal Take batch.

## Generate Takes

Select Generate and press Enter, or press g.

The default Take count is 4 and can be changed in Settings. Generation is sequential.

If Takes already exist, Generate regenerates the full set. A selected Take can also be regenerated individually from the candidate controls.

Esc requests cancellation of a running batch. Cancellation occurs at a safe Take boundary rather than interrupting a synthesis call in the middle.

## Listen and accept

Moving focus onto a generated Take plays it automatically. Space can replay the selected Take.

Press Enter on a Take to accept it. The accepted WAV is copied to the configured output directory. TXT and LAB sidecars are also created when those options are enabled.

After acceptance, the temporary candidate set is cleared.

## Clear candidates

Use Clear candidates or press c. Voiceger Editor asks for confirmation.

Candidates cannot be cleared while synthesis is active.

Changes to synthesis-affecting values clear old candidates because those Takes no longer match the current utterance settings. This includes pronunciation, section text, Style, Speed, Top K, Top P, and Temperature.

## Settings, Dictionary, Help

Settings controls reusable synthesis and output values. See [Settings](settings.md).

Dictionary manages Japanese and English reusable pronunciations. See [User Dictionary](dictionary.md).

Help shows the current controls, installed Voiceger Editor version, and documentation link.
