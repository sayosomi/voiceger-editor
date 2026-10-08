# BATCH ITEM

`BATCH ITEM` 画面では、1つの Caption について発音を調整し、Take を生成・確認・採用します。

基本的な使い方を先に確認したい場合は、[TUI](tui.md) を参照してください。

## 画面の見方

```text
BATCH ITEM                                                  < 1 / 3 >

  Neutral | 1.00x | Takes 4 | TXT ON | LAB OFF
  [F] Output: ~/.voiceger-editor/output

  [E] Caption : 今日は雨なのだ。
  [P] Build pronunciation

▶ JA | [キョ] ー ワ
     | [ア] メ ナ
     | ノ [ダ]。

  [A] Add section

  Candidates   No candidates yet.
  [G] Generate < 4 > takes

  [X] Delete caption

  [S] Settings
  [D] Dictionary
  [?] Help
  [Q] Quit
```

画面上部の、

```text
< 1 / 3 >
```

は、3件ある Caption のうち1件目を開いていることを表します。

その下には、現在のスタイル名、話速（`1.00x` など）、Take 数、TXT・LAB 出力の ON/OFF と Output フォルダが表示されます。

## 前後の Caption に移動する

`[` / `]` で前後の Caption に移動できます。

画面上部の、

```text
< 1 / 3 >
```

にカーソルを合わせた場合は、Left / Right でも移動できます。

最初の Caption からさらに前へ、最後の Caption からさらに後ろへ移動することはできません。

Esc を押すと `BATCH LIST` に戻ります。

## Caption を編集する

`[E] Caption` を選んで Enter を押すか、`E` を押すと、Caption の文章を編集できます。

```text
[E] Caption : 今日は雨なのだ。
```

Enter で編集を終了します。

Caption を変更すると、発音情報を含め、音声生成に関係する状態も更新する必要があります。

## 発音を確認・編集する

Caption を初めて開くと、発音情報が自動で作られます。

`JA` には日本語の読みとアクセント、`EN` には英語の ARPAbet と強勢が表示されます。

**読みやアクセントの変更、Section の追加、`[P] Build pronunciation` による発音の作り直し**は [発音編集](pronunciation.md) を参照してください。音素の表記については [ARPAbet](arpabet.md) で説明しています。

## Take を生成する

`[G] Generate` を選んで Enter を押すか、`G` を押すと Take を生成します。

```text
[G] Generate < 4 > takes
```

Left / Right で、一度に生成する Take 数を変更できます。

生成中は現在の進捗が表示されます。

```text
Generating 2/4
```

画面下部にも生成状況が表示されます。

生成中に Esc を押して `BATCH LIST` に戻っても、生成はバックグラウンドで続きます。

生成をキャンセルする場合は `Ctrl+C` を押します。

## Take を聞く

生成が終わると、`Candidates` に Take が並びます。

```text
Candidates

▶ [1] Take 1  2.41s
  [2] Take 2  2.36s
  [3] Take 3  2.44s
  [4] Take 4  2.39s
```

Take にカーソルを移動すると、その音声が再生されます。

Space を押すと、選択中の Take をもう一度再生できます。

`1`〜`9` を押すと、対応する Take に直接移動して再生できます。

## 1つの Take だけ作り直す

作り直したい Take にカーソルを合わせて `R` を押すと、その Take だけを再生成できます。

ほかの Take はそのまま残ります。

## Take を採用する

採用したい Take にカーソルを合わせて Enter を押します。

採用した Take は Output フォルダへ保存され、`✓` が表示されます。

```text
Candidates
▶ [1] ✓ Take 1  2.10s
  [2] Take 2  1.90s
```

Take を採用しても、ほかの候補は消えません。そのまま聞き比べたり、別の Take を再生成したりできます。

保存先やファイル形式については [設定](settings.md) を参照してください。

## Take をすべて作り直す

候補がすでにある場合、`[G] Generate` は `[G] Regenerate all` に変わります。

```text
[G] Regenerate all < 4 > takes
```

実行すると、現在の候補をすべて新しい Take に置き換えます。

## 候補を削除する

`[C] Clear candidates` を実行すると、現在の Take 候補をすべて削除できます。

```text
[C] Clear candidates
```

削除前に確認画面が表示されます。

生成中は候補を削除できません。

## 出力先と設定

`[F] Output` または `F` キーから、Output フォルダを直接編集できます。

出力形式や TXT・LAB の切り替えなど、詳しい設定方法は [設定](settings.md) を参照してください。

## Caption を削除する

`[X] Delete caption` を実行すると、現在開いている Caption を削除できます。

```text
[X] Delete caption
```

削除前に確認画面が表示されます。

Caption を削除すると、その Caption の一時的な Take も削除されます。

## 関連ページ

- [発音編集](pronunciation.md)
- [ARPAbet](arpabet.md)
- [設定](settings.md)
- [BATCH LIST](batch-list.md)
