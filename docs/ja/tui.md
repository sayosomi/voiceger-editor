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

Caption を開くと、発音情報が自動で作られ、`BATCH ITEM` に日本語の読みとアクセントが表示されます。

`JA` は日本語の発音情報です。`[キョ]`、`[ア]`、`[ダ]` のように `[]` で囲まれているモーラが、アクセント句ごとのアクセント位置を示します。

発音の変更方法は [発音編集](pronunciation.md)、画面全体の操作は [BATCH ITEM](batch-item.md) を参照してください。

## Take を生成して採用する

発音を確認したら、`BATCH ITEM` の `[G] Generate` で Take を生成します。

作成された Take を再生して聞き比べ、採用するものを選んで Enter を押すと、音声が Output フォルダに保存されます。

Take の生成数、再生、個別の再生成、保存操作は [BATCH ITEM](batch-item.md) で説明しています。出力先や保存形式は [設定](settings.md) を参照してください。

## BATCH LIST に戻る

Esc を押すと `BATCH LIST` に戻ります。Caption はそのまま残り、別の Caption を追加して作業を続けられます。

Caption の追加や一括生成、一覧管理については [BATCH LIST](batch-list.md) を参照してください。

## 次に読む

ここまでが Voiceger Editor の基本的な使い方です。

より詳しい使い方については、以下のページを参照してください。

- [BATCH LIST](batch-list.md) — Caption の追加・管理・一括生成
- [BATCH ITEM](batch-item.md) — 個別の Caption の編集、Take の生成・再生・保存
- [発音編集](pronunciation.md) — 日本語の読み・アクセント、英語の ARPAbet
- [ARPAbet](arpabet.md) — 英語の音素と強勢の読み方・書き方
- [ユーザー辞書](dictionary.md) — 日本語・英語の単語を登録して再利用
- [設定](settings.md) — スタイル、話速、Take 数、保存先、出力形式など
