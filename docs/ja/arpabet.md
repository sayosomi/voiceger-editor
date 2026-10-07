# ARPAbet

Voiceger Editor では、英語の発音を **ARPAbet** という音素表記で編集します。

たとえば `very` の発音は次のように表します。

```text
V EH1 R IY0
```

英単語のつづりそのものではなく、**どの音をどの順番で発音するか**を書いたものです。

## BATCH ITEM での表示

`BATCH ITEM` では、たとえば次のように表示されます。

```text
EN | very   V [EH1] R IY0
   | sweet  S W [IY1] T
```

`[]` で囲まれている音が、現在の第一強勢です。

この `[]` は BATCH ITEM 上の表示です。

詳細編集画面では、

```text
V EH1 R IY0
```

のように、ARPAbet 本来の数字付き表記を直接編集します。

## 強勢の数字

ARPAbet では、母音の末尾につく数字で強勢を表します。

| 数字  | 意味   |
| --- | ---- |
| `0` | 強勢なし |
| `1` | 第一強勢 |
| `2` | 第二強勢 |

たとえば、

```text
V EH1 R IY0
```

では `EH` に第一強勢があり、`IY` には強勢がありません。

子音には数字を付けません。

```text
S W IY1 T
```

の `S`、`W`、`T` には数字を付けず、母音の `IY` にだけ `1` を付けます。

## Voiceger Editor で使える母音

Voiceger Editor では、次の母音を使用できます。

| 音素   | おおまかな例          |
| ---- | --------------- |
| `AA` | hot の母音         |
| `AE` | cat の母音         |
| `AH` | cut、about などの母音 |
| `AO` | law の母音         |
| `AW` | now の母音         |
| `AY` | my の母音          |
| `EH` | bed の母音         |
| `ER` | bird の母音        |
| `EY` | say の母音         |
| `IH` | sit の母音         |
| `IY` | see の母音         |
| `OW` | go の母音          |
| `OY` | boy の母音         |
| `UH` | book の母音        |
| `UW` | food の母音        |

通常は、これらの母音に `0`、`1`、`2` のいずれかを付けて入力します。

```text
AE1
IY0
OW1
```

## Voiceger Editor で使える子音

使用できる子音は次のとおりです。

```text
B   CH  D   DH  F   G   HH
JH  K   L   M   N   NG  P
R   S   SH  T   TH  V   W
Y   Z   ZH
```

いくつか、つづりだけでは分かりにくいものがあります。

| 音素   | おおまかな例        |
| ---- | ------------- |
| `CH` | chair の ch    |
| `DH` | this の th     |
| `HH` | hello の h     |
| `JH` | judge の j     |
| `NG` | sing の ng     |
| `SH` | she の sh      |
| `TH` | think の th    |
| `ZH` | measure の中央の音 |

`TH` と `DH` はどちらも英語の `th` に使われますが、音が異なります。

```text
think → TH
this  → DH
```

## 単語の例

### very

```text
V EH1 R IY0
```

### sweet

```text
S W IY1 T
```

### hello

```text
HH AH0 L OW1
```

音素は半角スペースで区切って並べます。

## 第一強勢を移動する

`BATCH ITEM` では、英単語の発音行にカーソルを合わせて Left / Right を押すと、第一強勢を母音の間で移動できます。

たとえば、

```text
▶ EN | very   V [EH1] R IY0
```

から、

```text
▶ EN | very   V EH0 R [IY1]
```

のように変更できます。

ARPAbet では、

```text
V EH1 R IY0
```

から、

```text
V EH0 R IY1
```

へ変わったことになります。

## ARPAbet を直接編集する

英単語の発音行で Enter を押すと、`EDIT PRONUNCIATION` が開きます。

```text
EDIT PRONUNCIATION

Word
  sweet

▶ S W IY1 T

  [P] Preview
  [A] Apply
  [S] Save to dictionary
  [D] Dictionary menu
  [E] Edit text
  [C] Clear
  [R] Reset
  [Esc] Back
```

音素は半角スペースで区切って入力します。

編集した発音は `[P] Preview` で確認し、問題なければ `[A] Apply` で反映します。

Voiceger Editor が対応していない音素を入力すると、Apply する前にエラーになります。

## 発音が分からないとき

最初から ARPAbet をすべて手入力する必要はありません。

Caption を開くと、Voiceger が英語のつづりから発音情報を自動で作ります。

まず自動生成された発音を聞き、必要なところだけ Voiceger Editor で変更する使い方が基本です。

たとえば、

```text
sweet
```

から自動で、

```text
S W IY1 T
```

が作られたあと、必要に応じて音素や強勢を修正します。

## ユーザー辞書と ARPAbet

調整した英単語の発音は、英語ユーザー辞書に保存できます。

同じ単語を何度も使う場合は、発音を辞書に登録しておくと毎回編集する必要がありません。

詳しくは [ユーザー辞書](dictionary.md) を参照してください。

## 日本語を ARPAbet で近似する

ARPAbet は英語用の音素表記ですが、音素を組み合わせて日本語っぽい音を作ることもできます。

**これは実用的な日本語発音のためではなく、遊び用途です。**

また、このような特殊な音素列では **[LAB 出力](lab-output.md) がうまくいかない可能性が高いです**。

### 五十音の目安

| 行 | あ段      | い段      | う段       | え段      | お段      |
| - | ------- | ------- | -------- | ------- | ------- |
| あ | `AA`    | `IY`    | `UW`     | `EH`    | `OW`    |
| か | `K AA`  | `K IY`  | `K UW`   | `K EH`  | `K OW`  |
| が | `G AA`  | `G IY`  | `G UW`   | `G EH`  | `G OW`  |
| さ | `S AA`  | `SH IY` | `S UW`   | `S EH`  | `S OW`  |
| ざ | `Z AA`  | `JH IY` | `Z UW`   | `Z EH`  | `Z OW`  |
| た | `T AA`  | `CH IY` | `T S UW` | `T EH`  | `T OW`  |
| だ | `D AA`  | `JH IY` | `Z UW`   | `D EH`  | `D OW`  |
| な | `N AA`  | `N IY`  | `N UW`   | `N EH`  | `N OW`  |
| は | `HH AA` | `HH IY` | `F UW`   | `HH EH` | `HH OW` |
| ば | `B AA`  | `B IY`  | `B UW`   | `B EH`  | `B OW`  |
| ぱ | `P AA`  | `P IY`  | `P UW`   | `P EH`  | `P OW`  |
| ま | `M AA`  | `M IY`  | `M UW`   | `M EH`  | `M OW`  |
| や | `Y AA`  | —       | `Y UW`   | —       | `Y OW`  |
| ら | `R AA`  | `R IY`  | `R UW`   | `R EH`  | `R OW`  |
| わ | `W AA`  | —       | —        | —       | `OW`    |

### 拗音

| 系列       | あ         | う         | お         |
| -------- | --------- | --------- | --------- |
| きゃ・きゅ・きょ | `K Y AA`  | `K Y UW`  | `K Y OW`  |
| ぎゃ・ぎゅ・ぎょ | `G Y AA`  | `G Y UW`  | `G Y OW`  |
| しゃ・しゅ・しょ | `SH AA`   | `SH UW`   | `SH OW`   |
| じゃ・じゅ・じょ | `JH AA`   | `JH UW`   | `JH OW`   |
| ちゃ・ちゅ・ちょ | `CH AA`   | `CH UW`   | `CH OW`   |
| にゃ・にゅ・にょ | `N Y AA`  | `N Y UW`  | `N Y OW`  |
| ひゃ・ひゅ・ひょ | `HH Y AA` | `HH Y UW` | `HH Y OW` |
| みゃ・みゅ・みょ | `M Y AA`  | `M Y UW`  | `M Y OW`  |
| りゃ・りゅ・りょ | `R Y AA`  | `R Y UW`  | `R Y OW`  |

### 「ん」

日本語の「ん」は、後ろに続く音によって `N`、`M`、`NG` を使い分けると自然になることがあります。

| 日本語の音       | 目安   |
| ----------- | ---- |
| んか・んが など    | `NG` |
| んば・んぱ・んま など | `M`  |
| その他         | `N`  |

語末では `N` と `NG` の両方を試して、自然に聞こえる方を使うのが実用的です。

### 長音

日本語の長母音にそのまま対応する記号はありません。

| 日本語の音 | 近似の目安 |
| ----- | ----- |
| おー    | `OW`  |
| えー    | `EY`  |
| いー    | `IY`  |
| うー    | `UW`  |

### 外来音

| 系列            | あ      | い      | う      | え      | お      |
| ------------- | ------ | ------ | ------ | ------ | ------ |
| ファ・フィ・フ・フェ・フォ | `F AA` | `F IY` | `F UW` | `F EH` | `F OW` |
| ヴァ・ヴィ・ヴ・ヴェ・ヴォ | `V AA` | `V IY` | `V UW` | `V EH` | `V OW` |

そのほか、

| 日本語 | ARPAbet |
| --- | ------- |
| ティ  | `T IY`  |
| ディ  | `D IY`  |
| トゥ  | `T UW`  |
| ドゥ  | `D UW`  |

のように近似できます。

### 強勢を付ける

日本語を ARPAbet で近似する場合も、母音には強勢数字を付けます。

たとえば「ずんだもん」なら、

```text
Z UW1 N D AA0 M OW0 N
```

のように、まず1か所を第一強勢 `1` にし、それ以外を `0` にして試せます。

英語の強勢と日本語のアクセントは同じものではありません。ここでの数字は、日本語のアクセントを厳密に記述するものではありません。

## 関連ページ

- [発音編集](pronunciation.md)
- [BATCH ITEM](batch-item.md)
- [ユーザー辞書](dictionary.md)
- [LAB 出力](lab-output.md)
