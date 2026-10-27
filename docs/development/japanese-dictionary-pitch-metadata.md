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

## Native ZIP backup (#283)

Current Voiceger Editor export writes one complete native backup:

```text
YYYYMMDDHHMM_voiceger_editor_dictionary.zip
```

ZIP members are `manifest.json` (format version 1 and SHA-256 digest for
each listed member), the unchanged canonical Japanese `user_dict.json`,
the unchanged `english_user_dict.json`, and optionally the unchanged
`user_dict_pitch_events.json` when there are extra Japanese pitch events.
The ZIP is written to a temporary file, then collision-safely published as
a completed archive. Names are never overwritten; a duplicate name gains
`-2`, `-3`, etc. before `.zip`. Failed exports leave no misleading
named incomplete archive. Imports validate ZIP structure, safe bounded
size and expansion, member completeness/uniqueness, version, digest,
canonical JSON, and matching pitch metadata before producing a review.

Native **Merge** reviews Japanese/English changes in one combined flow:
new entries are selected, conflicts are opt-in, exact duplicates are
skipped, and local-only entries are retained. There is no destructive
full-replacement restore action. Selected Merge changes update the
canonical Japanese dictionary, English dictionary, and pitch sidecar
as one journaled, recoverable operation.
The `dictionaries.pending.json` journal stores the previous optional
bytes of all three files; startup recovery restores them if an operation
was interrupted. The existing `user_dict.pending.json` journal still
covers ordinary Japanese word+pitch changes.

Legacy native exports remain importable. A two-file export used the
separate `YYYYMMDDHHMM_user_dict.json` and
`YYYYMMDDHHMM_english_user_dict.json` files, imported individually.
When multi-peak words existed, the three-file export used:

```text
YYYYMMDDHHMM_user_dict_with_pitch_events.json
YYYYMMDDHHMM_english_user_dict.json
YYYYMMDDHHMM_user_dict_pitch_events.json
```

Import the declared Japanese `user_dict_with_pitch_events` member
alongside its matching sidecar. Sidecar integrity and reference checks
are unchanged. Standalone VOICEVOX / legacy UUID-keyed Japanese JSON
and Voiceger Editor English JSON continue to be supported. The ZIP
format is native to Voiceger Editor, not a VOICEVOX interchange format.

## VOICEVOX export

`YYYYMMDDHHMM_voicevox_user_dict.json` contains **only** the canonical
single-accent dictionary, regardless of sidecar contents. Export results
report affected UUIDs so the TUI can visibly warn that VOICEVOX import
cannot recover the extra peaks. The TUI warns before export and offers
Cancel. Such an export is not a lossless native backup; choose the Voiceger
Editor ZIP export for that purpose.

Priority is independent of pitch metadata. Default priority remains 5.
