# TUI

Voiceger Editor は、テキスト中心のインターフェースで、調声しながらトーク音声を生成できるエディタです。

## 【用語説明】

**Caption**  
Voiceger Editor では、音声にしたい文章を Caption という単位で管理します。1つのセリフが、基本的には1つの Caption です。

**Take**  
Caption から生成した候補音声を Take と呼びます。1つの Caption から複数の Take を生成し、聞き比べてから採用する Take を選んで保存します。

**BATCH LIST**  
Caption を一覧で管理する画面です。Caption の追加、一括生成する Caption の選択、複数 Caption の一括生成などを行います。

**BATCH ITEM**  
個別の Caption を編集する画面です。発音やアクセントの調整、Take の生成・再生・保存などを行います。

## 起動

```bash
voiceger-editor
```

最初の Caption を1つ指定して起動することもできます。

```bash
voiceger-editor "このずんだ餅はvery sweetなのだ。"
```

ここでは、Caption を指定せずに起動した場合の流れを説明します。

## 最初の Caption を登録する

普通に起動すると、Caption が0件の `BATCH LIST` が表示されます。

```text
BATCH LIST · 0/0 selected · 0 takes · Accepted 0/0

  Takes < 4 >

▶ [A] Add captions
  [G] Generate selected

  [R] Read batch
  [W] Write batch

  [S] Settings
  [D] Dictionary

  [?] Help
  [Q] Quit
```

最初は `[A] Add captions` が選択されています。

Enter を押すか、`A` を押して Caption の追加画面を開きます。

```text
ADD CAPTIONS

▶ 今日は雨なのだ。

  [A] Apply
  [C] Clear
  [R] Reset
  [Esc] Back
```

音声にしたい文章を入力します。

ここでは、

```text
今日は雨なのだ。
```

と入力しています。

Enter で文章の編集を終了し、`[A] Apply` を実行すると Caption が登録されます。

`BATCH LIST` に戻ると、登録した Caption が表示されます。

```text
BATCH LIST · 1/1 selected · 4 takes · Accepted 0/1

  Takes < 4 >

▶ [x] [1] 今日は雨なのだ。

  [A] Add captions
  [G] Generate selected

  [R] Read batch
  [W] Write batch

  [S] Settings
  [D] Dictionary

  [?] Help
  [Q] Quit
```

`[x]` は、この Caption が一括生成の対象になっていることを表します。

`[1]` は Caption の番号です。1〜9番の Caption は、対応する数字キーでも直接開けます。

今回はそのまま Enter を押します。選択した Caption の個別編集画面 `BATCH ITEM` が開きます。

## 発音を確認する

Caption を初めて開くと、発音情報が自動で作られます。

処理が終わると、`BATCH ITEM` は次のように表示されます。

```text
BATCH ITEM                                                  < 1 / 1 >

  Style 3 Neutral | Speed 1.00 | Takes 1 | TXT ON
  [F] Output: ~/.voiceger-editor/output

  [E] Caption : 今日は雨なのだ。
  [P] Build pronunciation

▶ JA | [キョ] ー ワ
     | [ア] メ ナ
     | ノ [ダ]。

  [A] Add section

  Candidates   No candidates yet.
  [G] Generate < 1 > takes

  [X] Delete caption

  [S] Settings
  [D] Dictionary
  [?] Help
  [Q] Quit
```

`Style`、`Takes`、`TXT`、`Output` などの表示は、現在の設定によって変わります。

`JA` から始まる部分が、自動で作られた日本語の発音情報です。

```text
JA | [キョ] ー ワ
   | [ア] メ ナ
   | ノ [ダ]。
```

この例では「今日は雨なのだ。」が3つのアクセント句に分かれています。

`[キョ]`、`[ア]`、`[ダ]` のように `[]` で囲まれているモーラが、それぞれのアクセント句の現在のアクセント位置です。

発音に問題がなければ、そのまま Take を生成できます。

発音やアクセントを直したい場合は、この発音表示を選んで編集します。詳しくは [発音編集](pronunciation.md) を参照してください。

## Take を生成する

`[G] Generate` を選んで Enter を押すと、Take の生成が始まります。

```text
[G] Generate < 1 > takes
```

この例では1つの Take を生成します。

生成する数は Left / Right で変更できます。

生成が終わると、作成した Take が `Candidates` に表示されます。

Take にカーソルを移動すると音声が再生されます。Space を押すと、選択している Take をもう一度再生できます。

複数の Take を生成した場合は、それぞれを聞き比べて採用するものを選びます。

採用する Take にカーソルを合わせて Enter を押します。

## 保存先を確認する

採用した Take は、`BATCH ITEM` 上部の `[F] Output` に表示されているフォルダへ保存されます。

デフォルトの保存先は次のとおりです。

```text
~/.voiceger-editor/output
```

保存先は `[F] Output` や `[S] Settings` から変更できます。

ファイル名や WAV / FLAC / MP3 などの出力形式も設定できます。詳しくは [設定](settings.md) を参照してください。

## BATCH LIST に戻る

Esc を押すと、`BATCH ITEM` から `BATCH LIST` に戻ります。

この例では次のように表示されます。

```text
BATCH LIST · 1/1 selected · 1 take · Accepted 1/1

  Takes < 1 >

▶ [x] [1]  今日は雨なのだ。

  [A] Add captions
  [G] Generate selected

  [R] Read batch
  [W] Write batch

  [S] Settings
  [D] Dictionary

  [?] Help

  [Q] Quit
```

`BATCH LIST` に戻っても、登録した Caption はそのまま残っています。

ここから別の Caption を追加したり、もう一度 `BATCH ITEM` を開いたりできます。

## 2本目の Caption を追加する

次は Caption をもう1つ追加してみます。

`BATCH LIST` で `[A] Add captions` を選んで Enter を押すか、`A` を押します。

今回は、

```text
明日も元気なのだ。
```

と入力します。

Enter で編集を終了し、`[A] Apply` を実行します。

`BATCH LIST` に戻ると、2つの Caption が並びます。

このように、`BATCH LIST` で複数の Caption を管理し、それぞれを `BATCH ITEM` で編集できます。

## 次に読む

ここまでが Voiceger Editor の基本的な使い方です。

より詳しい使い方については、以下のページを参照してください。

- [BATCH LIST](batch-list.md) — Caption の追加・管理・一括生成
- [BATCH ITEM](batch-item.md) — 個別の Caption の編集、Take の生成・再生・保存
- [発音編集](pronunciation.md) — 日本語の読み・アクセント、英語の ARPAbet
- [ARPAbet](arpabet.md) — 英語の音素と強勢の読み方・書き方
- [ユーザー辞書](dictionary.md) — 日本語・英語の単語を登録して再利用
- [設定](settings.md) — スタイル、話速、Take 数、保存先、出力形式など
