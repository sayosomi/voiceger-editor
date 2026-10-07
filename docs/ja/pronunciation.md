# 発音編集

Voiceger Editor では、Take を生成する前に発音やアクセントを編集できます。

日本語と英語では、編集方法が異なります。

## 日本語のアクセント位置を変更する

アクセント位置だけを変更する場合は、`BATCH ITEM` から直接操作できます。

たとえば、

```text
Caption : ずんだもん
▶ JA | ズ ン [ダ] モ ン
```

と表示されているとします。

発音行にカーソルを合わせて Left / Right を押すと、アクセント位置を1モーラずつ移動できます。

たとえば Left を使って、

```text
▶ JA | [ズ] ン ダ モ ン
```

のように変更できます。

アクセント句の区切りを変える必要がなければ、この操作だけで調整できます。

## 読みやアクセント句を詳しく編集する

読みそのものやアクセント句の区切りを変更したい場合は、発音行で Enter を押します。

`EDIT PRONUNCIATION` 画面が開きます。

たとえば、

```text
Caption : 今日は雨なのだ。

▶ JA | [キョ] ー ワ
     | [ア] メ ナ
     | ノ [ダ]。
```

という発音を開くと、次のように表示されます。

```text
EDIT PRONUNCIATION

Source
  今日は雨なのだ。

▶ キョ'ーワ ア'メナ ノダ'。

  [P] Preview
  [A] Apply
  [S] Save to dictionary
  [D] Dictionary menu
  [E] Edit text
  [C] Clear
  [R] Reset
  [Esc] Back
```

`Source` には元の文章、その下には編集中の発音が表示されます。

`'` は、アクセントを置くモーラの直後に入力します。

スペースはアクセント句の区切りです。

たとえば、

```text
キョ'ーワ ア'メナ ノダ'。
```

を、

```text
キョ'ーワ ア'メ ナ'ノダ。
```

に変更すると、`BATCH ITEM` では次のようになります。

```text
JA | [キョ] ー ワ
   | [ア] メ
   | [ナ] ノ ダ。
```

このように、`EDIT PRONUNCIATION` ではアクセント位置だけでなく、アクセント句の区切りも変更できます。

編集した発音は `[P] Preview` で音声を聞いて確認できます。Preview しただけでは Caption の発音には反映されず、通常の Take も作成されません。

問題なければ `[A] Apply` を実行して変更を反映します。

`[C] Clear` は編集中の発音欄を空にします。

`[R] Reset` は、`EDIT PRONUNCIATION` を開いた時点の発音に戻します。

Esc を押すと `BATCH ITEM` に戻ります。

発音やアクセントの変更を Apply すると、それまでに生成した Take と採用状態はクリアされます。

## Section の文章を編集する

`EDIT PRONUNCIATION` の `[E] Edit text` では、現在の発音に対応する Section の文章そのものを編集できます。

たとえば `[E] Edit text` を実行すると、次の画面が開きます。

```text
EDIT SECTION TEXT

Language
  Japanese

▶ 今日は雨なのだ。

  [P] Preview
  [A] Apply
  [R] Reset
  [Esc] Back
```

文章を、

```text
▶ 今日は晴れなのだ。
```

のように書き換え、`[P] Preview` で確認してから `[A] Apply` で反映します。

`[R] Reset` は、`EDIT SECTION TEXT` を開いた時点の文章に戻します。

Caption 全体の文章を編集する場合は、`BATCH ITEM` の `[E] Caption` を使用します。

## 日本語の発音の入力

ひらがな・カタカナのどちらでも入力できます。

小さい「ゃ」「ゅ」「ょ」などは、前の文字と合わせて1モーラとして扱われます。

たとえば、

```text
きゃ'
```

は1モーラにアクセントを置いた状態です。

句読点には、

```text
。 、 ？ ！ …
```

などを使用できます。

`.`、`,`、`?`、`!` などの半角記号を入力した場合は、対応する日本語の記号に変換されます。

## 英語の発音

英語の発音は ARPAbet で編集します。

`BATCH ITEM` では、たとえば次のように表示されます。

```text
EN | very   V [EH1] R IY0
```

母音の後ろの数字は強勢を表します。

- `0` — 強勢なし
- `1` — 第一強勢
- `2` — 第二強勢

ARPAbet の音素や書き方について詳しくは [ARPAbet](arpabet.md) を参照してください。

## 英語の第一強勢を変更する

英単語の発音行にカーソルを合わせ、Left / Right を押すと、第一強勢を置ける母音の間で位置を移動できます。

たとえば、

```text
▶ EN | very   V [EH1] R IY0
```

から、

```text
▶ EN | very   V EH0 R [IY1]
```

のように変更できます。

## ARPAbet を詳しく編集する

英単語の発音行で Enter を押すと、`EDIT PRONUNCIATION` 画面が開きます。

ARPAbet の音素列を直接編集できます。

たとえば `sweet` の発音は、

```text
S W IY1 T
```

のように入力します。

Voiceger Editor は Apply する前に、入力された音素が利用できるものか確認します。

Preview、Apply、Edit text、Clear、Reset などの操作は、日本語の `EDIT PRONUNCIATION` と同じです。

ARPAbet の音素一覧や強勢の書き方については [ARPAbet](arpabet.md) を参照してください。

## 日本語英語混じり文

日本語と英語は、1つの Caption の中で混在できます。

たとえば、

```text
[E] Caption : このずんだ餅はvery sweetなのだ。
[P] Build pronunciation

JA | コ [ノ]
   | [ズ] ン ダ モ チ ワ
EN | very   V [EH1] R IY0
   | sweet  S W [IY1] T
▶ JA | ナ ノ [ダ]。
```

のように、日本語部分と英語部分がそれぞれ表示されます。

日本語部分は日本語の読みとアクセント、英語部分は ARPAbet と強勢をそれぞれ編集できます。

Voiceger Editor では、日本語・英語のまとまりを Section として扱います。

必要に応じて `[A] Add section` から Section を追加できます。

Add section では、Left / Right で日本語・英語を選び、文章を入力して追加します。

## 発音を作り直す

`BATCH ITEM` の `[P] Build pronunciation` を実行すると、現在の Caption から発音情報を作り直せます。

```text
[P] Build pronunciation
```

手動で編集した発音情報がある場合は、置き換える前に確認されます。

作り直すと、生成済みの Take と採用状態はクリアされます。

## 発音を辞書に保存する

日本語・英語の `EDIT PRONUNCIATION` では、現在の発音をユーザー辞書に保存できます。

```text
[S] Save to dictionary
```

同じ単語を今後も同じ発音で読ませたい場合に使用します。

`[D] Dictionary menu` からユーザー辞書を開くこともできます。

詳しくは [ユーザー辞書](dictionary.md) を参照してください。

## 関連ページ

- [ARPAbet](arpabet.md)
- [BATCH ITEM](batch-item.md)
- [ユーザー辞書](dictionary.md)
