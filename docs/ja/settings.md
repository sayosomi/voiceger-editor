# 設定

Voiceger Editorでは、音声生成に使用するStyleやSpeed、Take数、保存するファイルの形式などを設定できます。

`BATCH LIST` または `BATCH ITEM` で `S` を押すと、`EDIT SETTINGS` が開きます。

Up / Downで項目を選択し、Left / Rightで値を変更できます。項目によってはEnterで直接入力できます。

変更後は `[A] Apply and save` で保存してください。

`[R] Reset` は、設定画面を開いたときの値に戻す操作です。初期設定に戻す機能ではありません。

## 基本設定

### Style

音声生成に使用するVoicegerのStyleを選択します。

| Style | ID |
|---|---:|
| Sweet | 1 |
| Neutral | 3 |
| Sexy | 5 |
| Snippy | 7 |
| Whispering | 22 |
| Murmuring | 38 |
| Exhausted | 75 |
| Sobbing | 76 |

初期値は `Neutral` です。

Voicegerのインストール先に対応する参照音声が存在するStyleだけを選択できます。

ここで設定したStyleは、各BATCH ITEMで音声を生成するときのデフォルト値になります。

`BATCH ITEM` では、CaptionごとにStyleを個別に変更できます。

### Speed

音声の話速を変更します。

初期値は `1.00` です。

値を大きくすると速く、小さくすると遅くなります。

ここで設定したSpeedは、各BATCH ITEMで音声を生成するときのデフォルト値になります。

`BATCH ITEM` では、CaptionごとにSpeedを個別に変更できます。

### Takes

一度に生成するTake数を設定します。

初期値は `4`、設定できる範囲は `1`〜`100` です。

Take数は`BATCH LIST`からも変更できます。また、`BATCH ITEM`ではCaptionごとに生成するTake数を指定できます。

詳しくは[BATCH LIST](batch-list.md)と[BATCH ITEM](batch-item.md)を参照してください。

### Output

生成した音声などを保存するフォルダを指定します。

初期値は次のとおりです。

```text
~/.voiceger-editor/output
```

OutputはVoiceger Editor全体で共通の設定です。

Takeの保存、バッチファイルの書き出し、辞書のエクスポートには、このフォルダが使用されます。

`BATCH LIST`などの画面からも、`F` キーでOutputを直接編集できます。

一方、バッチファイルや辞書を読み込む際の`File path`は、読み込み対象を指定するための一時的な入力欄です。読み込み元を変更しても、共通のOutput設定は変わりません。

## 音声ファイルの設定

`File format & naming` を選択すると、`AUDIO OUTPUT` が開きます。

ここでは、音声形式、ファイル名、TXT・LABの出力を設定できます。

### 音声形式

次の形式に対応しています。

| 形式 | 選択できる設定 |
|---|---|
| WAV | Source / PCM 16-bit / PCM 24-bit / Float 32-bit |
| FLAC | PCM 16-bit / PCM 24-bit |
| MP3 | 96〜320 kbps |

初期設定は `WAV / Source` です。

`Source` は、生成されたWAVを再エンコードせず、そのまま保存する設定です。

FLACやMP3などへの変換は、Takeを採用して保存するときに行われます。

MP3を使用するには、別途FFmpegが必要です。詳しくは[MP3出力](mp3.md)を参照してください。

### Filename template

保存する音声ファイルの名前を指定できます。

初期値は次のとおりです。

```text
{YYYYMMDDHHmm}_{style}_{caption}
```

使用できる変数は次のとおりです。

| 変数 | 内容 |
|---|---|
| `YYYY` | 年 |
| `MM` | 月 |
| `DD` | 日 |
| `HH` | 時 |
| `mm` | 分 |
| `ss` | 秒 |
| `{style}` | TakeのStyle名 |
| `{caption}` | 採用時点のCaption |

日付と時刻の記号は、`{YYYYMMDDHHmm}` のように波括弧で囲んで使用します。

設定画面には、現在のテンプレートを使ったファイル名のプレビューが表示されます。

ファイルの拡張子は、選択した音声形式に応じて自動的に追加されます。

同じ名前のファイルが存在する場合は、末尾に `-2`、`-3` などを付けて保存します。既存のファイルは上書きされません。

### TXT

有効にすると、採用したTakeの音声ファイルと一緒に、Captionを記録したTXTファイルが保存されます。

TXTには、Takeを採用した時点のCaptionがUTF-8で保存されます。

実際に読み上げた内容がCaptionと異なる場合でも、TXTにはCaptionの文章が使用されます。

Captionと読み上げ内容を分ける方法については、[BATCH ITEM](batch-item.md#セクションとcaptionの違い)を参照してください。

### LAB

有効にすると、採用したTakeの音声ファイルと一緒に、音素の開始・終了時刻を記録したLABファイルの生成を試みます。

LABの生成には追加の依存パッケージや外部ツールが必要です。

対応言語や制限事項、設定方法については[LAB出力](lab.md)を参照してください。

## サンプリング設定

Top K、Top P、Temperatureは、音声生成時のランダム性に関係するパラメータです。

| 設定 | 初期値 | 設定範囲 |
|---|---:|---:|
| Top K | 20 | 1〜100 |
| Top P | 1.00 | 0.00〜1.00 |
| Temperature | 1.00 | 0.00〜1.00 |

これらは音の高さ、話速、音量、感情の強さを直接調整するものではありません。

### Top K

次のトークンを生成するときに、確率の高い候補を最大何個まで考慮するかを指定します。

値を小さくすると候補が絞られ、大きくすると候補の幅が広がります。

### Top P

次のトークンを生成するときに、累積確率に基づいて候補を絞り込みます。

値を小さくすると選ばれる候補が制限され、大きくすると候補の幅が広がります。

`1.00` では、累積確率による追加の絞り込みを行いません。

### Temperature

候補の選ばれ方のランダム性を調整します。

値を小さくすると確率の高い候補が選ばれやすくなり、大きくすると生成結果のばらつきが増えます。

### 初期値に戻す

`Reset sampling to Voiceger defaults` では、Top K・Top P・Temperatureの3項目だけをVoicegerの初期値に戻せます。

ほかの設定は変更されません。

変更を保存するには、`[A] Apply and save`を実行してください。

## 設定変更と既存のTake

共通SettingsでStyle、Speed、Top K、Top P、Temperatureなど、音声生成の内容に影響する設定を変更すると、既存の候補Takeと採用状態がクリアされます。

すでにOutputへ保存したファイルは削除されません。

Take数や保存先など、音声生成の内容に影響しない設定だけを変更した場合は、既存の候補Takeが維持されます。

なお、`BATCH ITEM`で個別にStyleやSpeedを変更した場合は、既存のTakeを維持したまま、次に生成するTakeの設定を変更できます。

詳しくは[BATCH ITEM](batch-item.md)を参照してください。

## 設定ファイルの保存場所

設定は `config.json` に保存されます。

標準の保存場所はOSによって異なります。

**macOS**

```text
~/Library/Application Support/voiceger-editor/config.json
```

**Windows**

```text
%APPDATA%\voiceger-editor\config.json
```

**Linux**

```text
~/.config/voiceger-editor/config.json
```

環境変数などによって保存場所が変わる場合があります。

## コマンドラインから一時的に設定する

起動時のオプションで、一部の設定を一時的に上書きできます。

例えば、Take数を8、StyleをSweet、Speedを0.95にして起動する場合は、次のコマンドを使用します。

```bash
voiceger-editor --take-count 8 --style 1 --speed 0.95
```

この方法で指定した値は、保存済みの設定ファイルを直接変更しません。

詳しいオプションは、次のコマンドで確認できます。

```bash
voiceger-editor --help
```
