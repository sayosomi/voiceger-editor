# BATCH ITEM

`BATCH ITEM` 画面では、1つの Caption について発音を調整し、Take を生成・確認・採用します。

基本的な使い方を先に確認したい場合は、[TUI](tui.md) を参照してください。

## 画面の見方

```text
BATCH ITEM                                                  < 1 / 3 >

  Style 3 Neutral | Speed 1.00 | Takes 4 | TXT ON
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

その下には、現在の Style、Speed、Take 数、TXT 出力の設定と Output フォルダが表示されます。

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

日本語の場合は、たとえば次のように表示されます。

```text
JA | [キョ] ー ワ
   | [ア] メ ナ
   | ノ [ダ]。
```

`[]` で囲まれているモーラが、現在のアクセント位置です。

発音行にカーソルを合わせて Left / Right を押すと、アクセント位置を1モーラずつ移動できます。

Enter を押すと、日本語の読みやアクセントを詳しく編集できます。

英語では、ARPAbet の発音が表示されます。Left / Right で第一強勢の位置を移動し、Enter で ARPAbet を編集できます。

ARPAbet の音素や強勢の表記については [ARPAbet](arpabet.md) を参照してください。

詳しくは [発音編集](pronunciation.md) を参照してください。

### 発音情報を作り直す

`[P] Build pronunciation` を実行すると、現在の Caption から発音情報を作り直します。

```text
[P] Build pronunciation
```

手動で編集した発音情報がある場合は、置き換える前に確認されます。

発音情報を作り直すと、生成済みの Take と採用状態はクリアされます。

## Section を追加する

`[A] Add section` では、日本語・英語の Section を追加できます。

```text
[A] Add section
```

日本語英語混じり文の発音を調整するときに使用します。

詳しくは [発音編集](pronunciation.md) を参照してください。

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

## 設定を変更したとき

発音や音声生成に関係する設定を変更すると、現在の Take 候補と採用状態がクリアされることがあります。

設定項目について詳しくは [設定](settings.md) を参照してください。

## Output フォルダを変更する

`[F] Output` を選んで Enter を押すか、`F` を押すと、Output フォルダを直接編集できます。

```text
[F] Output: ~/.voiceger-editor/output
```

その他の出力設定については [設定](settings.md) を参照してください。

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
