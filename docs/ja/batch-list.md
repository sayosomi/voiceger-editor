# BATCH LIST

`BATCH LIST` 画面では、Caption を一覧で管理することができます。

基本的な使い方を先に確認したい場合は、[TUI](tui.md) を参照してください。

## 画面の見方

Caption が3件あるとき、例えば次のように表示されます。

```text
BATCH LIST · 2/3 selected · 8 takes · Accepted 1/3

  Takes < 4 >

▶ [x] [1]  [✓] 今日は雨なのだ。
  [x] [2]  [!] このずんだ餅はvery sweetなのだ。
  [ ] [3]      明日も元気なのだ。

  [A] Add captions
  [G] Generate selected

  [R] Read batch
  [W] Write batch

  [S] Settings
  [D] Dictionary

  [?] Help
  [Q] Quit
```

一番上には、現在の Caption 数や生成設定が表示されます。

```text
BATCH LIST · 2/3 selected · 8 takes · Accepted 1/3
```

この例では、

- Caption が全部で3件
- そのうち2件を一括生成の対象として選択中
- Caption 2件 × 4 Takes = 合計 8 件の Takes が生成される
- Caption 3件中1件で Take を採用済み

という状態です。

`Takes < 4 >` は、一括生成するときの Caption 1件あたりの Take 数です。

## Caption の状態

各 Caption の左側には、現在の状態が表示されます。

```text
[x] [1]  [✓] 今日は雨なのだ。
[x] [2]  [!] このずんだ餅はvery sweetなのだ。
[ ] [3]      明日も元気なのだ。
```

`[x]` は一括生成の対象、`[ ]` は対象外です。

`[✓]`、`[!]` 等は、生成・確認の状態を表します。

- `[✓]` — 採用した Take がある
- `[!]` — Take の生成が完了していて、まだ採用する Take を選んでいない
- `[⚠]` — 生成がキャンセルされた、または失敗した
- 状態表示なし — まだ Take を生成していない

生成中は、この状態表示の代わりに進捗が%で表示されます。

```text
[x] [2]  [25%] このずんだ餅はvery sweetなのだ。
```

## Caption を追加する

`[A] Add captions` を選んで Enter を押すか、`A` を押します。

```text
[A] Add captions
```

1行入力すると、Caption が1件追加されます。

```text
今日は雨なのだ。
```

複数行をまとめて入力することもできます。改行するときは Ctrl+N を使います。

```text
今日は雨なのだ。
このずんだ餅はvery sweetなのだ。
明日も元気なのだ。
```

この場合は、1行ずつ別々の Caption として追加されます。

空行は無視されます。

複数行の文章をそのままペーストすることもできます。

Enter は改行ではなく、テキスト編集の終了です。

編集を終了したあと、`[A] Apply` を実行すると Caption が追加されます。

別 Caption の音声を生成中でも、新しい Caption の追加は可能です。

## Caption を開く

Up / Down で Caption を選び、Enter を押すと、その Caption の `BATCH ITEM` が開きます。

```text
▶ [x] [1] 今日は雨なのだ。
```

1〜9番の Caption は、対応する数字キーでも直接開けます。

たとえば `2` を押すと、2番目の Caption が開きます。

Caption が10件以上ある場合は、`[0] Jump to Caption` が表示されます。

```text
[0] Jump to Caption
```

`0` を押すと番号入力に切り替わります。

たとえば Caption が15件あり、12番を開きたい場合は次のように入力します。

```text
▶ Jump to Caption: 12_ / 15
  [Enter] Open   [Esc] Cancel
```

番号を入力して Enter を押すと、その Caption が開きます。

Esc で番号入力をキャンセルできます。

存在しない番号を入力した場合は Warning が表示され、番号入力はそのまま続けられます。

Caption を削除する場合は、その Caption の `BATCH ITEM` を開いて `[X] Delete caption` を使用します。

## 一括生成する Caption を選ぶ

Caption にカーソルを合わせて Space を押すと、一括生成の対象を切り替えられます。

```text
[x]  一括生成する
[ ]  一括生成しない
```

複数の Caption を選択できます。

`[G] Generate selected` を実行すると、`[x]` が付いている Caption だけが生成されます。

## 一括生成する Take 数を変更する

`Takes` にカーソルを合わせ、Left / Right で Take 数を変更します。

```text
Takes < 4 >
```

たとえば2件の Caption が選択され、`Takes < 4 >` になっている場合は、Caption 2件 × 4 Takes = 合計8件の Take が生成されます。

```text
BATCH LIST · 2/3 selected · 8 takes · Accepted 0/3
```

## 選択した Caption をまとめて生成する

`[G] Generate selected` を選んで Enter を押すか、`G` を押します。

```text
[G] Generate selected
```

`[x]` が付いている Caption の Take が順番に生成されます。

生成中は、現在処理している Caption に進捗が表示されます。

```text
[x] [2]  [25%] このずんだ餅はvery sweetなのだ。
```

画面下部にも進捗が表示されます。

```text
Generating selected · Caption 2 · Take 2/4 · Overall 6/8 · [Ctrl+C] Cancel generation
```

生成中に別の画面へ移動しても、生成はバックグラウンドで続きます。

Voiceger Editor が同時に実行できる音声生成は1つだけです。

すでに音声生成中の場合、別の Caption について `[G] Generate` を実行しても、新しい生成は開始されず、キューにも追加されません。

その場合は、生成中の処理を完了するかキャンセルしてから、次の生成を実行します。

## 一括生成をキャンセルする

生成中に `Ctrl+C` を押すと、キャンセルを要求できます。

キャンセルは Take の生成途中で強制終了するのではなく、安全な区切りで行われます。

すでに生成が完了した Take は残ります。

キャンセル後の Caption には `[⚠]` が表示されます。

## 採用済みの Caption

`BATCH ITEM` で Take を採用すると、`BATCH LIST` の Caption に `[✓]` が表示されます。

```text
[x] [1]  [✓] 今日は雨なのだ。
```

画面上部の `Accepted` 欄でも、採用済み Caption の数を確認できます。

```text
Accepted 1/3
```

採用した Take の確認や再生成は、その Caption の `BATCH ITEM` 画面で行います。

## バッチファイルを保存する

現在の Caption 一覧は、バッチファイルとして保存できます。

`[W] Write batch` を選んで Enter を押すか、`W` を押します。

```text
[W] Write batch
```

バッチファイルの推奨拡張子は次のとおりです。

```text
.voiceger.json
```

デフォルトのファイル名は、

```text
batch.voiceger.json
```

です。

ファイルは現在の Output フォルダに保存されます。

Output フォルダは Settings から変更できます。詳しくは [設定](settings.md) を参照してください。

バッチファイルには、Caption や発音情報、音声生成に必要な設定などが保存されます。

保存する Caption は、あらかじめ発音情報が作られている必要があります。

バッチファイルは人間が読める JSON 形式なので、保存後に VS Code などで編集してから読み直すこともできます。

### バッチファイルに保存されないもの

バッチファイルは、作業状態をそのまま復元するためのスナップショットではありません。

次の情報は保存されません。

- 生成済みの Take
- 採用した Take の状態
- 再生状態
- 生成中の進捗

バッチファイルを読み込んだあとは、必要な Take を改めて生成します。

## バッチファイルを読み込む

`[R] Read batch` を選んで Enter を押すか、`R` を押します。

```text
[R] Read batch
```

読み込むファイルのパスを入力します。初期値には現在の Output フォルダが表示されます。

すでに Caption が登録されている場合は、現在の `BATCH LIST` を置き換えるか確認されます。

キャンセルした場合やファイルを読み込めなかった場合は、現在の `BATCH LIST` は変更されません。

## 関連ページ

- [BATCH ITEM](batch-item.md)
- [設定](settings.md)
- [ユーザー辞書](dictionary.md)
