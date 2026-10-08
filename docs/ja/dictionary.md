# ユーザー辞書

Voiceger Editor では、日本語と英語のユーザー辞書を別々に管理できます。

よく使う単語の発音を登録しておくと、Caption を作るたびに発音を調整する手間を減らせます。

## 辞書を開く

`BATCH LIST` または `BATCH ITEM` で `[D] Dictionary` を実行すると、次の画面が開きます。

```text
DICTIONARY

▶ [J] Japanese       2 words
  [E] English        2 words
  [I] Import dictionary
  [X] Export dictionary

  [Esc] Back
```

`[J] Japanese` は日本語辞書、`[E] English` は英語辞書です。

`Import dictionary` では辞書ファイルを読み込み、`Export dictionary` では現在の辞書を書き出せます。

## 日本語辞書

`[J] Japanese` を開くと、登録済みの単語が一覧で表示されます。

```text
JAPANESE DICTIONARY

▶ [1] あめ          [ア] メ
  [2] ずんだもん    ズ ン [ダ] モ ン

  [S] Sort      < Surface ↑ >
  [F] Filter    Not set
  [A] Add
  [X] Delete
  [Esc] Back
```

単語の右側には、登録されている読みとアクセント位置が表示されます。

`[]` で囲まれている部分がアクセント位置です。

単語を選んで Enter を押すと編集画面が開きます。`1`〜`9` の数字キーでも、対応する単語を直接開けます。

10件以上ある場合は、`0` キーで番号を入力して移動できます。

### 単語を登録する

`[A] Add` を実行すると、`ADD JAPANESE DICTIONARY WORD` が開きます。

最初から `Surface` の入力が始まるので、登録したい単語をそのまま入力できます。

ここでは「ずんだもん」を例に説明します。

登録後の編集画面は次のようになります。

```text
EDIT JAPANESE DICTIONARY WORD                           < 2 / 2 >

▶ Surface        ずんだもん
  [G] Generate pronunciation

  Pronunciation  ズ ン [ダ] モ ン
  Word type      < 固有名詞 >
  Priority       < 5 >

  [P] Preview
  [S] Save

  [X] Delete

  [D] Dictionary menu
  [Esc] Back
```

各項目の意味は次のとおりです。

| 項目 | 内容 |
|---|---|
| Surface | 辞書で一致させる単語 |
| Pronunciation | カタカナの読みとアクセント位置 |
| Word type | 品詞 |
| Priority | 優先度（0〜10） |

`[G] Generate pronunciation` では、Surface から発音を自動生成できます。

生成された発音は、そのまま使うことも手動で調整することもできます。

### 読みとアクセントを編集する

`Pronunciation` にカーソルを合わせて Left / Right を押すと、アクセント位置を変更できます。

Enter を押すと、読みを直接編集できます。

たとえば「あめ」の場合、

```text
ア'メ
```

と、

```text
アメ'
```

ではアクセント位置が異なります。

日本語辞書の読みは、1つのアクセント句として登録します。

### 品詞と優先度

`Word type` は Left / Right で変更できます。

選べる品詞は、固有名詞・普通名詞・動詞・形容詞・接尾辞の5種類です。

新規登録時は「固有名詞」が選ばれています。

`Priority` は0〜10の範囲で変更できます。初期値は5です。

### 発音を確認して保存する

`[P] Preview` で音声を聞き、問題なければ `[S] Save` で保存します。

既存の単語を編集するときも、基本的な操作は同じです。

右上の `< 2 / 2 >` は、表示中の2件のうち2件目を開いていることを表します。ここにカーソルを合わせて Left / Right を押すか、`[` / `]` で前後の単語に移動できます。

## 英語辞書

`DICTIONARY` から `[E] English` を開きます。

```text
ENGLISH DICTIONARY

▶ [1] sweet     S W IY1 T
  [2] very      V EH1 R IY0

  [S] Sort      < Surface ↑ >
  [F] Filter    Not set
  [A] Add
  [X] Delete
  [Esc] Back
```

英語辞書では、発音が ARPAbet で表示されます。

ARPAbet の読み方については [ARPAbet](arpabet.md) を参照してください。

### 英単語を登録する

`[A] Add` を実行すると、`ADD ENGLISH DICTIONARY WORD` が開きます。

こちらも `Surface` の入力から始まります。

たとえば `very` を登録すると、編集画面は次のようになります。

```text
EDIT ENGLISH DICTIONARY WORD                            < 2 / 2 >

▶ Surface        very
  [G] Generate pronunciation

  Pronunciation  V EH1 R IY0

  [P] Preview
  [S] Save

  [X] Delete

  [D] Dictionary menu
  [Esc] Back
```

`[G] Generate pronunciation` で発音を自動生成できます。

`Pronunciation` にカーソルを合わせて Left / Right を押すと、第一強勢の位置を移動できます。

Enter を押すと、ARPAbet の音素列を直接編集できます。

編集後は `[P] Preview` で確認し、`[S] Save` で保存します。

英語辞書の単語照合では、大文字と小文字を区別しません。

## 一覧の並び替えと絞り込み

日本語・英語の辞書一覧には、共通して `Sort` と `Filter` があります。

### Sort

`[S] Sort` では、単語の表示順を変更できます。

`Sort` 行にカーソルを合わせて Left / Right を押しても切り替えられます。

日本語辞書では、Surface の昇順・降順、品詞、Priority の昇順・降順、追加順の昇順・降順を選べます。

英語辞書では、Surface と追加順をそれぞれ昇順・降順で表示できます。

### Filter

`[F] Filter` では、表示する単語を絞り込めます。

日本語辞書では Surface または Pronunciation で検索でき、品詞でも絞り込めます。

英語辞書では Surface または ARPAbet で検索できます。

一度条件を設定すると、一覧の `Filter` 行で Left / Right を押して絞り込みの ON / OFF を切り替えられます。OFF にしても設定した条件は残ります。

## 辞書をインポートする

`DICTIONARY` から `[I] Import dictionary` を実行します。

JSON ファイルのパスを入力して `[I] Review file` を実行すると、取り込み前の確認画面が開きます。

たとえば、次の3件を含むファイルを読み込んだ場合です。

| 単語 | 読み | 現在の辞書との関係 |
|---|---|---|
| ずんだもち | ズンダ'モチ | 新規 |
| あめ | アメ' | 競合 |
| ずんだもん | ズンダ'モン | 完全一致 |

```text
IMPORT DICTIONARY

3 words found
1 already exist
2 to review

▶ [x]   ずんだもち  固有名詞
  [ ] ! あめ        普通名詞

  [I] Import selected
  [C] Clear selection
  [Esc] Back
```

画面上部の数字には、次の意味があります。

- `3 words found`：ファイルから3件見つかった
- `1 already exist`：1件は現在の辞書と完全一致
- `2 to review`：残り2件が確認対象

新規の単語は最初から選択されています。

既存の単語と内容が競合する場合は、`!` が表示され、最初は未選択になっています。

完全一致の単語は確認一覧に表示されません。

### 取り込む単語を選ぶ

Space で選択・選択解除できます。

Enter を押すと、その単語の詳細を確認できます。

日本語辞書の詳細画面では、取り込み前に品詞を変更できます。読み・アクセント・優先度は変更できません。

英語辞書の詳細画面は確認専用です。

選択を終えたら `[I] Import selected` を実行します。選択した単語だけが取り込まれます。

`[C] Clear selection` では、確認一覧の選択をすべて解除できます。

取り込みを確定せずに戻る場合は Esc を押します。

### 読み込めるファイル

Voiceger Editor は、ファイル名ではなく JSON の内容から辞書の形式を判別します。

読み込めるのは、VOICEVOX 形式の日本語ユーザー辞書、Voiceger Editor から書き出した日本語辞書、Voiceger Editor 形式の英語辞書です。

VOICEVOX の日本語ユーザー辞書は、変換せずに読み込めます。

Import のファイルパスには、保存済みの Output フォルダが初期値として使われます。読み込むファイルのパスを変更しても、Output の設定は変わりません。

## 辞書をエクスポートする

`DICTIONARY` から `[X] Export dictionary` を実行します。

```text
EXPORT DICTIONARY

  [F] Output: ~/.voiceger-editor/output

▶ [E] Voiceger Editor
  Japanese + English

  [V] VOICEVOX
  Japanese dictionary only

  [Esc] Back
```

### Voiceger Editor 形式

`[E] Voiceger Editor` を実行すると、日本語辞書と英語辞書を別々の JSON ファイルとして出力します。

```text
YYYYMMDDHHMM_user_dict.json
YYYYMMDDHHMM_english_user_dict.json
```

### VOICEVOX 形式

`[V] VOICEVOX` を実行すると、日本語辞書だけを VOICEVOX 互換形式で出力します。

```text
YYYYMMDDHHMM_voicevox_user_dict.json
```

英語辞書は含まれません。

### 保存先

出力先は `[F] Output` に表示されます。

`F` を押すと、Output フォルダを直接変更できます。この変更は共通の Output 設定にも反映されます。

出力先に同名ファイルがある場合は、上書きせず、ファイル名に `-2`、`-3` などが追加されます。

## 発音編集画面から辞書に保存する

`BATCH ITEM` の `EDIT PRONUNCIATION` 画面からも、発音を辞書に登録できます。

```text
[S] Save to dictionary
```

これを実行すると、編集中の発音を引き継いで、日本語または英語の辞書登録画面が開きます。

詳しくは [発音編集](pronunciation.md) を参照してください。

## 登録した単語を削除する

辞書一覧で単語を選び、`[X] Delete` を実行します。

単語の編集画面から削除することもできます。

削除前には確認画面が表示されます。

また、編集内容を保存せずに画面を離れようとした場合も、変更を破棄するか確認されます。

## 辞書ファイルの保存場所

通常の辞書ファイルは、Voiceger Editor の設定ファイルと同じフォルダに保存されます。

| 辞書 | ファイル名 |
|---|---|
| 日本語辞書 | `user_dict.json` |
| 英語辞書 | `english_user_dict.json` |

OS ごとの標準の保存先は次のとおりです。

| OS | 保存先 |
|---|---|
| macOS | `~/Library/Application Support/voiceger-editor/` |
| Windows | `%APPDATA%\voiceger-editor\` |
| Linux | `~/.config/voiceger-editor/` |

Windows で `APPDATA` が設定されていない場合は、`%USERPROFILE%\AppData\Roaming\voiceger-editor\` が使われます。

Linux などでは、`XDG_CONFIG_HOME` が設定されていればその場所が優先されます。

これらは Voiceger Editor が管理するファイルであり、Voiceger 本体の辞書ファイルとは別です。

## HTTP API との関係

日本語・英語のユーザー辞書は、HTTP API からも操作できます。

TUI と HTTP API は同じ辞書ファイルを使用します。

詳しい操作方法は [HTTP API](api.md) を参照してください。

## 関連ページ

- [発音編集](pronunciation.md)
- [ARPAbet](arpabet.md)
- [設定](settings.md)
- [HTTP API](api.md)
