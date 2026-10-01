# User Dictionary

Voiceger Editor has separate Japanese and English user dictionaries.

Use the Dictionary screen to add, edit, or delete entries. You can also save a pronunciation directly from a pronunciation editor.

## Japanese dictionary

A Japanese entry contains:

- Surface;
- Pronunciation;
- Accent;
- Word type;
- Priority.

The stored pronunciation is katakana and represents one accent phrase.

### Add an entry

Open Dictionary, choose Japanese, then choose Add.

Enter the Surface text and generate or edit the pronunciation.

On the Pronunciation row:

- Left and Right move the accent;
- Enter edits the reading directly.

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

Priority is from `0` through `10`.

The default is `5`.

Usually, leave the default unless you need to resolve a dictionary matching conflict.

## English dictionary

An English entry maps a spelling to an ARPAbet pronunciation.

Example:

```text
sweet → S W IY1 T
```

On the Pronunciation row:

- Left and Right move primary stress;
- Enter edits ARPAbet directly.

English dictionary matching ignores letter case.

## Save from the pronunciation editor

When you correct a Japanese or English pronunciation, choose Save to dictionary to reuse it later.

If an existing matching entry is found, Voiceger Editor can update that entry instead of creating an unrelated duplicate.

## Unsaved changes and deletion

Leaving an entry with unsaved changes asks for confirmation.

Deleting an entry also requires confirmation.

## Storage

Dictionary files are stored beside the normal settings file:

```text
user_dict.json
english_user_dict.json
```

On macOS, the default directory is:

```text
~/Library/Application Support/voiceger-editor/
```

On systems using `XDG_CONFIG_HOME`, Voiceger Editor uses that config location. Otherwise it uses:

```text
~/.config/voiceger-editor/
```

These are Voiceger Editor dictionary files. They are not files owned by Voiceger itself.

See [Settings](settings.md) for config locations.
