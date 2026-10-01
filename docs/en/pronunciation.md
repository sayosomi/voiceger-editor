# Pronunciation

Voiceger Editor lets you edit pronunciation before generating Takes.

Japanese uses editable reading and pitch accent. English sections use ARPAbet-style phonemes and stress.

## Japanese notation

An apostrophe marks the accent position immediately after the accented mora.

Examples:

~~~text
ア'メ
アメ'
~~~

For the common minimal pair:

~~~text
雨 → ア'メ
飴 → アメ'
~~~

Small kana belong to the same mora as the preceding kana. For example:

~~~text
きゃ'
~~~

is one accented mora.

The TUI displays separate accent phrases with spaces. The VOICEVOX-style API kana form uses / between phrases.

Example TUI form:

~~~text
キョ'ーワ ア'メデスネ。
~~~

Equivalent API-style phrase separation:

~~~text
キョ'ーワ/ア'メデスネ。
~~~

Do not type / as a phrase separator in the normal TUI pronunciation field.

Supported punctuation includes Japanese full stop, comma, question mark, exclamation mark, and ellipsis. Common ASCII punctuation is normalized where supported.

## Move Japanese accent

Select a Japanese pronunciation row on the main screen.

Left / Right moves the accent by one mora.

Press Enter when you need to edit the reading itself or make a more complex change.

Preview lets you hear the draft before Apply. Applying a pronunciation change clears existing Takes because they were generated from older pronunciation state.

## English ARPAbet

English pronunciation is stored as ARPAbet-style phonemes.

Example:

~~~text
very → V EH1 R IY0
sweet → S W IY1 T
~~~

Vowel stress digits are:

- 0 — unstressed.
- 1 — primary stress.
- 2 — secondary stress.

Consonants do not use stress digits.

On an English pronunciation row, Left / Right moves the primary stress between available vowels when possible.

Example:

~~~text
V EH1 R IY0
→
V EH0 R IY1
~~~

Press Enter to edit the phoneme sequence directly. Unsupported tokens are rejected.

## Mixed text

Japanese and English can be used in one Caption:

~~~text
このずんだ餅はvery sweetなのだ。
~~~

Voiceger Editor keeps Japanese accent information and English phonemes separately so both can be edited before synthesis.

## Save reusable pronunciations

A pronunciation can be saved from its editor to the user dictionary.

See [User Dictionary](dictionary.md).
