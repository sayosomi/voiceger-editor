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

Each phrase has one accent position.

The TUI does not require you to type `/` between phrases.

The VOICEVOX-style API kana form uses `/`:

```text
キョ'ーワ/ア'メデスネ。
```

## Move Japanese accent

On the Main screen, select a Japanese pronunciation row.

Use Left / Right to move the accent by one mora.

Press Enter for detailed editing.

Changing pronunciation or accent does not take effect until the edit is applied.

Applying the change clears existing Takes because they were generated with the previous pronunciation.

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
