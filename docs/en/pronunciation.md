# Pronunciation

Voiceger Editor lets you edit pronunciation before generating Takes.

Japanese and English use different editing models.

## Japanese pronunciation

Japanese text is converted to a kana reading with pitch-accent information.

Example:

```text
雨 → ア'メ
飴 → アメ'
```

The apostrophe `'` is placed immediately after the accented mora.

For multi-peak readings, use `[` for a rise and `]` for a fall after a complete mora. To make the high spans easier to see, you can additionally enclose an initially high mora with a leading `[` or a final high span with a trailing `]`. These optional edge brackets do not add sound or pitch events. Examples:

```text
シ]コク[メ]タン      → [シ]コク[メ]タン
[シ]コク[メタン]     → the last high span continues to the end
```

The single-accent `'` notation is unchanged. Multi-peak input is serialized with the optional high-span edge brackets for legibility.

Examples:

```text
ア'メ
アメ'
```

Small kana belong to the same mora as the preceding kana.

For example:

```text
きゃ'
```

is one accented mora.

Both hiragana and katakana are accepted while editing.

Supported punctuation includes:

```text
。 、 ？ ！ …
```

ASCII punctuation such as `.`, `,`, `?`, and `!` is converted to the corresponding Japanese form.

## Accent phrases

A Japanese utterance can contain several accent phrases.

In the TUI, phrases are displayed as a readable sequence separated by spaces.

Example:

```text
キョ'ーワ ア'メデスネ。
```

Legacy phrases have one accent position. A multi-peak phrase can contain several pitch rises and falls **without creating extra accent-phrase boundaries**.

The TUI does not require you to type `/` between phrases.

The VOICEVOX-style API kana form uses `/`:

```text
キョ'ーワ/ア'メデスネ。
```

## Move Japanese accent

On a Batch Item, select a Japanese pronunciation row.

For a **single-accent** phrase, Left / Right moves the accent by one mora. This direct shortcut cannot change a multi-peak phrase: it would discard its other pitch events.

Press Enter for **EDIT PRONUNCIATION**. Its text cursor lets you move, insert, or remove individual `[` (rise) and `]` (fall) pitch markers in a multi-peak phrase. The complete mora must remain intact. The selected Japanese row opens the entire Japanese section so that phrase boundaries and punctuation can be preserved.

In **BATCH ITEM**, the pronunciation rows show complete mora-separated high spans, while the detailed editor shows compact editable text:

| Detailed pronunciation | BATCH ITEM row |
| --- | --- |
| `[シ]コク[メ]タン` | `[シ] コ ク [メ] タ ン` |
| `[シ]コク[メタン]` | `[シ] コ ク [メ タ ン]` |
| `シ'コクメタン` | `[シ] コ ク メ タ ン` |

The leading `[` and final `]` are display delimiters for an initially high or finally high span, not additional pitch events. Spaces **inside the detailed editor** delimit **real accent phrases**, not individual morae. Do not insert spaces to separate internal peaks; `/` belongs to the API notation and is not typed in the detailed editor. In the Batch Item rows, spaces merely separate visual mora tokens.

Use **Preview** to listen to the proposed contour without changing the query, then **Apply** to update it. **Quick Save** can store the edited pronunciation in the Japanese user dictionary for subsequent preparation. Query edits clear existing Takes; unchanged input does not. If you have manually edited the current pronunciation, an automatic **Build pronunciation** requires explicit confirmation before replacing it.

## Preview

The pronunciation editor can preview a draft before you apply it.

Preview:

- synthesizes temporary audio from the draft;
- does not change the active pronunciation;
- does not create a normal Take batch.

Use Apply when you want to keep the edit.

## English pronunciation

English pronunciation uses ARPAbet-style phoneme tokens.

Example:

```text
very → V EH1 R IY0
```

Vowels can have a stress digit:

- `0`: no lexical stress;
- `1`: primary stress;
- `2`: secondary stress.

Consonants do not use stress digits.

## Move English primary stress

On an English word row, Left / Right moves primary stress between available vowels when possible.

For example:

```text
V EH1 R IY0
```

can become:

```text
V EH0 R IY1
```

Press Enter to edit the phoneme sequence directly.

Example:

```text
S W IY1 T
```

Voiceger Editor validates supported phoneme tokens before applying the edit.

## English-only Captions

An English-only Caption is prepared with Voiceger's English G2P and exposes the
same editable ARPAbet word groups used by English sections in mixed text.

Preview, Generate, regeneration, playback, Accept, and the English user dictionary
are supported. Synthesis uses Voiceger's native English mode; Voiceger Editor does
not insert a fake Japanese section just to route synthesis.

## Mixed Japanese-English text

Japanese and English can appear in the same Caption.

Example:

```text
このずんだ餅はvery sweetなのだ。
```

Japanese sections keep editable Japanese pronunciation and accent.

English sections keep editable ARPAbet pronunciation and stress.

## Save pronunciation to the dictionary

Both Japanese and English pronunciation editors can save the current pronunciation to a user dictionary.

See [User Dictionary](dictionary.md).
