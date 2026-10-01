# Pronunciation

Voiceger Editor lets you check and edit pronunciation before generating Takes.

Japanese and English use different editing models.

## Japanese pronunciation and pitch accent

Japanese pronunciation uses kana with an apostrophe (`'`) after the accented mora.

Examples:

```text
ア'メ   accent on ア
アメ'   accent on メ
```

This lets you distinguish pronunciations such as:

```text
雨 → ア'メ
飴 → アメ'
```

Small kana belong to the same mora as the preceding kana. For example:

```text
きゃ'
```

is one accented mora.

### Accent phrases

A Japanese utterance can contain several accent phrases.

In the TUI, phrases are displayed with spaces:

```text
キョ'ーワ ア'メデスネ。
```

The VOICEVOX-style API kana form uses `/` between phrases:

```text
キョ'ーワ/ア'メデスネ。
```

Do not type `/` as a phrase separator in the normal TUI pronunciation editor.

### Move the accent

On a Japanese pronunciation row, Left and Right move the accent by one mora.

Press Enter for detailed editing.

The Japanese editor can also:

- edit the reading directly;
- preview the current draft;
- apply the draft;
- save the pronunciation to the user dictionary;
- edit the section text.

Preview does not apply the draft to the full utterance.

Applying a pronunciation change clears existing Takes because they were generated from older pronunciation state.

## English pronunciation and stress

English pronunciation uses ARPAbet-style phonemes.

Example:

```text
very → V EH1 R IY0
```

Stress-bearing vowels use a digit:

- `0` — no lexical stress;
- `1` — primary stress;
- `2` — secondary stress.

Consonants do not use stress digits.

### Move primary stress

On an English word row, Left and Right move the primary stress between available vowels.

For example:

```text
V EH1 R IY0
→
V EH0 R IY1
```

Press Enter to edit the phoneme sequence directly.

Example:

```text
S W IY1 T
```

Unsupported phoneme tokens are rejected.

## Mixed Japanese-English text

Japanese and English sections can appear in the same Caption.

Example:

```text
このずんだ餅はvery sweetなのだ。
```

Japanese sections keep editable Japanese accent information.

English sections keep editable ARPAbet pronunciation and stress.

## Save a pronunciation

Both Japanese and English pronunciation editors can save the current pronunciation to the user dictionary.

See [User Dictionary](dictionary.md).
