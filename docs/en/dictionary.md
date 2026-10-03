# User Dictionary

Voiceger Editor has separate Japanese and English user dictionaries.

Use the Dictionary screen from the Main TUI, or save directly from a pronunciation editor.

## Open the dictionary

From the Main screen, select Dictionary or press:

```text
d
```

Choose:

- Japanese;
- English.

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

The English dictionary is currently a Voiceger Editor TUI feature.

See [HTTP API](api.md).
