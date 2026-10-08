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

Japanese dictionary pronunciation is stored as katakana with one accent phrase.

You can generate a pronunciation from the Surface and then edit it.

On the Pronunciation row:

- Left / Right moves the accent;
- Enter edits the reading directly.

Example:

```text
ア'メ
```

and:

```text
アメ'
```

represent different accent positions.

Use Preview to listen before saving.

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

## Import a dictionary

Choose **Import dictionary** from the top-level Dictionary screen, enter the JSON
file path, and open the review.

Supported files are detected from their contents rather than the filename:

- Japanese VOICEVOX user dictionaries using the UUID-keyed expanded
  `UserDictWord` JSON format;
- Japanese dictionaries exported by Voiceger Editor in the same format;
- Voiceger Editor English dictionaries using
  `{"surface": ["ARPABET", "TOKENS"]}`.

Japanese VOICEVOX dictionaries do not need conversion before import.

The review list omits exact duplicates and counts them as already existing.
New entries start selected. Conflicting entries start unselected and are marked
with `!` immediately after the checkbox. Use Space to select or deselect the
focused entry, Enter to inspect its details, **Import selected** to commit the
current selection, or **Clear selection** to deselect all review entries.

Japanese import detail shows Surface, Pronunciation, Accent, Word type, and
Priority. Only Word type can be changed during import review; Left / Right
changes it and immediately recalculates whether that entry is new, conflicting,
or an exact duplicate. Pronunciation, Accent, and Priority are read-only.
English import detail is entirely read-only.

When a selected Japanese conflict replaces an existing logical entry, the
existing UUID and its canonical position are preserved. Newly imported entries
are appended in input-file order. The import is committed as one logical
operation and reports imported, replaced, and skipped counts when complete.

The Import File path starts at the saved Output directory for convenience.
It is an input-only path: changing it does not change `Settings.output_dir`.

Invalid or unsupported input is rejected before the active dictionary is
changed. Back exits the import workflow without committing the review.

## Export a dictionary

Choose **Export dictionary** from the top-level Dictionary screen.

The Export screen shows the shared saved output directory as **[F] Output**.
Select that row and press Enter, or press **F**, to edit
`Settings.output_dir` in place without leaving Export.

**Voiceger Editor** export writes the current dictionaries as two separate
native JSON files:

    YYYYMMDDHHMM_user_dict.json
    YYYYMMDDHHMM_english_user_dict.json

There is no combined bundle format. The Japanese and English files preserve
their canonical dictionary order.

**VOICEVOX** export writes the Japanese dictionary only, using the same
UUID-keyed expanded UserDictWord JSON shape used for Japanese import:

    YYYYMMDDHHMM_voicevox_user_dict.json

The English dictionary is not included in VOICEVOX export.

Exports are written to the current Settings.output_dir, the same configured
output directory used for accepted audio. Existing files are never overwritten.
If a name already exists, Voiceger Editor adds -2, -3, and so on before the
.json extension. A paired Voiceger Editor export always uses the same suffix
for both files.

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
