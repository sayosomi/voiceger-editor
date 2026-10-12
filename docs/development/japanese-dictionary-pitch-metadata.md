# Japanese dictionary pitch-event sidecar (v1)

Issue #273 extends native dictionary persistence. This is **not** a change to
the canonical VOICEVOX expanded `UserDictWord` schema or OpenJTalk CSV.

## Local storage

- Canonical Japanese dictionary: `user_dict.json` (unchanged UUID-keyed JSON).
- Optional adapter-only sidecar: `user_dict_pitch_events.json`.
- A transient recovery journal: `user_dict.pending.json`.

An absent sidecar means no additional pitch events. Sidecar version 1 is UTF-8
JSON; duplicate keys, unknown properties, unknown UUIDs, stale digests, invalid
readings and unaligned events are errors. Extra events are never added to
`accent_type`, `pronunciation`, `mora_count` or the compiled CSV.

Example for one word:

```json
{
  "version": 1,
  "dictionarySha256": "64-character lowercase hex SHA-256 of canonical user_dict.json",
  "entries": {
    "11111111-1111-4111-8111-111111111111": {
      "reading": "スタックチャン",
      "moraCount": 6,
      "events": [
        {"afterMora": 1, "symbol": "["},
        {"afterMora": 2, "symbol": "]"},
        {"afterMora": 4, "symbol": "["},
        {"afterMora": 5, "symbol": "]"}
      ]
    }
  }
}
```

The digest covers the exact bytes output by
`serialize_japanese_dictionary()`, including indentation and final newline.
Every `entries` key is a stable word UUID from the base JSON. `reading`
matches its `pronunciation`; `moraCount` matches its `mora_count`.
Events follow 1-based mora positions, use alternating rise (`[`) and fall
(`]`) markers and must pass `AccentPhrase` validation. A two-event
first-fall-then-rise shape is valid for an initially high word whose final
high span reaches the end. Optional leading `[` and trailing `]` in the
human-readable notation are delimiters, not stored events. The first fall must
equal canonical `accent_type`; further falls live only in the sidecar.
Empty `entries` are represented by **absence** of the sidecar.

## Commit and recovery

Metadata-only changes atomically replace the sidecar; compilation is not
required because the canonical OpenJTalk word is unchanged. When a dictionary
mutation may affect both base and sidecar, the adapter writes a rollback
journal containing the *previous* optional bytes of each file. It then
atomically replaces base and sidecar, and removes the journal only when both
writes succeeded. If any write fails, runtime state and both files revert to
the previous state. On startup, a surviving journal is applied before
dictionary loading (rollback to the prior complete pair). A corrupt journal
or unmatched persistent sidecar is a storage error, never a silent reset.

No runtime Voiceger files or dictionaries are modified by this mechanism.

## Native transfer naming

Without multi-peak words, export remains exactly two separate files:

```text
YYYYMMDDHHMM_user_dict.json
YYYYMMDDHHMM_english_user_dict.json
```

With multi-peak words, native export produces exactly three:

```text
YYYYMMDDHHMM_user_dict_with_pitch_events.json
YYYYMMDDHHMM_english_user_dict.json
YYYYMMDDHHMM_user_dict_pitch_events.json
```

When names already exist, each file gets the *same* `-2`, `-3`, etc.
before `.json`. All group members are reserved before writing; partial
export attempts remove only files reserved by that attempt. The
`user_dict_with_pitch_events` filename explicitly declares that the
matching sidecar must exist, be valid and match the exported canonical JSON.
Import rejects missing or incorrect sidecars before making any changes.
Imported metadata follows the word's stable UUID, or the retained UUID for
a selected logical-identity conflict. All selected word and metadata changes
commit as one dictionary transaction. Native Japanese import remains
review/selection based; English is imported separately as before.

Ordinary VOICEVOX or legacy Voiceger Editor UUID-keyed JSON files continue
to import without a sidecar. Renaming a declared native file to a legacy
filename discards this declaration and is unsupported for lossless transfer;
retain original filenames.

## VOICEVOX export

`YYYYMMDDHHMM_voicevox_user_dict.json` contains **only** the canonical
single-accent dictionary, regardless of sidecar contents. Export results
report affected UUIDs so the TUI can visibly warn that VOICEVOX import
cannot recover the extra peaks. Such an export is not a lossless native
backup; choose Voiceger Editor native export for that purpose.

Priority is independent of pitch metadata. Default priority remains 5.
