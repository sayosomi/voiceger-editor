# User Dictionary

Voiceger Editor has separate Japanese and English user dictionaries.

Open Dictionary from Batch List or Batch Item, or save directly from a pronunciation editor.

## Open the dictionary

From Batch List or Batch Item, select Dictionary or press:

```text
d
```

Choose:

- Japanese;
- English;
- Import dictionary;
- Export dictionary.

The Japanese and English dictionary lists share the numbered-list navigation used
elsewhere in the TUI. Keys `1` through `9` open the matching visible word
directly. With 10 or more visible words, `0` opens explicit number entry; type
the target number and press Enter.

On a focused word row in either language, press `Space` or `P` to Preview
without opening its editor. The `[P] Preview` action also appears in the list.
Preview uses the currently displayed pronunciation, even before an auto-save
completes.

In the Japanese list, Left / Right moves a **single-accent** word's accent
one mora at a time without wrapping. For **multi-peak** words, Left / Right
does nothing: edit the complete sequence in the detailed pronunciation editor.
Multi-peak words display the compact `[` (rise) / `]` (fall) notation
used during text editing, without extra mora spaces or a peak-count suffix.

In the English list, Left / Right moves the single primary ARPAbet stress
(`1`) to the previous / next vowel, following BATCH ITEM's rule. The
primary-stressed vowel is enclosed in square brackets, as on BATCH ITEM
(for example, `Z [UW1] N D AA0 M OW0 N`). English words with zero or
multiple primary stresses, or fewer than two vowels, are not adjustable.

Changes appear immediately and are automatically saved in the background;
rapid adjustments are combined. Leaving a list or opening an editor waits until
the pending save is complete. A save failure restores the last committed values
and reports an error. Left / Right on Sort and Filter keep their existing
meanings.

Both lists expose `[S] Sort` and `[F] Filter`. Sort can be cycled with the
shortcut or with Left / Right while focused. Japanese sort modes are Surface
ascending/descending, Word type, Priority ascending/descending, and Added
ascending/descending. English sort modes are Surface ascending/descending and
Added ascending/descending.

Japanese Filter can match Surface or Pronunciation and can restrict Word type.
English Filter matches Surface or ARPAbet. Once filter criteria exist, Left /
Right on the Filter row toggles those saved criteria on or off without deleting
them.

## Japanese dictionary

Selecting Add opens a new entry with Surface already in text-editing mode, so
you can start typing immediately without pressing Enter again.

A Japanese entry contains:

- Surface;
- Pronunciation;
- Accent;
- Word type;
- Priority.

### Surface

Surface is the text that should match.

Example:

```text
ずんだもん
```

### Pronunciation and accent

Japanese dictionary pronunciation is stored as katakana within one accent phrase.
A word may have multiple pitch-accent peaks without splitting that phrase.

Generate a pronunciation from Surface, then select the Pronunciation row.
For a single-accent word, Left / Right moves the accent one mora at a time.
For multi-peak words, Left / Right does not modify the reading.

Press Enter on Pronunciation to open **EDIT PRONUNCIATION**, using the
same direct text-editing layout as BATCH ITEM. Edit the string, then select
**Preview** to listen, **Apply** to accept the draft back into the Dictionary
entry, **Clear** or **Reset** as needed, or **Esc** to return without applying.
Save the dictionary word separately in the parent entry.

Single-accent words retain their existing notation (`ア'メ` / `アメ'`)
and behavior. For multiple peaks, use explicit `[` rise and `]` fall
markers, for example `ス[タ]ック[チャ]ン`. Both rise and fall positions
are typed directly: no new notation, special marker-selection shortcut,
or automatic conversion is required. Markers must follow complete morae;
`チャ` is one mora. An optional leading `[` makes an initially high
mora explicit (`[シ]コク[メ]タン` equals `シ]コク[メ]タン`). A trailing
`]` may close a high span continuing through the final mora, for example
`[シ]コク[メタン]`. These edge delimiters are accepted and displayed, but
do not add extra pitch events or phrase boundaries.

Dictionary readings remain a single accent phrase. A slash `/` splits
phrases and is not valid within one dictionary word. Additional pitch
events live in Voiceger Editor metadata, while the first fall stays in the
VOICEVOX-compatible `accent_type`. Preview, Save, and Quick Save preserve
every pitch event, and existing single-accent words are not upgraded
automatically.

Select Preview to listen before saving. New entries default to Priority 5.
Invalid text or failed saves keep a retryable draft. See
[Pronunciation](pronunciation.md) for general phrase separators,
[Compatibility](compatibility.md) for VOICEVOX limitations, and the
export/import instructions below for lossless backups.

### Word type

Supported word types are:

- Proper noun;
- Common noun;
- Verb;
- Adjective;
- Suffix.

New entries default to Proper noun.

### Priority

Priority is from:

```text
0–10
```

The default is:

```text
5
```

For normal use, leaving the default is usually sufficient.

### Save

Select Save to write the entry.

If the same Surface already has matching entries, Voiceger Editor lets you choose which existing entry to update when needed.

## English dictionary

Selecting Add also opens Surface directly in text-editing mode.

An English entry contains:

- Surface;
- ARPAbet pronunciation.

Example:

```text
sweet
S W IY1 T
```

Use Generate pronunciation to create a starting pronunciation.

Then:

- Left / Right moves primary stress when possible;
- Enter edits ARPAbet tokens directly;
- Preview lets you listen before saving.

English dictionary matching ignores letter case.

## Import a dictionary (Merge)

Choose **Import dictionary (Merge)** from the Dictionary menu. Enter the path
to a native ZIP backup or an older JSON dictionary file, then select
**Review file**.

Native ZIP backups include Japanese, English, and optional additional
Japanese pitch events. Both languages are reviewed together. New entries
start selected; conflicts start unselected; exact duplicates are omitted
from the review list and counted. A selected conflict replaces the matching
logical entry without deleting unrelated local words. Review each word with
Enter, toggle its selection using Space, then choose **Import selected**.

Japanese review details show Surface, Pronunciation, Accent, Word type, and
Priority. For Merge, only Japanese Word type is adjustable; changing it
updates conflict detection. English details are read-only. Local words not
selected for replacement remain intact. Changes for both languages and all
selected pitch events are committed as one recoverable operation.

Standalone JSON remains supported:

- Japanese VOICEVOX-style UUID-keyed `UserDictWord` JSON;
- earlier Voiceger Editor Japanese JSON, including the declared three-file
  pitch-metadata backup (select its `user_dict_with_pitch_events` file with
  the matching pitch-events sidecar in the same folder);
- Voiceger Editor English JSON (`{"surface": ["ARPABET", "TOKENS"]}`).

Standalone JSON files still import only their respective language. Their
existing preview, conflict resolution, and commit behavior is unchanged.
The Import path starts at `Settings.output_dir`, but changing an import
file path never changes that setting. Invalid files are rejected before
local dictionary data is changed.

## Export a dictionary

Choose **[O] Export dictionary** (or press O) from the top-level Dictionary screen.
The Export screen shows the current shared output directory as
**[F] Output**. Press F or Enter while the row is selected to change
`Settings.output_dir` in place.

**Voiceger Editor** writes one complete native backup:

    YYYYMMDDHHMM_voiceger_editor_dictionary.zip

The archive contains `manifest.json` (version 1, member names, SHA-256
checksums), unchanged canonical `user_dict.json`, unchanged
`english_user_dict.json`, and optional unchanged
`user_dict_pitch_events.json` for additional Japanese pitch events.
All files are checked as a complete set on import. Damaged, unsupported,
incomplete or unsafe archives are rejected without changing the dictionary.
A completed ZIP is published without overwriting an existing file; a
collision adds `-2`, `-3`, and so on before `.zip`.

**VOICEVOX** writes only the standard Japanese single-accent JSON:

    YYYYMMDDHHMM_voicevox_user_dict.json

VOICEVOX exports never include English words or additional Japanese pitch
events. If additional pitch peaks exist, a warning appears **before**
export; cancellation leaves no export file. Confirming creates the normal
single-accent VOICEVOX JSON. Choose the native ZIP backup to preserve every
pitch event.

Additional Japanese pitch events are stored locally in
`user_dict_pitch_events.json` beside `user_dict.json`. The version-1
pitch sidecar is UUID-keyed, includes reading and mora alignment, and binds
to the exact canonical Japanese dictionary bytes with a SHA-256 checksum.
Neither VOICEVOX JSON nor OpenJTalk CSV contains the extra events.

Native ZIP backups replace the older two- or three-JSON export format,
but already-exported standalone JSON and the three-file native pitch
backup remain importable. They are not complete ZIP backups.

## Save from a pronunciation editor

Japanese and English pronunciation editors include:

```text
Save to dictionary
```

This opens the corresponding dictionary flow with the current pronunciation as the starting value.

## Edit and delete

Select an existing dictionary entry and press Enter to edit it.

Use the Delete action from the list to remove an entry.

Deletion requires confirmation. The confirmation uses the same two-row modal
pattern as other destructive actions: Up/Down selects `[D] Delete` or
`[Esc] Cancel`, Enter activates the selected row, `D` confirms directly,
and Esc cancels directly and returns to the dictionary list.

If you try to leave an entry editor with unsaved changes, Voiceger Editor asks before discarding them.

## Storage

Dictionary files are stored beside the normal Voiceger Editor configuration.

Japanese:

```text
user_dict.json
```

English:

```text
english_user_dict.json
```

On Windows, the default directory is:

```text
%APPDATA%\voiceger-editor\
```

If `APPDATA` is unavailable, the fallback is under:

```text
%USERPROFILE%\AppData\Roaming\voiceger-editor\
```

On macOS:

```text
~/Library/Application Support/voiceger-editor/
```

On Linux and other XDG-style systems, the default is normally:

```text
~/.config/voiceger-editor/
```

If `XDG_CONFIG_HOME` is set on those systems, Voiceger Editor uses it instead.

These are Voiceger Editor files. They are not files inside the Voiceger repository.

See [Settings](settings.md) for configuration paths.

## API dictionary compatibility

The HTTP API exposes the Japanese dictionary through VOICEVOX-compatible dictionary endpoints.

The English dictionary is available through Voiceger Editor-specific HTTP endpoints for listing, creating/replacing, updating, deleting, and importing entries. These endpoints use the same persistent `english_user_dict.json` as the TUI, but are not VOICEVOX-compatible endpoints. API changes are visible to the next `/audio_query` in the same process; changes made by a different already-running process are not automatically reloaded.

See [HTTP API](api.md).
