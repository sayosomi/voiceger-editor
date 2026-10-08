# 設定

Voiceger Editor では、音声のスタイルや生成する Take 数、保存形式などを設定できます。

`BATCH LIST` または `BATCH ITEM` で `[S] Settings` を実行すると、`EDIT SETTINGS` が開きます。

## 設定画面

```text
EDIT SETTINGS

Voice
▶ [S] Style *         < Neutral >
  [V] Speed *         < 1.00 >

Generation
  [N] Takes           < 4 >

Output
  [F] Output          ~/.voiceger-editor/output
  [O] File format & naming

Sampling
  [K] Top K *         < 20 >
  [P] Top P *         < 1.00 >
  [T] Temperature *   < 1.00 >
  [D] Reset sampling to Voiceger defaults

Actions
  [A] Apply and save
  [R] Reset
  [Esc] Back

* Applying this setting clears existing candidates.
```

Up / Down で項目を選択し、Left / Right で値を変更できます。

数値やパスを直接入力できる項目では、Enter で編集を開始します。

設定を保存するには `[A] Apply and save` を実行します。

**Esc で戻るだけでは、変更は保存されません。**

`[R] Reset` は、設定画面を開いたときの値に戻す操作です。初期設定に戻す操作ではありません。

項目名に `*` が付いている設定を変更して適用すると、生成済みの Take 候補がクリアされます。

## Style

音声生成に使用する Voiceger のスタイルを選びます。

| スタイル       | 日本語名 | ID |
| ---------- | ---- | -: |
| Sweet      | あまあま |  1 |
| Neutral    | ノーマル |  3 |
| Sexy       | セクシー |  5 |
| Snippy     | ツンツン |  7 |
| Whispering | ささやき | 22 |
| Murmuring  | ヒソヒソ | 38 |
| Exhausted  | へろへろ | 75 |
| Sobbing    | なみだめ | 76 |

初期値は **Neutral（3）** です。

選択できるのは、Voiceger 本体に対応する参照音声ファイルがあるスタイルだけです。

## Speed

音声の話速を設定します。

初期値は `1.00` です。

値を大きくすると速く、小さくすると遅くなります。設定できる値は0より大きい数です。

## Takes

一度に生成する Take の数を設定します。

初期値は `4` で、1〜100の範囲で指定できます。

Take 数を変更しても、すでに生成されている Take の音声は変わりません。

## Output

音声などのファイルを保存するフォルダです。

初期値は次のとおりです。

```text
~/.voiceger-editor/output
```

`[F] Output` で保存先を編集できます。

この Output フォルダは、採用した Take の保存、バッチファイルの書き出し、辞書のエクスポートなどで共通して使用されます。

## 音声生成のランダム性

`Sampling` には、音声生成時の候補の選び方を調整する設定があります。

| 設定          |  初期値 |        範囲 |
| ----------- | ---: | --------: |
| Top K       |   20 |     1〜100 |
| Top P       | 1.00 | 0.00〜1.00 |
| Temperature | 1.00 | 0.00〜1.00 |

### Top K

次に生成する候補を、確率の高いものから最大何個まで考慮するかを指定します。

値を小さくすると選択肢が絞られ、大きくすると選択肢が増えます。

### Top P

候補の累積確率に基づいて、選択範囲を調整します。

小さい値ほど選択肢が絞られます。

`1.00` では、累積確率による追加の絞り込みは行われません。

### Temperature

確率の高い候補をどの程度優先するかを調整します。

小さい値ほど確率の高い候補が選ばれやすくなります。

大きい値では、生成結果に変化が出やすくなります。

これらは音量や話速、感情の強さを直接指定するものではありません。

特に調整する理由がなければ、初期値のままで問題ありません。

### Sampling の設定を戻す

`[D] Reset sampling to Voiceger defaults` を実行すると、Top K・Top P・Temperature の3項目だけを初期値に戻せます。

変更を保存するには、続けて `[A] Apply and save` を実行してください。

## 音声の保存形式とファイル名

`EDIT SETTINGS` の `[O] File format & naming` を実行すると、`AUDIO OUTPUT` が開きます。

```text
AUDIO OUTPUT

  Format             < WAV >
  Encoding           < Source >

  Filename template  {YYYYMMDDHHmm}_{text}

Preview
  202610081815_Sample text.wav

Sidecars
▶ [X] TXT            < ON >
  [L] LAB            < OFF >

Tokens: YYYY MM DD HH mm ss · {text} {style}
  [Esc] Back
```

この画面では、音声形式、ファイル名、TXT・LAB ファイルの出力を設定できます。

変更内容は `EDIT SETTINGS` と共通の編集中設定に保持されます。

**`AUDIO OUTPUT` から戻ったあと、`[A] Apply and save` で保存してください。**

### Format と Encoding

採用した Take の保存形式を選択できます。

| Format | Encoding                                        |
| ------ | ----------------------------------------------- |
| WAV    | Source / PCM 16-bit / PCM 24-bit / Float 32-bit |
| FLAC   | PCM 16-bit / PCM 24-bit                         |
| MP3    | 96〜320 kbps                                     |

初期設定は **WAV / Source** です。

`Source` では、生成した WAV 音声を不要な再エンコードを行わずに保存します。

MP3 を利用するには、別途 `ffmpeg` が必要です。利用できない環境では、MP3 は選択肢に表示されません。

音声形式の変換は Take を採用するときに行われます。生成候補や Preview の音声は WAV のままです。

### Filename template

保存するファイル名の形式を変更できます。

初期値は次のとおりです。

```text
{YYYYMMDDHHmm}_{text}
```

この設定では、日時と Caption の文章を組み合わせたファイル名になります。

たとえば、次のように保存されます。

```text
202610081815_今日は雨なのだ。.wav
```

使用できる変数は次のとおりです。

| 変数        | 内容          |
| --------- | ----------- |
| `YYYY`    | 年           |
| `MM`      | 月           |
| `DD`      | 日           |
| `HH`      | 時           |
| `mm`      | 分           |
| `ss`      | 秒           |
| `{text}`  | Caption の文章 |
| `{style}` | スタイル名       |

`MM` は月、`mm` は分です。大文字と小文字を区別します。

ファイルの拡張子は Format によって自動的に決まるため、テンプレートに含める必要はありません。

`Preview` には、現在のテンプレートで生成されるファイル名の例が表示されます。

### TXT

TXT を `ON` にすると、Take を採用したときに、音声ファイルと同じ名前の `.txt` ファイルも保存されます。

TXT ファイルには、元の Caption の文章が記録されます。

```text
202610081815_今日は雨なのだ。.wav
202610081815_今日は雨なのだ。.txt
```

### LAB

LAB を `ON` にすると、Take を採用したときに `.lab` ファイルの生成も試みます。

LAB は音素ごとの時間情報を記録するファイルです。

生成には追加のソフトウェアや条件が必要です。詳しくは [LAB 出力](lab-output.md) を参照してください。

## 設定ファイル

設定は `config.json` に保存されます。

標準の保存先は次のとおりです。

| OS      | 設定ファイル                                                      |
| ------- | ----------------------------------------------------------- |
| macOS   | `~/Library/Application Support/voiceger-editor/config.json` |
| Windows | `%APPDATA%\voiceger-editor\config.json`                     |
| Linux   | `~/.config/voiceger-editor/config.json`                     |

Windows で `APPDATA` が設定されていない場合や、Linux で `XDG_CONFIG_HOME` が設定されている場合は、保存先が異なります。

## コマンドラインで設定を変更する

一部の設定は、起動時のオプションでも指定できます。

```text
voiceger-editor --take-count 8 --style 1 --speed 0.95
```

この例では、Take 数を8、Style を Sweet、Speed を0.95にして起動します。

コマンドラインで指定した値は、その起動中だけ適用されます。TUI で変更して保存しない限り、保存済み設定は書き換わりません。

## 関連ページ

- [BATCH LIST](batch-list.md)
- [BATCH ITEM](batch-item.md)
- [LAB 出力](lab-output.md)
- [ユーザー辞書](dictionary.md)
