# User Dictionary

Voiceger Editor has separate Japanese and English user dictionaries.

Open Dictionary from the main TUI, choose a language, then add, edit, or delete entries. A pronunciation editor can also save its current pronunciation directly to the dictionary.

## Japanese entries

A Japanese entry contains:

- Surface — the text to match.
- Pronunciation — katakana reading.
- Accent — accent position.
- Word type.
- Priority — 0 through 10.

Supported word types are:

- Proper noun.
- Common noun.
- Verb.
- Adjective.
- Suffix.

New entries default to Proper noun and priority 5.

The pronunciation is one Japanese accent phrase. You can generate a pronunciation from Surface and then edit it.

On the Pronunciation row, Left / Right moves the accent position. Preview lets you hear the entry before saving.

## English entries

An English entry contains a Surface form and ARPAbet pronunciation.

Example:

~~~text
Surface: very
Pronunciation: V EH1 R IY0
~~~

You can generate a starting pronunciation, edit the phonemes, move primary stress, preview it, and save it.

English dictionary matching ignores case.

## Save from the pronunciation editor

When editing a Japanese or English section in the TUI, choose Save to dictionary to reuse the current pronunciation later.

An existing matching entry can be updated.

Unsaved dictionary edits prompt before leaving. Deletion requires confirmation.

## Storage

The dictionaries are stored beside the normal Voiceger Editor settings file:

~~~text
user_dict.json
english_user_dict.json
~~~

These are Voiceger Editor data files. They are not files inside the Voiceger repository.

See [Settings](settings.md) for the platform-specific data location.

## API compatibility

The VOICEVOX-style HTTP dictionary endpoints manage the Japanese dictionary. The English dictionary is currently a Voiceger Editor TUI feature.

See [HTTP API](api.md).
